from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_role
from ..models import ChatMessage, Dashboard, DataSource, Widget
from ..schemas import ChatRequest
from ..services.llm import LLMError, get_llm
from ..services.planner import AgentError, run_agent
from .canvas import serialize

router = APIRouter(prefix="/api/agent", tags=["agent"])


def _message(m: ChatMessage) -> dict:
    return {"id": m.id, "role": m.role, "content": m.content, "selection": m.selection, "status": m.status,
            "clarification": m.clarification, "change_set_id": m.change_set_id, "created_at": m.created_at.isoformat()}


def _pick_source(db: Session, req: ChatRequest) -> DataSource:
    ds_id = req.data_source_id
    for wid in req.selection.widget_ids:
        w = db.get(Widget, wid)
        if w is not None:
            ds_id = w.dashboard.data_source_id
    for did in req.selection.dashboard_ids:
        d = db.get(Dashboard, did)
        if d is not None:
            ds_id = d.data_source_id
    ds = db.get(DataSource, ds_id) if ds_id else db.query(DataSource).order_by(DataSource.created_at).first()
    if ds is None:
        raise HTTPException(400, "no data source available; connect one in the Metadata tab")
    return ds


@router.get("/messages")
def messages(limit: int = 100, db: Session = Depends(get_db)) -> list[dict]:
    rows = db.query(ChatMessage).order_by(ChatMessage.created_at.desc()).limit(min(limit, 500)).all()
    return [_message(m) for m in reversed(rows)]


@router.delete("/messages")
def clear_messages(db: Session = Depends(get_db)) -> dict:
    db.query(ChatMessage).delete()
    db.commit()
    return {"cleared": True}


@router.post("/chat")
def chat(req: ChatRequest, db: Session = Depends(get_db), role: str = Depends(get_role)) -> dict:
    if not req.prompt.strip():
        raise HTTPException(400, "prompt is empty")
    ds = _pick_source(db, req)
    user_msg = ChatMessage(role="user", content=req.prompt.strip(), selection=req.selection.model_dump())
    db.add(user_msg)
    db.commit()

    try:
        llm = get_llm()
        outcome = run_agent(db, llm, req, ds, role)
    except (LLMError, AgentError) as exc:
        db.rollback()
        reply = ChatMessage(role="assistant", content=str(exc), status="error")
        db.add(reply)
        db.commit()
        return {"message": _message(reply), "dashboards": [], "removed": []}
    except Exception as exc:  # gateway/network failures
        db.rollback()
        reply = ChatMessage(role="assistant", status="error",
                            content=f"The model gateway call failed: {type(exc).__name__}: {str(exc)[:300]}")
        db.add(reply)
        db.commit()
        return {"message": _message(reply), "dashboards": [], "removed": []}

    plan = outcome["plan"]
    cs = outcome["change_set"]
    reply = ChatMessage(
        role="assistant",
        content=plan.clarification.question if plan.clarification else (plan.message or "Done."),
        clarification=plan.clarification.model_dump() if plan.clarification else None,
        status="clarification" if plan.clarification else "ok",
        change_set_id=cs.id if cs else None,
    )
    db.add(reply)
    db.commit()
    dashboards = [serialize(db, d, role) for did in outcome["touched"] if (d := db.get(Dashboard, did))]
    return {"message": _message(reply), "dashboards": dashboards, "removed": outcome["removed"],
            "created": [did for did, snap in (cs.before.items() if cs else []) if snap is None]}

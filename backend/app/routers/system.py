from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..deps import get_role, require_admin
from ..models import AgentCall
from ..services.compiler import ROLES

router = APIRouter(prefix="/api", tags=["system"])


@router.get("/health")
def health() -> dict:
    return {"status": "ok"}


@router.get("/config")
def config() -> dict:
    s = get_settings()
    return {
        "llm_configured": s.llm_configured,
        "model": s.openai_model,
        "gateway": s.openai_base_url or "https://api.openai.com/v1",
        "roles": list(ROLES),
        "limits": {"default_rows": s.default_row_limit, "max_rows": s.max_row_limit,
                   "timeout_seconds": s.query_timeout_seconds},
    }


@router.get("/audit/agent-calls")
def agent_calls(limit: int = 20, db: Session = Depends(get_db), role: str = Depends(get_role)) -> list[dict]:
    """Everything sent to the model, for verifying that no business records cross the boundary."""
    require_admin(role)
    calls = db.query(AgentCall).order_by(AgentCall.created_at.desc()).limit(min(limit, 100)).all()
    return [
        {"id": c.id, "purpose": c.purpose, "model": c.model, "created_at": c.created_at.isoformat(),
         "duration_ms": c.duration_ms, "error": c.error, "request": c.request, "response": c.response}
        for c in calls
    ]

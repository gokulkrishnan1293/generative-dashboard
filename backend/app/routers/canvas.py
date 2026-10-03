from fastapi import APIRouter, Depends, HTTPException
from pydantic import ValidationError
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_role
from ..models import CanvasState, ChangeSet, Dashboard, DataSource, Widget
from ..schemas import DashboardCreate, DashboardPatch, MetadataDoc, Presentation, QueryPlan, Viewport, WidgetPatch
from ..services.compiler import Catalog, CompileError, compile_plan
from ..services.dashboards import ChangeRecorder, dashboard_dict, restore, snapshot, widget_dict
from ..services.executor import ExecutionError, dialect_of, effective_plan, execute_plan
from ..config import get_settings

router = APIRouter(prefix="/api", tags=["canvas"])


def _ds(db: Session, ds_id: str) -> DataSource:
    ds = db.get(DataSource, ds_id)
    if ds is None:
        raise HTTPException(404, "data source not found")
    return ds


def _dashboard(db: Session, dashboard_id: str) -> Dashboard:
    d = db.get(Dashboard, dashboard_id)
    if d is None:
        raise HTTPException(404, "dashboard not found")
    return d


def _widget(db: Session, widget_id: str) -> Widget:
    w = db.get(Widget, widget_id)
    if w is None:
        raise HTTPException(404, "widget not found")
    return w


def serialize(db: Session, d: Dashboard, role: str) -> dict:
    return dashboard_dict(d, db.get(DataSource, d.data_source_id), role)


@router.get("/canvas")
def get_canvas(db: Session = Depends(get_db), role: str = Depends(get_role)) -> dict:
    state = db.get(CanvasState, 1)
    sources = {ds.id: ds for ds in db.query(DataSource).all()}
    return {
        "viewport": state.viewport if state else {"x": 0, "y": 0, "zoom": 1},
        "dashboards": [
            dashboard_dict(d, sources.get(d.data_source_id), role)
            for d in db.query(Dashboard).order_by(Dashboard.created_at).all()
        ],
    }


@router.put("/canvas/viewport")
def save_viewport(body: Viewport, db: Session = Depends(get_db)) -> dict:
    state = db.get(CanvasState, 1) or CanvasState(id=1)
    state.viewport = body.model_dump()
    db.add(state)
    db.commit()
    return state.viewport


@router.post("/dashboards")
def create_dashboard(body: DashboardCreate, db: Session = Depends(get_db), role: str = Depends(get_role)) -> dict:
    _ds(db, body.data_source_id)
    d = Dashboard(name=body.name, data_source_id=body.data_source_id, x=body.x, y=body.y)
    db.add(d)
    db.flush()
    rec = ChangeRecorder(db)
    rec.touch(None, d.id)
    rec.commit(f"Created dashboard '{body.name}'", source="manual")
    db.commit()
    return serialize(db, d, role)


@router.patch("/dashboards/{dashboard_id}")
def patch_dashboard(dashboard_id: str, body: DashboardPatch, db: Session = Depends(get_db), role: str = Depends(get_role)) -> dict:
    """Direct edits: geometry (not versioned) and name/filters (versioned)."""
    d = _dashboard(db, dashboard_id)
    rec = ChangeRecorder(db)
    if body.name is not None or body.filters is not None or body.description is not None:
        rec.touch(d)
    if body.filters is not None:
        ds = _ds(db, d.data_source_id)
        cat = Catalog(MetadataDoc.model_validate(ds.metadata_doc or {}), role)
        try:
            for f in body.filters:
                cat.column(f.field)
        except CompileError as exc:
            raise HTTPException(422, str(exc)) from exc
        d.filters = [f.model_dump(exclude_none=True) for f in body.filters]
    for k in ("name", "description", "x", "y", "width", "height"):
        v = getattr(body, k)
        if v is not None:
            setattr(d, k, v)
    rec.commit("Edited dashboard", source="manual")
    db.commit()
    return serialize(db, d, role)


@router.delete("/dashboards/{dashboard_id}")
def delete_dashboard(dashboard_id: str, db: Session = Depends(get_db)) -> dict:
    d = _dashboard(db, dashboard_id)
    rec = ChangeRecorder(db)
    rec.touch(d)
    db.delete(d)
    cs = rec.commit(f"Deleted dashboard '{d.name}'", source="manual")
    db.commit()
    return {"deleted": dashboard_id, "change_set_id": cs.id if cs else None}


@router.patch("/widgets/{widget_id}")
def patch_widget(widget_id: str, body: WidgetPatch, db: Session = Depends(get_db), role: str = Depends(get_role)) -> dict:
    """Ordinary supported interactions (presentation tweaks, editing existing filter values)
    apply directly without a generation step."""
    w = _widget(db, widget_id)
    ds = _ds(db, w.dashboard.data_source_id)
    rec = ChangeRecorder(db)
    rec.touch(w.dashboard)
    query = dict(w.query)
    if body.filters is not None:
        query["filters"] = [f.model_dump(exclude_none=True) for f in body.filters]
    try:
        plan = QueryPlan.model_validate(query)
        s = get_settings()
        compile_plan(plan, Catalog(MetadataDoc.model_validate(ds.metadata_doc or {}), role),
                     dialect_of(ds.url), s.default_row_limit, s.max_row_limit)
        if body.presentation is not None:
            Presentation.model_validate({**w.presentation, **body.presentation.model_dump(exclude_unset=True)})
    except (CompileError, ValidationError) as exc:
        raise HTTPException(422, str(exc)) from exc
    w.query = plan.model_dump(exclude_none=True)
    if body.title is not None:
        w.title = body.title
    if body.type is not None:
        w.type = body.type
    if body.presentation is not None:
        w.presentation = {**w.presentation, **body.presentation.model_dump(exclude_unset=True)}
    rec.commit(f"Edited widget '{w.title}'", source="manual")
    db.commit()
    return widget_dict(w, ds, role, w.dashboard.filters)


@router.delete("/widgets/{widget_id}")
def delete_widget(widget_id: str, db: Session = Depends(get_db), role: str = Depends(get_role)) -> dict:
    w = _widget(db, widget_id)
    d = w.dashboard
    rec = ChangeRecorder(db)
    rec.touch(d)
    d.widgets.remove(w)
    cs = rec.commit(f"Removed widget '{w.title}'", source="manual")
    db.commit()
    return {"dashboard": serialize(db, d, role), "change_set_id": cs.id if cs else None}


@router.post("/widgets/{widget_id}/data")
def widget_data(widget_id: str, force: bool = False, db: Session = Depends(get_db), role: str = Depends(get_role)) -> dict:
    """Execute a saved widget definition. Results go to the UI only."""
    w = _widget(db, widget_id)
    ds = _ds(db, w.dashboard.data_source_id)
    doc = MetadataDoc.model_validate(ds.metadata_doc or {})
    try:
        plan, skipped = effective_plan(w.query, w.dashboard.filters or [], doc, role, dialect_of(ds.url))
        result = execute_plan(plan, doc, ds.url, ds.id, role, force=force)
    except (CompileError, ValidationError) as exc:
        raise HTTPException(422, {"kind": "invalid", "message": str(exc)}) from exc
    except ExecutionError as exc:
        raise HTTPException(504 if "time limit" in str(exc) else 502, {"kind": "execution", "message": str(exc)}) from exc
    return {**result, "widget_id": w.id, "skipped_filters": skipped}


# ---------------------------------------------------------------------------
# History & undo
# ---------------------------------------------------------------------------

_GEOMETRY = ("x", "y", "width", "height")


def _content(snap: dict | None) -> dict | None:
    return None if snap is None else {k: v for k, v in snap.items() if k not in _GEOMETRY}


@router.get("/history")
def history(limit: int = 30, db: Session = Depends(get_db)) -> list[dict]:
    items = db.query(ChangeSet).order_by(ChangeSet.created_at.desc()).limit(min(limit, 200)).all()
    return [
        {"id": c.id, "source": c.source, "summary": c.summary, "undone": c.undone,
         "created_at": c.created_at.isoformat(), "dashboards": list(c.before)}
        for c in items
    ]


@router.post("/history/{change_set_id}/undo")
def undo(change_set_id: str, db: Session = Depends(get_db), role: str = Depends(get_role)) -> dict:
    cs = db.get(ChangeSet, change_set_id)
    if cs is None:
        raise HTTPException(404, "change set not found")
    if cs.undone:
        raise HTTPException(409, "this change was already undone")
    for did, after in cs.after.items():
        current = db.get(Dashboard, did)
        if _content(snapshot(current) if current else None) != _content(after):
            raise HTTPException(409, "a later change modified the same dashboard; undo that change first")
    for did, before in cs.before.items():
        restore(db, did, before)
    cs.undone = True
    db.commit()
    return get_canvas(db, role)

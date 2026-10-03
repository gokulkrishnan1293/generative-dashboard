from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import ValidationError
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_role, require_admin, require_reviewer
from ..models import Dashboard, DataSource
from ..schemas import DataSourceCreate, DataSourceUpdate, MetadataDoc
from ..services.dashboards import dependency_issues
from ..services.demo_metadata import apply_demo_metadata
from ..services.executor import clear_cache
from ..services.introspect import discover_schema, merge_discovery
from ..services.llm import LLMError, get_llm
from ..services.metadata_agent import draft_with_llm, heuristic_draft
from ..services.sources import dispose_engine, get_engine, redact_url

router = APIRouter(prefix="/api/datasources", tags=["data sources"])


def _summary(ds: DataSource) -> dict:
    doc = MetadataDoc.model_validate(ds.metadata_doc or {})
    counts: dict[str, int] = {}
    for t in doc.tables:
        for item in [t, *t.columns]:
            counts[item.status] = counts.get(item.status, 0) + 1
    for item in [*doc.relationships, *doc.metrics]:
        counts[item.status] = counts.get(item.status, 0) + 1
    return {
        "id": ds.id, "name": ds.name, "url": redact_url(ds.url), "is_demo": ds.is_demo,
        "documentation": ds.documentation,
        "discovered_at": ds.discovered_at.isoformat() if ds.discovered_at else None,
        "drafted_at": ds.drafted_at.isoformat() if ds.drafted_at else None,
        "table_count": len(doc.tables), "status_counts": counts,
    }


def _get(db: Session, ds_id: str) -> DataSource:
    ds = db.get(DataSource, ds_id)
    if ds is None:
        raise HTTPException(404, "data source not found")
    return ds


def run_discovery(db: Session, ds: DataSource) -> list[str]:
    try:
        discovered = discover_schema(ds.url)
    except Exception as exc:
        raise HTTPException(400, f"could not read schema: {type(exc).__name__}: {str(exc)[:300]}") from exc
    doc, changes = merge_discovery(MetadataDoc.model_validate(ds.metadata_doc or {}), discovered)
    ds.metadata_doc = doc.model_dump()
    ds.discovered_at = datetime.now(timezone.utc)
    db.commit()
    clear_cache()
    return changes


@router.get("")
def list_sources(db: Session = Depends(get_db)) -> list[dict]:
    return [_summary(ds) for ds in db.query(DataSource).order_by(DataSource.created_at).all()]


@router.post("")
def create_source(body: DataSourceCreate, db: Session = Depends(get_db), role: str = Depends(get_role)) -> dict:
    require_admin(role)
    try:
        with get_engine(body.url).connect():
            pass
    except Exception as exc:
        dispose_engine(body.url)
        raise HTTPException(400, f"could not connect: {type(exc).__name__}: {str(exc)[:300]}") from exc
    ds = DataSource(name=body.name, url=body.url, documentation=body.documentation)
    db.add(ds)
    db.commit()
    changes = run_discovery(db, ds)
    return {**_summary(ds), "changes": changes}


@router.get("/{ds_id}")
def get_source(ds_id: str, db: Session = Depends(get_db)) -> dict:
    return _summary(_get(db, ds_id))


@router.patch("/{ds_id}")
def update_source(ds_id: str, body: DataSourceUpdate, db: Session = Depends(get_db), role: str = Depends(get_role)) -> dict:
    require_reviewer(role)
    ds = _get(db, ds_id)
    if body.name is not None:
        ds.name = body.name
    if body.documentation is not None:
        ds.documentation = body.documentation
    db.commit()
    return _summary(ds)


@router.delete("/{ds_id}")
def delete_source(ds_id: str, db: Session = Depends(get_db), role: str = Depends(get_role)) -> dict:
    require_admin(role)
    ds = _get(db, ds_id)
    dispose_engine(ds.url)
    db.delete(ds)
    db.commit()
    return {"deleted": ds_id}


@router.post("/{ds_id}/discover")
def discover(ds_id: str, db: Session = Depends(get_db), role: str = Depends(get_role)) -> dict:
    """Re-read the schema; structural changes send affected items back to review."""
    require_reviewer(role)
    ds = _get(db, ds_id)
    changes = run_discovery(db, ds)
    return {"changes": changes, "metadata": ds.metadata_doc, "impact": _impact(db, ds)}


@router.post("/{ds_id}/draft")
def draft(ds_id: str, overwrite: bool = False, db: Session = Depends(get_db), role: str = Depends(get_role)) -> dict:
    """Let the agent draft descriptions for everything not yet approved."""
    require_reviewer(role)
    ds = _get(db, ds_id)
    doc = MetadataDoc.model_validate(ds.metadata_doc or {})
    try:
        llm = get_llm()
    except LLMError:
        notes = heuristic_draft(doc)
    else:
        try:
            notes = draft_with_llm(db, llm, doc, ds.documentation, overwrite)
        except LLMError as exc:
            raise HTTPException(502, f"metadata drafting failed: {exc}") from exc
        except Exception as exc:
            raise HTTPException(502, f"model gateway error: {type(exc).__name__}: {str(exc)[:300]}") from exc
    ds.metadata_doc = doc.model_dump()
    ds.drafted_at = datetime.now(timezone.utc)
    db.commit()
    return {"notes": notes, "metadata": ds.metadata_doc}


@router.get("/{ds_id}/metadata")
def get_metadata(ds_id: str, db: Session = Depends(get_db)) -> dict:
    ds = _get(db, ds_id)
    return MetadataDoc.model_validate(ds.metadata_doc or {}).model_dump()


@router.put("/{ds_id}/metadata")
def put_metadata(ds_id: str, body: dict, db: Session = Depends(get_db), role: str = Depends(get_role)) -> dict:
    require_reviewer(role)
    ds = _get(db, ds_id)
    try:
        doc = MetadataDoc.model_validate(body)
    except ValidationError as exc:
        raise HTTPException(422, exc.errors()) from exc
    old = MetadataDoc.model_validate(ds.metadata_doc or {})
    if role != "admin":
        # Only administrators may change access restrictions.
        for t in doc.tables:
            ot = old.table(t.name)
            t.restricted = ot.restricted if ot else t.restricted
            for c in t.columns:
                oc = ot.column(c.name) if ot else None
                c.restricted = oc.restricted if oc else c.restricted
    for item in [*doc.tables, *[c for t in doc.tables for c in t.columns]]:
        if item.status == "approved":
            item.schema_change = None
    ds.metadata_doc = doc.model_dump()
    db.commit()
    clear_cache()
    return {"metadata": ds.metadata_doc, "impact": _impact(db, ds)}


@router.post("/{ds_id}/metadata/load-demo")
def load_demo_metadata(ds_id: str, db: Session = Depends(get_db), role: str = Depends(get_role)) -> dict:
    """Shortcut for testing: apply the reviewed wrapper shipped for the demo database."""
    require_reviewer(role)
    ds = _get(db, ds_id)
    if not ds.is_demo:
        raise HTTPException(400, "reviewed metadata is only bundled for the demo data source")
    doc = apply_demo_metadata(MetadataDoc.model_validate(ds.metadata_doc or {}))
    ds.metadata_doc = doc.model_dump()
    db.commit()
    clear_cache()
    return {"metadata": ds.metadata_doc}


def _impact(db: Session, ds: DataSource) -> list[dict]:
    doc = MetadataDoc.model_validate(ds.metadata_doc or {})
    out = []
    for d in db.query(Dashboard).filter(Dashboard.data_source_id == ds.id).all():
        for w in d.widgets:
            issues = dependency_issues(w.query, doc)
            if issues:
                out.append({"dashboard_id": d.id, "dashboard": d.name, "widget_id": w.id, "widget": w.title,
                            "issues": issues})
    return out


@router.get("/{ds_id}/impact")
def impact(ds_id: str, db: Session = Depends(get_db)) -> list[dict]:
    """Saved widgets whose dependencies are no longer approved or no longer exist."""
    return _impact(db, _get(db, ds_id))

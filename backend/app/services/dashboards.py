"""Dashboard/widget state: serialization, placement, change sets and undo."""

from __future__ import annotations

from sqlalchemy.orm import Session

from ..models import ChangeSet, Dashboard, DataSource, Widget, new_id
from ..schemas import MetadataDoc, QueryPlan, RelativePlacement, WidgetSpec
from .compiler import plan_dependencies, plan_hash
from .executor import dialect_of, effective_plan

GAP = 80
DEFAULT_W, DEFAULT_H = 1040, 680
GRID_ROW_PX = 70


def widget_dict(w: Widget, ds: DataSource | None, role: str, dashboard_filters: list | None = None) -> dict:
    data = {
        "id": w.id, "dashboard_id": w.dashboard_id, "type": w.type, "title": w.title, "position": w.position,
        "query": w.query, "presentation": w.presentation,
        "updated_at": w.updated_at.isoformat() if w.updated_at else None,
    }
    if ds is not None:
        doc = MetadataDoc.model_validate(ds.metadata_doc or {})
        try:
            plan, skipped = effective_plan(w.query, dashboard_filters or [], doc, role, dialect_of(ds.url))
            data["effective_query_hash"] = plan_hash(plan, ds.id)
            data["skipped_filters"] = skipped
        except Exception:
            data["effective_query_hash"] = None
            data["skipped_filters"] = []
        data["dependency_issues"] = dependency_issues(w.query, doc)
    return data


def dependency_issues(query: dict, doc: MetadataDoc) -> list[str]:
    try:
        deps = plan_dependencies(QueryPlan.model_validate(query), doc)
    except Exception:
        return ["definition is no longer valid"]
    issues = []
    metrics = {m.name: m for m in doc.metrics}
    for dep in deps:
        if dep.startswith("metric:"):
            m = metrics.get(dep[7:])
            if m is None or m.status != "approved":
                issues.append(f"metric {dep[7:]} is {m.status if m else 'missing'}")
            continue
        t, _, c = dep.partition(".")
        table = doc.table(t)
        col = table.column(c) if table else None
        if table is None or col is None:
            issues.append(f"{dep} no longer exists")
        elif table.status != "approved":
            issues.append(f"table {t} is {table.status}")
        elif col.status != "approved":
            issues.append(f"{dep} is {col.status}" + (f" ({col.schema_change})" if col.schema_change else ""))
    return issues


def dashboard_dict(d: Dashboard, ds: DataSource | None, role: str) -> dict:
    return {
        "id": d.id, "name": d.name, "description": d.description, "data_source_id": d.data_source_id,
        "x": d.x, "y": d.y, "width": d.width, "height": d.height, "filters": d.filters or [],
        "updated_at": d.updated_at.isoformat() if d.updated_at else None,
        "widgets": [widget_dict(w, ds, role, d.filters) for w in d.widgets],
    }


def snapshot(d: Dashboard) -> dict:
    return {
        "id": d.id, "name": d.name, "description": d.description, "data_source_id": d.data_source_id,
        "x": d.x, "y": d.y, "width": d.width, "height": d.height, "filters": d.filters or [],
        "widgets": [
            {"id": w.id, "type": w.type, "title": w.title, "position": w.position,
             "query": w.query, "presentation": w.presentation}
            for w in d.widgets
        ],
    }


def restore(db: Session, dashboard_id: str, snap: dict | None) -> None:
    existing = db.get(Dashboard, dashboard_id)
    if snap is None:
        if existing is not None:
            db.delete(existing)
        return
    if existing is None:
        existing = Dashboard(id=dashboard_id, data_source_id=snap["data_source_id"], name=snap["name"])
        db.add(existing)
    for k in ("name", "description", "x", "y", "width", "height", "filters"):
        setattr(existing, k, snap[k])
    existing.widgets.clear()
    db.flush()
    for ws in snap["widgets"]:
        existing.widgets.append(Widget(
            id=ws["id"], type=ws["type"], title=ws["title"], position=ws["position"],
            query=ws["query"], presentation=ws["presentation"],
        ))


def auto_height(widgets: list[WidgetSpec]) -> float:
    """Estimate dashboard height from the 12-column grid packing of its widgets."""
    rows, row_w, row_h = 0, 0, 0
    for w in widgets:
        if row_w + w.presentation.w > 12:
            rows += row_h
            row_w, row_h = 0, 0
        row_w += w.presentation.w
        row_h = max(row_h, w.presentation.h)
    rows += row_h
    return max(360, min(1800, rows * GRID_ROW_PX + 120))


def free_position(db: Session) -> tuple[float, float]:
    dashboards = db.query(Dashboard).all()
    if not dashboards:
        return 0, 0
    right = max(d.x + d.width for d in dashboards)
    top = min(d.y for d in dashboards)
    return right + GAP, top


def relative_position(db: Session, placement: RelativePlacement, w: float, h: float) -> tuple[float, float]:
    target = db.get(Dashboard, placement.dashboard_id)
    if target is None:
        raise ValueError(f"unknown dashboard '{placement.dashboard_id}'")
    if placement.side == "right":
        return target.x + target.width + GAP, target.y
    if placement.side == "left":
        return target.x - w - GAP, target.y
    if placement.side == "below":
        return target.x, target.y + target.height + GAP
    return target.x, target.y - h - GAP


def new_widget(spec: WidgetSpec, position: int) -> Widget:
    return Widget(
        id=new_id(), type=spec.type, title=spec.title, position=position,
        query=spec.query.model_dump(exclude_none=True),
        presentation=spec.presentation.model_dump(exclude_none=True),
    )


class ChangeRecorder:
    """Captures 'before' snapshots of every dashboard touched in one change set."""

    def __init__(self, db: Session):
        self.db = db
        self.before: dict[str, dict | None] = {}

    def touch(self, dashboard: Dashboard | None, dashboard_id: str | None = None) -> None:
        key = dashboard.id if dashboard is not None else dashboard_id
        if key and key not in self.before:
            self.before[key] = snapshot(dashboard) if dashboard is not None else None

    def commit(self, summary: str, source: str = "agent") -> ChangeSet | None:
        if not self.before:
            return None
        self.db.flush()
        after = {}
        for did in self.before:
            d = self.db.get(Dashboard, did)
            if d is not None:
                self.db.refresh(d)
            after[did] = snapshot(d) if d is not None else None
        cs = ChangeSet(id=new_id(), source=source, summary=summary[:2000], before=self.before, after=after)
        self.db.add(cs)
        return cs

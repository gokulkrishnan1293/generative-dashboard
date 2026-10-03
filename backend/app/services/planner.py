"""The dashboard agent: turns a request plus metadata/configuration context into data requests
and UI descriptions (FR-04, FR-08), validates them (FR-05) and applies them as one change set.

Data boundary: the context contains approved metadata and dashboard *definitions* only.
Filter values from existing definitions are replaced with opaque placeholders before they
are sent and restored afterwards, so values a user typed into the UI are not forwarded.
No query results, cached rows or execution errors are ever included.
"""

from __future__ import annotations

import json
import re
from typing import Any

from pydantic import ValidationError
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import ChatMessage, Dashboard, DataSource, Widget
from ..schemas import (
    AddWidgetOp, AgentPlan, ChatRequest, CreateDashboardOp, MetadataDoc, MoveDashboardOp, Presentation, QueryPlan,
    RemoveDashboardOp, RemoveWidgetOp, UpdateDashboardOp, UpdateWidgetOp, WidgetSpec,
)
from .compiler import Catalog, CompileError, compile_plan
from .dashboards import (
    DEFAULT_H, DEFAULT_W, ChangeRecorder, auto_height, free_position, new_widget, relative_position,
)
from .executor import dialect_of
from .llm import JSONCompleter, LLMError, audited_call

SYSTEM = """You are the dashboard agent of a generative BI workspace: an infinite canvas holding
many dashboards, each with widgets. You turn the user's request into OPERATIONS that create or
change dashboard definitions. The application executes the data requests and renders results;
you never see data, and must not claim anything about actual values, row counts or timing.

## Metadata
Use ONLY the approved tables, columns, relationships and metrics in the context. Fields are
written "table.column". If the request depends on a business meaning that is not covered
(listed under "unreviewed" or absent), or on a choice between plausible definitions that
changes the result, do NOT guess: return a clarification (and no operations).

## Data request (query)
{"dimensions": [{"field": "t.c", "alias": "name", "grain": "day|week|month|quarter|year" (time fields only)}],
 "measures": [{"alias": "name", "metric": "approved_metric_name"}
              | {"alias": "name", "agg": "sum|avg|min|max|count|count_distinct", "field": "t.c"}
              | {"alias": "name", "agg": "count"}  (row count of the most granular table)],
 "filters": [{"field": "t.c", "op": "eq|neq|gt|gte|lt|lte|in|not_in|between|contains|is_null|not_null|in_last_days", "value": ...}],
 "order_by": [{"key": "alias", "direction": "asc|desc"}],
 "limit": 10,
 "via": ["relationship id"]}
- Joins are derived automatically from approved relationships; never write SQL or join conditions.
  If two relationship paths are possible (e.g. customer region vs. sales-rep region), set "via"
  to the intended relationship id, or ask a clarification if the user's intent is unclear.
- Prefer approved metrics over ad-hoc aggregations; respect metric descriptions (e.g. required
  exclusions). Use coded values exactly as listed.
- A measure must not be summed across a one-to-many join (the service rejects it).
- Aliases: lowercase snake_case, unique per query. No measures = a row-level listing (set a limit).
- "in" / "not_in" take a list; "between" takes [low, high]; "in_last_days" takes a number of days.
- Filter values shown as «vN» are redacted placeholders for values already configured by the
  user; copy them verbatim to keep a filter, never invent replacements for them.

## Widgets (component catalog)
{"type": "kpi|table|bar|line|area|pie", "title": "...", "query": {...},
 "presentation": {"x": "dimension alias", "y": ["measure aliases"], "series": "optional dimension alias",
                  "stacked": false, "horizontal": false, "columns": ["table column order"],
                  "formats": {"alias": "number|integer|currency|percent|text|date"},
                  "labels": {"alias": "Display label"}, "w": 1-12 grid columns, "h": 2-12 grid rows}}
- kpi: measures only, no dimensions (one row). w 3, h 2.
- line/area: time dimension on x. bar: category on x. pie: one dimension + one measure, <= 8 slices.
- table: any; set "columns". Typical sizes: charts w 6 h 5, tables w 12 h 6.

## Operations
{"op": "create_dashboard", "ref": "new1", "name": "...", "description": "...", "filters": [],
   "widgets": [widget, ...], "relative_to": {"dashboard_id": "id", "side": "right|left|above|below"}}
{"op": "update_dashboard", "dashboard_id": "id", "name"?, "description"?, "filters"?: [filter]}
{"op": "move_dashboard", "dashboard_id": "id", "relative_to": {...} | "position": {"x", "y"}, "width"?, "height"?}
{"op": "remove_dashboard", "dashboard_id": "id"}
{"op": "add_widget", "dashboard_id": "id or ref", "widget": widget}
{"op": "update_widget", "widget_id": "id", "changes": {"type"?, "title"?, "query"?, "presentation"?}}
{"op": "remove_widget", "widget_id": "id"}

Rules for changes:
- Requests referring to "this"/"it" apply to the SELECTED dashboards/widgets. If nothing is
  selected and the target is not clear from the request, ask a clarification.
- Change only what was asked. Keep ids, unrelated widgets and dashboards untouched.
- update_widget "query" replaces the whole query: send the complete new query.
- For a pure presentation change (e.g. "make it a bar chart"), do NOT send "query" at all, so
  existing results are reused. Only send "query" when the data needed actually changes.
- Moving or resizing dashboards never changes queries.
- Dashboard "filters" apply to every widget they are compatible with.

## Output
Return ONE JSON object: {"message": "short summary for the user of what you did",
"clarification": null | {"question": "...", "options": ["...", "..."]}, "operations": [...]}
"""


class AgentError(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# Context building (metadata + configuration only)
# ---------------------------------------------------------------------------


def metadata_context(doc: MetadataDoc, role: str) -> dict:
    cat = Catalog(doc, role)
    tables = []
    for t in cat.tables.values():
        cols = []
        for c in t.columns:
            ref = f"{t.name}.{c.name}"
            if ref not in cat.columns:
                continue
            entry: dict[str, Any] = {"name": c.name, "type": c.data_type}
            if c.description:
                entry["description"] = c.description
            if c.semantic_type:
                entry["semantic"] = c.semantic_type
            if c.unit:
                entry["unit"] = c.unit
            if c.coded_values:
                entry["values"] = c.coded_values
            elif c.allowed_values:
                entry["values"] = c.allowed_values
            cols.append(entry)
        tables.append({"name": t.name, "description": t.description, "row": t.row_meaning, "columns": cols})
    rels = [
        {"id": r.id, "cardinality": r.cardinality, "description": r.description}
        for r in cat.relationships
    ]
    metrics = [
        {"name": m.name, "label": m.label, "description": m.description, "format": m.format}
        for m in cat.metrics.values()
    ]
    unreviewed = []
    for t in doc.tables:
        if t.status in ("approved", "missing", "rejected"):
            for c in t.columns if t.status == "approved" else []:
                if c.status in ("draft", "needs_review"):
                    unreviewed.append({"field": f"{t.name}.{c.name}", "open_questions": c.ambiguities})
            continue
        if t.restricted and role != "admin":
            continue
        unreviewed.append({"table": t.name, "open_questions": t.ambiguities})
    for m in doc.metrics:
        if m.status in ("draft", "needs_review"):
            unreviewed.append({"metric": m.name, "open_questions": m.ambiguities})
    return {"tables": tables, "relationships": rels, "metrics": metrics, "unreviewed": unreviewed[:40]}


class Redactor:
    def __init__(self) -> None:
        self.values: dict[str, Any] = {}

    def _token(self, v: Any) -> str:
        token = f"«v{len(self.values) + 1}»"
        self.values[token] = v
        return token

    def filters(self, filters: list[dict]) -> list[dict]:
        out = []
        for f in filters or []:
            f = dict(f)
            if f.get("op") in ("is_null", "not_null", "in_last_days"):
                out.append(f)
                continue
            v = f.get("value")
            f["value"] = [self._token(x) for x in v] if isinstance(v, list) else self._token(v)
            out.append(f)
        return out

    def restore(self, obj: Any) -> Any:
        if isinstance(obj, str):
            if obj in self.values:
                return self.values[obj]
            return re.sub(r"«v\d+»", lambda m: str(self.values.get(m.group(0), m.group(0))), obj)
        if isinstance(obj, list):
            return [self.restore(x) for x in obj]
        if isinstance(obj, dict):
            return {k: self.restore(v) for k, v in obj.items()}
        return obj


def canvas_context(db: Session, req: ChatRequest, redactor: Redactor) -> dict:
    selected_d = set(req.selection.dashboard_ids)
    selected_w = set(req.selection.widget_ids)
    for wid in selected_w:
        w = db.get(Widget, wid)
        if w is not None:
            selected_d.add(w.dashboard_id)
    dashboards = []
    for d in db.query(Dashboard).order_by(Dashboard.created_at).all():
        entry: dict[str, Any] = {
            "id": d.id, "name": d.name, "x": round(d.x), "y": round(d.y), "width": round(d.width),
            "height": round(d.height), "selected": d.id in req.selection.dashboard_ids,
        }
        if d.id in selected_d:
            entry["description"] = d.description
            entry["filters"] = redactor.filters(d.filters)
            entry["widgets"] = [
                {
                    "id": w.id, "type": w.type, "title": w.title, "selected": w.id in selected_w,
                    "query": {**w.query, "filters": redactor.filters(w.query.get("filters", []))},
                    "presentation": w.presentation,
                }
                for w in d.widgets
            ]
        else:
            entry["widgets"] = [{"id": w.id, "type": w.type, "title": w.title} for w in d.widgets]
        dashboards.append(entry)
    return {"dashboards": dashboards, "selection": req.selection.model_dump()}


def history_context(db: Session, limit: int = 8) -> list[dict]:
    msgs = db.query(ChatMessage).order_by(ChatMessage.created_at.desc()).limit(limit).all()
    return [{"role": m.role, "content": m.content[:1500]} for m in reversed(msgs)]


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def _validate_plan(plan: AgentPlan, db: Session, catalog: Catalog, dialect: str) -> list[str]:
    s = get_settings()
    errors: list[str] = []
    refs: set[str] = set()

    def check_query(where: str, q: QueryPlan, spec_type: str | None = None, pres=None) -> None:
        try:
            compile_plan(q, catalog, dialect, s.default_row_limit, s.max_row_limit)
        except CompileError as exc:
            errors.append(f"{where}: {exc}")
            return
        if pres is not None:
            keys = set(q.output_keys())
            for k in [pres.x, pres.series, *pres.y, *pres.columns]:
                if k and k not in keys:
                    errors.append(f"{where}: presentation refers to '{k}' which is not an output of the query {sorted(keys)}")
        if spec_type == "kpi" and q.dimensions:
            errors.append(f"{where}: kpi widgets must not have dimensions")

    for i, op in enumerate(plan.operations):
        where = f"operation {i + 1} ({op.op})"
        if isinstance(op, CreateDashboardOp):
            if op.ref:
                refs.add(op.ref)
            for j, w in enumerate(op.widgets):
                check_query(f"{where} widget {j + 1} '{w.title}'", w.query, w.type, w.presentation)
            for f in op.filters:
                try:
                    catalog.column(f.field)
                except CompileError as exc:
                    errors.append(f"{where} filter: {exc}")
        elif isinstance(op, AddWidgetOp):
            if op.dashboard_id not in refs and db.get(Dashboard, op.dashboard_id) is None:
                errors.append(f"{where}: unknown dashboard '{op.dashboard_id}'")
            check_query(f"{where} '{op.widget.title}'", op.widget.query, op.widget.type, op.widget.presentation)
        elif isinstance(op, UpdateWidgetOp):
            w = db.get(Widget, op.widget_id)
            if w is None:
                errors.append(f"{where}: unknown widget '{op.widget_id}'")
                continue
            q = op.changes.query or QueryPlan.model_validate(w.query)
            pres_changes = op.changes.presentation.model_dump(exclude_unset=True) if op.changes.presentation else {}
            pres = Presentation.model_validate({**w.presentation, **pres_changes})
            check_query(where, q, op.changes.type or w.type, pres)
        elif isinstance(op, (UpdateDashboardOp, MoveDashboardOp, RemoveDashboardOp)):
            if db.get(Dashboard, op.dashboard_id) is None and op.dashboard_id not in refs:
                errors.append(f"{where}: unknown dashboard '{op.dashboard_id}'")
            if isinstance(op, UpdateDashboardOp):
                for f in op.filters or []:
                    try:
                        catalog.column(f.field)
                    except CompileError as exc:
                        errors.append(f"{where} filter: {exc}")
        elif isinstance(op, RemoveWidgetOp):
            if db.get(Widget, op.widget_id) is None:
                errors.append(f"{where}: unknown widget '{op.widget_id}'")
    return errors


# ---------------------------------------------------------------------------
# Applying operations
# ---------------------------------------------------------------------------


def apply_plan(db: Session, plan: AgentPlan, ds: DataSource, recorder: ChangeRecorder) -> list[str]:
    refs: dict[str, str] = {}
    touched: list[str] = []

    def resolve(did: str) -> Dashboard:
        d = db.get(Dashboard, refs.get(did, did))
        if d is None:
            raise AgentError(f"unknown dashboard '{did}'")
        return d

    for op in plan.operations:
        if isinstance(op, CreateDashboardOp):
            height = op.height or auto_height(op.widgets)
            width = op.width or DEFAULT_W
            if op.position:
                x, y = op.position.x, op.position.y
            elif op.relative_to and op.relative_to.dashboard_id in refs:
                x, y = relative_position(db, op.relative_to.model_copy(
                    update={"dashboard_id": refs[op.relative_to.dashboard_id]}), width, height)
            elif op.relative_to and db.get(Dashboard, op.relative_to.dashboard_id):
                x, y = relative_position(db, op.relative_to, width, height)
            else:
                x, y = free_position(db)
            d = Dashboard(
                data_source_id=ds.id, name=op.name, description=op.description, x=x, y=y,
                width=width, height=height or DEFAULT_H,
                filters=[f.model_dump(exclude_none=True) for f in op.filters],
            )
            db.add(d)
            db.flush()
            recorder.touch(None, d.id)
            for i, spec in enumerate(op.widgets):
                d.widgets.append(new_widget(spec, i))
            if op.ref:
                refs[op.ref] = d.id
            touched.append(d.id)
        elif isinstance(op, AddWidgetOp):
            d = resolve(op.dashboard_id)
            recorder.touch(d)
            d.widgets.append(new_widget(op.widget, max([w.position for w in d.widgets], default=-1) + 1))
            touched.append(d.id)
        elif isinstance(op, UpdateWidgetOp):
            w = db.get(Widget, op.widget_id)
            if w is None:
                raise AgentError(f"unknown widget '{op.widget_id}'")
            recorder.touch(w.dashboard)
            ch = op.changes
            if ch.type:
                w.type = ch.type
            if ch.title:
                w.title = ch.title
            if ch.query is not None:
                w.query = ch.query.model_dump(exclude_none=True)
            if ch.presentation is not None:
                w.presentation = {**w.presentation, **ch.presentation.model_dump(exclude_unset=True)}
            touched.append(w.dashboard_id)
        elif isinstance(op, RemoveWidgetOp):
            w = db.get(Widget, op.widget_id)
            if w is None:
                continue
            recorder.touch(w.dashboard)
            w.dashboard.widgets.remove(w)
            touched.append(w.dashboard_id)
        elif isinstance(op, UpdateDashboardOp):
            d = resolve(op.dashboard_id)
            recorder.touch(d)
            if op.name:
                d.name = op.name
            if op.description is not None:
                d.description = op.description
            if op.filters is not None:
                d.filters = [f.model_dump(exclude_none=True) for f in op.filters]
            touched.append(d.id)
        elif isinstance(op, MoveDashboardOp):
            d = resolve(op.dashboard_id)
            recorder.touch(d)
            if op.width:
                d.width = op.width
            if op.height:
                d.height = op.height
            if op.position:
                d.x, d.y = op.position.x, op.position.y
            elif op.relative_to:
                placement = op.relative_to.model_copy(
                    update={"dashboard_id": refs.get(op.relative_to.dashboard_id, op.relative_to.dashboard_id)})
                d.x, d.y = relative_position(db, placement, d.width, d.height)
            touched.append(d.id)
        elif isinstance(op, RemoveDashboardOp):
            d = resolve(op.dashboard_id)
            recorder.touch(d)
            db.delete(d)
    db.flush()
    return list(dict.fromkeys(touched))


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def run_agent(db: Session, llm: JSONCompleter, req: ChatRequest, ds: DataSource, role: str) -> dict:
    doc = MetadataDoc.model_validate(ds.metadata_doc or {})
    catalog = Catalog(doc, role)
    if not catalog.tables:
        raise AgentError(
            "No approved metadata is available for this data source yet. "
            "Review and approve the metadata wrapper first (Metadata tab)."
        )
    dialect = dialect_of(ds.url)
    redactor = Redactor()
    context = {
        "data_source": ds.name,
        "metadata": metadata_context(doc, role),
        "canvas": canvas_context(db, req, redactor),
        "conversation": history_context(db),
        "request": req.prompt,
    }
    user = json.dumps(context, ensure_ascii=False)

    plan: AgentPlan | None = None
    feedback = ""
    for attempt in range(3):
        raw = audited_call(db, llm, "dashboard_agent", SYSTEM, user + feedback)
        try:
            plan = AgentPlan.model_validate(redactor.restore(raw))
        except ValidationError as exc:
            problems = "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors()[:12])
            feedback = f"\n\nYour previous answer was not valid against the contract: {problems}. Return a corrected JSON object."
            plan = None
            continue
        if plan.clarification:
            plan.operations = []
            break
        errors = _validate_plan(plan, db, catalog, dialect)
        if not errors:
            break
        feedback = (
            "\n\nYour previous answer was rejected by the validator:\n- " + "\n- ".join(errors[:15])
            + "\nFix these problems (or ask a clarification) and return the complete corrected JSON object."
        )
        plan = None
    if plan is None:
        raise AgentError("The agent could not produce a valid definition for this request. " + feedback.strip()[:800])

    recorder = ChangeRecorder(db)
    touched = apply_plan(db, plan, ds, recorder)
    change_set = recorder.commit(plan.message or req.prompt)
    return {"plan": plan, "touched": touched, "change_set": change_set, "removed": [
        did for did, snap in recorder.before.items() if snap is not None and db.get(Dashboard, did) is None
    ]}


__all__ = ["run_agent", "AgentError", "LLMError", "SYSTEM", "Redactor", "metadata_context", "WidgetSpec"]

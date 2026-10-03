"""Validates a structured data request against approved metadata and compiles it to SQL.

Only approved, role-visible tables/columns/relationships/metrics can be used. Joins are
derived from approved relationships (the request never states join conditions), and a
grain check rejects aggregates that a one-to-many join would silently inflate.
Error messages reference metadata only, never business values, so they are safe to
return to the agent for self-correction.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

import sqlalchemy as sa
from sqlalchemy.sql.elements import ColumnElement

from ..schemas import Dimension, Expr, Filter, Measure, MetadataDoc, MetricMeta, QueryPlan, RelationshipMeta, TableMeta

ROLES = ("admin", "analyst", "viewer")
SAFE_AGGS = {"min", "max", "count_distinct"}


class CompileError(ValueError):
    pass


class Catalog:
    """The approved slice of the metadata wrapper visible to a role."""

    def __init__(self, doc: MetadataDoc, role: str):
        self.role = role
        see_restricted = role == "admin"
        self.tables: dict[str, TableMeta] = {
            t.name: t for t in doc.tables
            if t.status == "approved" and (see_restricted or not t.restricted)
        }
        self.columns: dict[str, Any] = {}
        for t in self.tables.values():
            for c in t.columns:
                if c.status == "approved" and (see_restricted or not c.restricted):
                    self.columns[f"{t.name}.{c.name}"] = c
        self.relationships: list[RelationshipMeta] = [
            r for r in doc.relationships
            if r.status == "approved" and r.from_table in self.tables and r.to_table in self.tables
            and self.tables[r.from_table].column(r.from_column) and self.tables[r.to_table].column(r.to_column)
        ]
        self.metrics: dict[str, MetricMeta] = {}
        for m in doc.metrics:
            if m.status == "approved" and all(c in self.columns for c in m.expr.columns()):
                self.metrics[m.name] = m
        self._all_doc = doc

    def column(self, ref: str):
        col = self.columns.get(ref)
        if col is None:
            raise CompileError(self._why_unavailable(ref))
        return col

    def _why_unavailable(self, ref: str) -> str:
        if "." not in ref:
            return f"field '{ref}' must be written as table.column"
        table, column = ref.split(".", 1)
        t = self._all_doc.table(table)
        if t is None:
            return f"unknown table '{table}'"
        if t.status != "approved":
            return f"table '{table}' is not approved for use (status: {t.status})"
        if table not in self.tables:
            return f"table '{table}' is restricted for role '{self.role}'"
        c = t.column(column)
        if c is None:
            return f"unknown column '{ref}'"
        if c.status != "approved":
            return f"column '{ref}' is not approved for use (status: {c.status})"
        return f"column '{ref}' is restricted for role '{self.role}'"


@dataclass
class OutputColumn:
    key: str
    kind: str  # dimension | measure
    field: str | None = None
    metric: str | None = None
    grain: str | None = None
    format: str | None = None


@dataclass
class CompiledQuery:
    statement: sa.Select
    outputs: list[OutputColumn]
    limit: int
    tables: list[str]
    dependencies: list[str] = field(default_factory=list)


@dataclass
class _Edge:
    a: str
    b: str
    rel: RelationshipMeta

    def other(self, t: str) -> str:
        return self.b if t == self.a else self.a

    def fans_out_from(self, t: str) -> bool:
        """True if moving from t across this edge can multiply t's rows."""
        if self.rel.cardinality == "one_to_one":
            return False
        return t == self.rel.to_table  # going from the 'one' side to the 'many' side


def _split(ref: str) -> tuple[str, str]:
    if ref.count(".") != 1:
        raise CompileError(f"field '{ref}' must be written as table.column")
    t, c = ref.split(".")
    return t, c


def _join_tree(
    catalog: Catalog, needed: set[str], measure_tables: set[str], via: list[str]
) -> tuple[str, list[_Edge]]:
    if len(needed) == 1:
        return next(iter(needed)), []
    adjacency: dict[str, list[_Edge]] = {}
    for rel in catalog.relationships:
        e = _Edge(rel.from_table, rel.to_table, rel)
        adjacency.setdefault(rel.from_table, []).append(e)
        adjacency.setdefault(rel.to_table, []).append(e)
    unknown_via = [v for v in via if v not in {r.id for r in catalog.relationships}]
    if unknown_via:
        raise CompileError(f"'via' references unknown or unapproved relationships: {unknown_via}")
    preferred = set(via)

    options: list[tuple[tuple[int, int, int], str, list[_Edge], str | None]] = []
    for root in sorted(measure_tables or needed):
        # Layered BFS keeping every shortest-path parent, so ambiguous paths can be detected.
        dist = {root: 0}
        parents: dict[str, list[tuple[str, _Edge]]] = {root: []}
        frontier = [root]
        while frontier:
            nxt_frontier = []
            for cur in frontier:
                for e in adjacency.get(cur, []):
                    nxt = e.other(cur)
                    if nxt not in dist:
                        dist[nxt] = dist[cur] + 1
                        parents[nxt] = [(cur, e)]
                        nxt_frontier.append(nxt)
                    elif dist[nxt] == dist[cur] + 1:
                        parents[nxt].append((cur, e))
            frontier = nxt_frontier
        if not needed.issubset(dist):
            continue
        edges: dict[str, _Edge] = {}
        ambiguity: str | None = None
        for t in needed:
            node = t
            while parents[node]:
                choices = parents[node]
                if len(choices) > 1:
                    pinned = [c for c in choices if c[1].rel.id in preferred]
                    if len(pinned) == 1:
                        choices = pinned
                    elif ambiguity is None:
                        ids = ", ".join(sorted(c[1].rel.id for c in choices))
                        ambiguity = (
                            f"ambiguous join path to '{node}': it can be reached through {ids}; "
                            f"set 'via' to the intended relationship id (or ask the user which is meant)"
                        )
                prev, e = choices[0]
                edges[e.rel.id] = e
                node = prev
        tree = list(edges.values())
        fanouts = sum(1 for e in tree if _oriented_fanout(e, root, tree))
        options.append(((fanouts, 1 if ambiguity else 0, len(tree)), root, tree, ambiguity))
    if not options:
        raise CompileError(f"no approved relationship path connects tables: {', '.join(sorted(needed))}")
    _, root, tree, ambiguity = min(options, key=lambda o: o[0])
    if ambiguity:
        raise CompileError(ambiguity)
    return root, tree


def _orient(tree: list[_Edge], start: str) -> list[tuple[str, _Edge]]:
    """Edges in traversal order from start, each paired with the node it is entered from."""
    out: list[tuple[str, _Edge]] = []
    seen = {start}
    frontier = [start]
    while frontier:
        cur = frontier.pop()
        for e in tree:
            if cur in (e.a, e.b) and e.other(cur) not in seen:
                seen.add(e.other(cur))
                out.append((cur, e))
                frontier.append(e.other(cur))
    return out


def _oriented_fanout(edge: _Edge, start: str, tree: list[_Edge]) -> bool:
    for frm, e in _orient(tree, start):
        if e is edge:
            return e.fans_out_from(frm)
    return False


class _Builder:
    def __init__(self, catalog: Catalog, dialect: str):
        self.catalog = catalog
        self.dialect = dialect
        self.aliases: dict[str, Any] = {}

    def table(self, name: str):
        if name not in self.aliases:
            meta = self.catalog.tables[name]
            tc = sa.table(name, *[sa.column(c.name) for c in meta.columns])
            self.aliases[name] = tc.alias(f"t{len(self.aliases)}")
        return self.aliases[name]

    def col(self, ref: str) -> ColumnElement:
        self.catalog.column(ref)
        t, c = _split(ref)
        return self.table(t).c[c]

    def expr(self, e: Expr) -> ColumnElement:
        if e.column is not None:
            return self.col(e.column)
        if e.literal is not None:
            return sa.literal(e.literal)
        left, right = (self.expr(a) for a in e.args or [])
        if e.op == "add":
            return left + right
        if e.op == "sub":
            return left - right
        if e.op == "mul":
            return left * right
        return (left * 1.0) / sa.func.nullif(right, 0)

    def grain(self, c: ColumnElement, grain: str) -> ColumnElement:
        if self.dialect == "sqlite":
            fmt = {"day": "%Y-%m-%d", "week": "%Y-W%W", "month": "%Y-%m", "year": "%Y"}
            if grain == "quarter":
                q = sa.cast((sa.cast(sa.func.strftime("%m", c), sa.Integer) + 2) // 3, sa.String)
                return sa.func.strftime("%Y", c) + "-Q" + q
            return sa.func.strftime(fmt[grain], c)
        if self.dialect == "postgresql":
            fmt = {"day": "YYYY-MM-DD", "week": "IYYY-\"W\"IW", "month": "YYYY-MM", "quarter": "YYYY-\"Q\"Q", "year": "YYYY"}
            return sa.func.to_char(sa.func.date_trunc(grain, c), fmt[grain])
        raise CompileError(f"time grains are not supported for dialect '{self.dialect}'")

    def measure(self, m: Measure) -> tuple[ColumnElement, str]:
        if m.metric:
            metric = self.catalog.metrics.get(m.metric)
            if metric is None:
                raise CompileError(f"unknown or unapproved metric '{m.metric}'")
            agg, inner = metric.agg, self.expr(metric.expr)
        else:
            agg = m.agg or "count"
            if m.field is None and m.expr is None:
                return sa.func.count(), "count"
            inner = self.col(m.field) if m.field else self.expr(m.expr)  # type: ignore[arg-type]
        fn = {
            "sum": sa.func.sum, "avg": sa.func.avg, "min": sa.func.min, "max": sa.func.max,
            "count": sa.func.count,
        }
        if agg == "count_distinct":
            return sa.func.count(sa.distinct(inner)), agg
        return fn[agg](inner), agg

    def filter(self, f: Filter) -> ColumnElement:
        c = self.col(f.field)
        v = f.value
        _check_value(f)
        op = f.op
        if op == "eq":
            return c == v
        if op == "neq":
            return c != v
        if op == "gt":
            return c > v
        if op == "gte":
            return c >= v
        if op == "lt":
            return c < v
        if op == "lte":
            return c <= v
        if op == "in":
            return c.in_(list(v))
        if op == "not_in":
            return c.not_in(list(v))
        if op == "between":
            return c.between(v[0], v[1])
        if op == "contains":
            return c.ilike(f"%{v}%")
        if op == "is_null":
            return c.is_(None)
        if op == "not_null":
            return c.is_not(None)
        if op == "in_last_days":
            since = date.today() - timedelta(days=int(v))
            return c >= (since.isoformat() if self.dialect == "sqlite" else since)
        raise CompileError(f"unsupported filter operator '{op}'")


def _is_scalar(v: Any) -> bool:
    return v is None or isinstance(v, (str, int, float, bool))


def _check_value(f: Filter) -> None:
    v = f.value
    if f.op in ("is_null", "not_null"):
        return
    if f.op in ("in", "not_in"):
        if not isinstance(v, list) or not v or not all(_is_scalar(x) for x in v):
            raise CompileError(f"filter on '{f.field}' with '{f.op}' needs a non-empty list of values")
        return
    if f.op == "between":
        if not isinstance(v, list) or len(v) != 2 or not all(_is_scalar(x) for x in v):
            raise CompileError(f"filter on '{f.field}' with 'between' needs [low, high]")
        return
    if f.op == "in_last_days":
        if not isinstance(v, (int, float)) or v <= 0 or v > 3660:
            raise CompileError(f"filter on '{f.field}' with 'in_last_days' needs a positive number of days")
        return
    if v is None or not _is_scalar(v):
        raise CompileError(f"filter on '{f.field}' with '{f.op}' needs a single value")


def plan_tables(plan: QueryPlan, catalog: Catalog) -> tuple[set[str], set[str]]:
    needed: set[str] = set()
    measure_tables: set[str] = set()
    for d in plan.dimensions:
        needed.add(_split(d.field)[0])
    for f in plan.filters:
        needed.add(_split(f.field)[0])
    for m in plan.measures:
        refs: list[str] = []
        if m.metric:
            metric = catalog.metrics.get(m.metric)
            if metric is None:
                raise CompileError(f"unknown or unapproved metric '{m.metric}'")
            refs = metric.expr.columns()
        elif m.field:
            refs = [m.field]
        elif m.expr:
            refs = m.expr.columns()
        ts = {_split(r)[0] for r in refs}
        needed |= ts
        measure_tables |= ts
    return needed, measure_tables


def compile_plan(plan: QueryPlan, catalog: Catalog, dialect: str, default_limit: int, max_limit: int) -> CompiledQuery:
    refs = [d.field for d in plan.dimensions] + [f.field for f in plan.filters]
    for m in plan.measures:
        refs += [m.field] if m.field else (m.expr.columns() if m.expr else [])
    for ref in refs:
        catalog.column(ref)
    needed, measure_tables = plan_tables(plan, catalog)
    if not needed:
        raise CompileError("count without a field needs at least one dimension or filter to identify the table")
    root, tree = _join_tree(catalog, needed, measure_tables, plan.via)

    for m in plan.measures:
        metric = catalog.metrics.get(m.metric) if m.metric else None
        agg = metric.agg if metric else (m.agg or "count")
        if agg in SAFE_AGGS:
            continue
        refs = metric.expr.columns() if metric else ([m.field] if m.field else (m.expr.columns() if m.expr else []))
        tables = {_split(r)[0] for r in refs} or {root}
        # The measure is evaluated per joined row; it is correct when, seen from one of its own
        # tables (its grain), no join in the query can multiply that table's rows.
        if any(not any(e.fans_out_from(frm) for frm, e in _orient(tree, t)) for t in tables):
            continue
        t = sorted(tables)[0]
        bad = next(e for frm, e in _orient(tree, t) if e.fans_out_from(frm))
        raise CompileError(
            f"measure '{m.alias}' ({agg} over {', '.join(sorted(tables))}) would be inflated by the one-to-many "
            f"join {bad.rel.id}; aggregate at the {bad.rel.from_table} grain, use count_distinct/min/max, "
            f"or remove fields from {bad.rel.from_table}"
        )

    b = _Builder(catalog, dialect)
    from_clause = b.table(root)
    for frm, e in _orient(tree, root):
        to = e.other(frm)
        rel = e.rel
        on = b.table(rel.from_table).c[rel.from_column] == b.table(rel.to_table).c[rel.to_column]
        from_clause = from_clause.outerjoin(b.table(to), on)

    outputs: list[OutputColumn] = []
    selected: list[ColumnElement] = []
    group_by: list[ColumnElement] = []
    labelled: dict[str, ColumnElement] = {}
    for d in plan.dimensions:
        c = b.col(d.field)
        if d.grain:
            c = b.grain(c, d.grain)
        label = c.label(d.key)
        selected.append(label)
        group_by.append(c)
        labelled[d.key] = label
        outputs.append(OutputColumn(key=d.key, kind="dimension", field=d.field, grain=d.grain))
    for m in plan.measures:
        expr, _ = b.measure(m)
        label = expr.label(m.alias)
        selected.append(label)
        labelled[m.alias] = label
        fmt = catalog.metrics[m.metric].format if m.metric else None
        outputs.append(OutputColumn(key=m.alias, kind="measure", field=m.field, metric=m.metric, format=fmt))

    stmt = sa.select(*selected).select_from(from_clause)
    for f in plan.filters:
        stmt = stmt.where(b.filter(f))
    if plan.measures and plan.dimensions:
        stmt = stmt.group_by(*group_by)

    order = plan.order_by
    if not order:
        grain_dim = next((d for d in plan.dimensions if d.grain), None)
        if grain_dim:
            stmt = stmt.order_by(sa.asc(sa.literal_column(_quote(grain_dim.key, dialect))))
        elif plan.measures and plan.dimensions:
            stmt = stmt.order_by(sa.desc(sa.literal_column(_quote(plan.measures[0].alias, dialect))))
    for o in order:
        if o.key not in labelled:
            raise CompileError(f"order_by key '{o.key}' is not one of the outputs {list(labelled)}")
        col = sa.literal_column(_quote(o.key, dialect))
        stmt = stmt.order_by(sa.desc(col) if o.direction == "desc" else sa.asc(col))

    limit = max(1, min(plan.limit or default_limit, max_limit))
    stmt = stmt.limit(limit + 1)  # one extra row detects truncation

    deps = plan_dependencies(plan, catalog._all_doc)
    return CompiledQuery(stmt, outputs, limit, sorted({root, *[e.a for e in tree], *[e.b for e in tree]}), deps)


def _quote(name: str, dialect: str) -> str:
    if not name.replace("_", "").isalnum():
        raise CompileError(f"output name '{name}' may only contain letters, digits and underscores")
    return f'"{name}"'


def plan_dependencies(plan: QueryPlan, doc: MetadataDoc) -> list[str]:
    deps = {d.field for d in plan.dimensions} | {f.field for f in plan.filters}
    metrics = {m.name: m for m in doc.metrics}
    for m in plan.measures:
        if m.metric:
            deps.add(f"metric:{m.metric}")
            if m.metric in metrics:
                deps |= set(metrics[m.metric].expr.columns())
        elif m.field:
            deps.add(m.field)
        elif m.expr:
            deps |= set(m.expr.columns())
    return sorted(deps)


def plan_hash(plan: QueryPlan | dict, data_source_id: str) -> str:
    data = plan.model_dump(exclude_none=True) if isinstance(plan, QueryPlan) else plan
    raw = json.dumps({"ds": data_source_id, "plan": data}, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]

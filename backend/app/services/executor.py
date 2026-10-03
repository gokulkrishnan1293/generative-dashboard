"""Execution service: authorizes, bounds and runs compiled data requests.

Results go from here straight to the UI. Nothing in this module talks to the agent.
"""

from __future__ import annotations

import threading
import time
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError, SQLAlchemyError

from ..config import get_settings
from ..schemas import Filter, MetadataDoc, QueryPlan
from .compiler import Catalog, CompileError, compile_plan, plan_hash
from .sources import get_engine


class ExecutionError(RuntimeError):
    pass


_cache: dict[tuple[str, str], tuple[float, dict]] = {}
_cache_lock = threading.Lock()


def dialect_of(url: str) -> str:
    return make_url(url).get_backend_name()


def effective_plan(
    widget_query: dict, dashboard_filters: list[dict], doc: MetadataDoc, role: str, dialect: str
) -> tuple[QueryPlan, list[dict]]:
    """Widget filters override dashboard filters on the same field. Dashboard filters that
    cannot apply to a widget (e.g. would require a fanning-out join) are skipped and reported."""
    plan = QueryPlan.model_validate(widget_query)
    own = {f.field for f in plan.filters}
    skipped: list[dict] = []
    catalog = Catalog(doc, role)
    s = get_settings()
    for raw in dashboard_filters or []:
        f = Filter.model_validate(raw)
        if f.field in own:
            continue
        candidate = plan.model_copy(update={"filters": [*plan.filters, f]})
        try:
            compile_plan(candidate, catalog, dialect, s.default_row_limit, s.max_row_limit)
        except CompileError as exc:
            skipped.append({"field": f.field, "reason": str(exc)})
            continue
        plan = candidate
    return plan, skipped


def _jsonable(v: Any) -> Any:
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    if isinstance(v, bytes):
        return v.hex()
    return v


def execute_plan(
    plan: QueryPlan, doc: MetadataDoc, url: str, data_source_id: str, role: str, force: bool = False
) -> dict:
    s = get_settings()
    dialect = dialect_of(url)
    key = plan_hash(plan, data_source_id)
    cache_key = (role, key)
    now = time.time()
    # Authorization and validation happen on every execution, including saved dashboards
    # and cache hits, so a metadata or permission change takes effect immediately.
    compiled = compile_plan(plan, Catalog(doc, role), dialect, s.default_row_limit, s.max_row_limit)
    if not force:
        with _cache_lock:
            hit = _cache.get(cache_key)
        if hit and now - hit[0] < s.result_cache_ttl_seconds:
            return {**hit[1], "cached": True}

    engine = get_engine(url)
    started = time.perf_counter()
    deadline = started + s.query_timeout_seconds
    try:
        with engine.connect() as conn:
            if dialect == "sqlite":
                raw = conn.connection.driver_connection
                raw.set_progress_handler(lambda: 1 if time.perf_counter() > deadline else 0, 20000)
            elif dialect == "postgresql":
                conn.exec_driver_sql(f"SET statement_timeout = {int(s.query_timeout_seconds * 1000)}")
            try:
                result = conn.execute(compiled.statement)
                keys = list(result.keys())
                rows = result.fetchmany(compiled.limit + 1)
            finally:
                if dialect == "sqlite":
                    raw.set_progress_handler(None, 0)
    except OperationalError as exc:
        if time.perf_counter() > deadline:
            raise ExecutionError(f"query exceeded the {s.query_timeout_seconds:.0f}s time limit") from exc
        raise ExecutionError(f"database error: {type(exc.orig).__name__ if exc.orig else 'OperationalError'}") from exc
    except SQLAlchemyError as exc:
        raise ExecutionError(f"database error: {type(exc).__name__}") from exc

    truncated = len(rows) > compiled.limit
    rows = rows[: compiled.limit]
    payload = {
        "query_hash": key,
        "columns": [
            {"key": o.key, "kind": o.kind, "field": o.field, "metric": o.metric, "grain": o.grain, "format": o.format}
            for o in compiled.outputs
        ],
        "rows": [{k: _jsonable(v) for k, v in zip(keys, r)} for r in rows],
        "row_count": len(rows),
        "truncated": truncated,
        "limit": compiled.limit,
        "executed_at": datetime.now(timezone.utc).isoformat(),
        "duration_ms": int((time.perf_counter() - started) * 1000),
        "cached": False,
    }
    with _cache_lock:
        _cache[cache_key] = (now, payload)
        if len(_cache) > 500:
            for k in sorted(_cache, key=lambda k: _cache[k][0])[:100]:
                _cache.pop(k, None)
    return payload


def clear_cache() -> None:
    with _cache_lock:
        _cache.clear()

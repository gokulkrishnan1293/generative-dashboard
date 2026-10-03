import pytest

from app.schemas import MetadataDoc, QueryPlan
from app.services.compiler import Catalog, CompileError, compile_plan
from app.services.demo_metadata import apply_demo_metadata
from app.services.demo_seed import create_demo_database, demo_url
from app.services.executor import execute_plan
from app.services.introspect import discover_schema, merge_discovery


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    path = tmp_path_factory.mktemp("db") / "demo.db"
    create_demo_database(str(path))
    url = demo_url(str(path))
    doc, _ = merge_discovery(MetadataDoc(), discover_schema(url))
    return url, apply_demo_metadata(doc)


def run(env, plan, role="analyst"):
    url, doc = env
    return execute_plan(QueryPlan.model_validate(plan), doc, url, "ds", role, force=True)


def test_metric_by_month(env):
    r = run(env, {"dimensions": [{"field": "orders.order_date", "grain": "month", "alias": "month"}],
                  "measures": [{"alias": "revenue", "metric": "revenue"}]})
    months = [row["month"] for row in r["rows"]]
    assert months == sorted(months) and len(months) >= 24


def test_fanout_rejected(env):
    with pytest.raises(CompileError, match="inflated"):
        run(env, {"dimensions": [{"field": "products.category"}],
                  "measures": [{"alias": "ship", "agg": "sum", "field": "orders.shipping_cost"}]})


def test_count_distinct_across_fanout_allowed(env):
    r = run(env, {"dimensions": [{"field": "products.category"}],
                  "measures": [{"alias": "orders", "metric": "order_count"}]})
    assert r["row_count"] == 6


def test_ambiguous_path_requires_via(env):
    plan = {"dimensions": [{"field": "regions.name", "alias": "region"}],
            "measures": [{"alias": "revenue", "metric": "revenue"}]}
    with pytest.raises(CompileError, match="ambiguous"):
        run(env, plan)
    r = run(env, {**plan, "via": ["customers.region_id->regions.id"]})
    assert all(row["region"] for row in r["rows"])


def test_restricted_table_requires_admin(env):
    plan = {"dimensions": [{"field": "sales_reps.full_name"}],
            "measures": [{"alias": "salary", "agg": "sum", "field": "sales_rep_compensation.base_salary"}]}
    with pytest.raises(CompileError, match="restricted"):
        run(env, plan, role="viewer")
    assert run(env, plan, role="admin")["row_count"] == 10


def test_unapproved_column_rejected(env):
    url, doc = env
    doc.table("orders").column("channel").status = "needs_review"
    try:
        with pytest.raises(CompileError, match="not approved"):
            compile_plan(QueryPlan.model_validate({"dimensions": [{"field": "orders.channel"}]}),
                         Catalog(doc, "admin"), "sqlite", 100, 1000)
    finally:
        doc.table("orders").column("channel").status = "approved"


def test_filter_values_are_bound_parameters(env):
    r = run(env, {"dimensions": [{"field": "customers.name"}],
                  "filters": [{"field": "customers.name", "op": "eq", "value": "x' OR '1'='1"}]})
    assert r["row_count"] == 0


def test_row_limit_and_truncation(env):
    r = run(env, {"dimensions": [{"field": "orders.id"}], "limit": 10})
    assert r["row_count"] == 10 and r["truncated"] is True

import json


def widget(title="Revenue by month", type_="line", filters=None):
    return {
        "type": type_, "title": title,
        "query": {"dimensions": [{"field": "orders.order_date", "grain": "month", "alias": "month"}],
                  "measures": [{"alias": "revenue", "metric": "revenue"}],
                  "filters": filters or []},
        "presentation": {"x": "month", "y": ["revenue"], "w": 6, "h": 5},
    }


def test_generate_refine_undo(client, demo_source, fake_llm):
    fake_llm.responses.append({
        "message": "Created a sales dashboard.",
        "operations": [{"op": "create_dashboard", "ref": "d1", "name": "Sales", "widgets": [
            widget(filters=[{"field": "orders.status", "op": "neq", "value": "cancelled"}]),
            {"type": "kpi", "title": "Total revenue", "query": {"measures": [{"alias": "revenue", "metric": "revenue"}]},
             "presentation": {"y": ["revenue"], "w": 3, "h": 2}},
        ]}],
    })
    r = client.post("/api/agent/chat", json={"prompt": "Create a sales dashboard"}).json()
    assert r["message"]["status"] == "ok", r
    dash = r["dashboards"][0]
    line, kpi = dash["widgets"]

    data = client.post(f"/api/widgets/{line['id']}/data").json()
    assert data["row_count"] > 0 and data["query_hash"] == line["effective_query_hash"]

    # The agent never receives results: no business value from the result appears in its input.
    sample_value = str(data["rows"][0]["revenue"])
    fake_llm.responses.append({
        "message": "Changed to a bar chart.",
        "operations": [{"op": "update_widget", "widget_id": line["id"], "changes": {"type": "bar"}}],
    })
    r2 = client.post("/api/agent/chat", json={"prompt": "Make this a bar chart",
                                              "selection": {"widget_ids": [line["id"]]}}).json()
    sent = fake_llm.requests[-1][1]
    assert sample_value not in sent
    # Existing filter values are redacted before reaching the agent.
    assert "cancelled" not in json.dumps(json.loads(sent)["canvas"])
    assert "«v1»" in sent
    updated = next(w for w in r2["dashboards"][0]["widgets"] if w["id"] == line["id"])
    assert updated["type"] == "bar"
    # Presentation-only change: same effective query, results reusable; filter value preserved.
    assert updated["effective_query_hash"] == line["effective_query_hash"]
    assert updated["query"]["filters"][0]["value"] == "cancelled"

    # Undo restores the line chart.
    undo = client.post(f"/api/history/{r2['message']['change_set_id']}/undo")
    assert undo.status_code == 200, undo.text
    canvas = undo.json()
    restored = next(d for d in canvas["dashboards"] if d["id"] == dash["id"])
    assert restored["widgets"][0]["type"] == "line"


def test_validator_feedback_loop(client, demo_source, fake_llm):
    bad = {"message": "x", "operations": [{"op": "create_dashboard", "name": "Bad", "widgets": [{
        "type": "bar", "title": "t",
        "query": {"dimensions": [{"field": "orders.nope"}], "measures": [{"alias": "n", "agg": "count"}]},
        "presentation": {"x": "nope", "y": ["n"]}}]}]}
    good = {"message": "ok", "operations": [{"op": "create_dashboard", "name": "Good", "widgets": [widget()]}]}
    fake_llm.responses += [bad, good]
    r = client.post("/api/agent/chat", json={"prompt": "orders"}).json()
    assert r["message"]["status"] == "ok"
    assert "unknown column 'orders.nope'" in fake_llm.requests[-1][1]


def test_clarification(client, demo_source, fake_llm):
    fake_llm.responses.append({"message": "", "clarification": {
        "question": "Customer region or sales-rep region?", "options": ["Customer region", "Rep region"]},
        "operations": []})
    r = client.post("/api/agent/chat", json={"prompt": "revenue by region"}).json()
    assert r["message"]["status"] == "clarification"
    assert r["message"]["clarification"]["options"] == ["Customer region", "Rep region"]


def test_direct_filter_edit_without_agent(client, demo_source, fake_llm):
    fake_llm.responses.append({"message": "ok", "operations": [
        {"op": "create_dashboard", "name": "Orders", "widgets": [widget(filters=[
            {"field": "orders.status", "op": "eq", "value": "pending"}])]}]})
    w = client.post("/api/agent/chat", json={"prompt": "pending"}).json()["dashboards"][0]["widgets"][0]
    calls = len(fake_llm.requests)
    r = client.patch(f"/api/widgets/{w['id']}", json={"filters": [
        {"field": "orders.status", "op": "eq", "value": "shipped"}]})
    assert r.status_code == 200 and len(fake_llm.requests) == calls
    assert r.json()["effective_query_hash"] != w["effective_query_hash"]


def test_viewer_cannot_read_restricted(client, demo_source, fake_llm):
    fake_llm.responses.append({"message": "ok", "operations": [{"op": "create_dashboard", "name": "Comp", "widgets": [{
        "type": "table", "title": "Salaries",
        "query": {"dimensions": [{"field": "sales_reps.full_name"}],
                  "measures": [{"alias": "salary", "agg": "sum", "field": "sales_rep_compensation.base_salary"}]},
        "presentation": {"columns": ["full_name", "salary"]}}]}]})
    r = client.post("/api/agent/chat", json={"prompt": "salaries"}, headers={"X-Role": "admin"}).json()
    wid = r["dashboards"][0]["widgets"][0]["id"]
    assert client.post(f"/api/widgets/{wid}/data", headers={"X-Role": "admin"}).status_code == 200
    denied = client.post(f"/api/widgets/{wid}/data", headers={"X-Role": "viewer"})
    assert denied.status_code == 422 and "restricted" in denied.json()["detail"]["message"]


def test_schema_change_flags_dependents(client, demo_source):
    ds_id = demo_source["id"]
    meta = client.get(f"/api/datasources/{ds_id}/metadata").json()
    for t in meta["tables"]:
        if t["name"] == "orders":
            for c in t["columns"]:
                if c["name"] == "status":
                    c["status"] = "needs_review"
    r = client.put(f"/api/datasources/{ds_id}/metadata", json=meta).json()
    assert any("orders.status" in i for item in r["impact"] for i in item["issues"])
    client.post(f"/api/datasources/{ds_id}/metadata/load-demo")


def test_heuristic_draft_without_llm(client):
    ds = client.get("/api/datasources").json()[0]
    r = client.post(f"/api/datasources/{ds['id']}/draft")
    assert r.status_code == 200 and r.json()["notes"]

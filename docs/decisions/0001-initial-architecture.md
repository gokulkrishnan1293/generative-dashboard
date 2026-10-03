# 0001 — Initial architecture for the first implementation

**Status:** Accepted for the first build · **Date:** 3 October 2026

This record answers the implementation questions deferred in PRD §10 for the first working version. Each can be revisited.

## 1. Data requests are a structured plan, not SQL

The agent emits a JSON *query plan* (`dimensions`, `measures`, `filters`, `order_by`, `limit`, optional `via`). The execution service (`backend/app/services/compiler.py`) compiles it to SQL with SQLAlchemy Core.

- Every field must be an **approved**, role-visible `table.column`. Measures may reference **approved metrics** (`revenue`, `gross_margin` …) defined once in the metadata wrapper.
- **Joins are never written by the agent.** The compiler derives a join tree from approved relationships. When two paths are equally valid (customer region vs. sales-rep region), it rejects the plan as *ambiguous* until `via` names the intended relationship, or the agent asks the user.
- **Grain check:** a `sum`/`avg`/`count` whose rows would be multiplied by a one-to-many join is rejected (`count_distinct`, `min`, `max` are allowed). This prevents the classic “summing order shipping cost per product line” error.
- Filter values are always bound parameters. Rows are capped (`MAX_ROW_LIMIT`) and queries time out (`QUERY_TIMEOUT_SECONDS`).

Validation errors mention metadata only, so they are fed back to the agent for up to two self-corrections.

## 2. UI generation configures a component catalog

Widgets are one of `kpi | table | bar | line | area | pie`, with a small `presentation` object (x, y, series, stacking, formats, labels, grid size). No generated code runs in the browser.

## 3. Changes are operations applied as change sets

The agent returns operations (`create_dashboard`, `add_widget`, `update_widget`, `move_dashboard`, …). They are validated as a whole, then applied in one transaction. A **change set** stores before/after snapshots of every touched dashboard. Undo restores the before state only if no later change modified the same dashboard content (geometry moves are ignored for that check).

Direct UI edits (rename, edit an existing filter value, change chart type, move/resize) go straight to the API without a generation step. Content edits are versioned the same way.

## 4. Data boundary

- The agent receives: approved metadata, the list of dashboards (ids, names, positions, widget titles), full definitions only for the **selected** items, and recent chat text.
- **Existing filter values are redacted** to placeholders (`«v1»`) before they are sent, and restored in the response. Values a user types in a prompt are, by nature, sent with the prompt.
- Query results, cached rows and execution errors are never sent. Every model call is stored in `agent_calls` and exposed to admins at `GET /api/audit/agent-calls` for verification.

## 5. Loading and refresh across a large canvas

- Each widget fetches independently (`POST /api/widgets/{id}/data`) and shows its own queued, loading (with elapsed time), success, empty or error state.
- Only dashboards intersecting the viewport fetch data. Below 30% zoom, dashboards render as lightweight placeholders. The client runs at most 4 requests at once.
- Every widget definition carries an `effective_query_hash` (widget query plus applicable dashboard filters). If the client already holds results for that hash, as after a presentation-only change, nothing is re-fetched. The server also caches results for `RESULT_CACHE_TTL_SECONDS`, but authorizes **before** serving a cached result.

## 6. State

| Scope | Where |
| --- | --- |
| Canvas viewport | `canvas_state` |
| Dashboard (name, geometry, shared filters) | `dashboards` |
| Widget (type, query plan, presentation) | `widgets` |
| Metadata wrapper | `data_sources.metadata_doc` (JSON) |
| History | `change_sets`, `chat_messages`, `agent_calls` |
| Runtime results | client memory + short server cache, never persisted |

The application state lives in SQLite by default (`APP_DB_URL` accepts any SQLAlchemy URL).

**Shared-filter precedence:** a widget filter on the same field overrides the dashboard filter. A dashboard filter that cannot apply to a widget (unreachable, or it would fan out the widget's measures) is skipped and shown on the widget.

## 7. First data sources and access

SQLite and PostgreSQL are supported for execution (time grains are dialect-specific). Other SQLAlchemy dialects can be discovered but don't support time grains yet. A demo SQLite sales database is generated on first start.

Access is a demo role passed as the `X-Role` header (`admin | analyst | viewer`). Tables or columns marked **restricted** are usable only by `admin`, and this is enforced in the compiler on every execution, including saved dashboards and cache hits. Real authentication is out of scope for this build.

## 8. Model access

Any OpenAI-compatible Chat Completions endpoint (`OPENAI_BASE_URL`, `OPENAI_API_KEY`, `OPENAI_MODEL`) is supported. JSON-object response mode is used where supported, with an automatic fallback for gateways that reject it. Without a key, metadata drafting falls back to a structure-only draft, and dashboard generation reports that no model is configured.

## Not done yet

Real authentication; per-user canvases; collaboration; sensitive-value classification beyond redaction of existing filters; HAVING-style filters on measures; joins that need the same table twice; business-data writes (out of scope by PRD).

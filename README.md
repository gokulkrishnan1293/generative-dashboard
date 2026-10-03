# Generative Dashboard

Create, explore and maintain multiple dashboards on one persistent infinite canvas by describing what you want in natural language.

An agent reads a reviewed business-metadata wrapper over the database, produces **data requests** and **UI descriptions**, and the application executes those requests and renders the results. Business records never pass through the agent.

- Product requirements: [docs/PRD.md](docs/PRD.md)
- Architecture decisions: [docs/decisions/](docs/decisions/)

## Layout

```
backend/    Python — FastAPI API, dashboard agent (OpenAI-compatible gateway), query compiler & execution service
frontend/   React + TypeScript (Vite) — infinite canvas, dashboards, widgets, assistant, metadata review
docs/       PRD and decision records
```

## Run it

### Option A — local (Python 3.11+, Node 20+)

```bash
cp .env.example .env          # set OPENAI_API_KEY (and OPENAI_BASE_URL for your gateway)
./scripts/dev.sh              # or: make dev
```

- UI: http://localhost:5173 (Vite proxies `/api` to the backend)
- API: http://localhost:8000, interactive docs at http://localhost:8000/docs

### Option B — Docker

```bash
cp .env.example .env          # set OPENAI_API_KEY / OPENAI_BASE_URL
docker compose up --build     # or: make docker-up
```

- UI: http://localhost:8080 · API: http://localhost:8000

On first start the backend creates a demo SQLite sales database (customers, orders, order lines, products, regions, sales reps, and a confidential compensation table) and registers it as a data source with its schema discovered.

## Model gateway

Any endpoint that speaks the OpenAI Chat Completions API works:

| Variable | Purpose |
| --- | --- |
| `OPENAI_API_KEY` | Required for generation and AI drafting |
| `OPENAI_BASE_URL` | Your gateway URL (empty = api.openai.com) |
| `OPENAI_MODEL` | Model name as the gateway expects it (default `gpt-4o`) |
| `OPENAI_TEMPERATURE` | Empty to omit (for models that reject it) |
| `OPENAI_DEFAULT_HEADERS` | JSON of extra headers, e.g. `{"x-team":"bi"}` |

The top bar shows whether a model is configured.

## Test walkthrough (PRD §12)

1. **Onboard.** Open **Metadata**. The demo source is discovered but nothing is approved. Click **Draft with AI**: the agent drafts table and column meanings, coded values, relationships and metrics from schema structure plus the bundled glossary. Items with low confidence or open questions are listed first and highlighted.
   *Shortcut:* **Use reviewed demo metadata** approves a hand-reviewed wrapper.
2. **Review.** Correct a description, resolve an ambiguity (for example what `processing` status means), approve items, and **Save review**. Only approved items are usable. Switch the role to **admin** to mark tables or columns restricted.
3. **Generate.** On **Canvas**, ask: *“Create a sales dashboard showing monthly revenue, top 10 customers and revenue by customer region.”*
4. **Second dashboard.** *“Build an operations dashboard with order counts by status and a table of pending orders.”* Both stay on the canvas. Drag headers to move, drag the corner to resize, Ctrl/⌘+scroll to zoom, and use the minimap or left list to navigate.
5. **Refine by selection.** Click a table widget and ask *“Add customer region to this table”*. Click a chart and ask *“Change this to a bar chart”*: it re-renders from the existing results without re-fetching. Select a dashboard and ask *“Move this next to the sales dashboard”*.
6. **Clarification.** Ask *“Revenue by region”* with nothing selected. Region is ambiguous (customer vs. sales rep), so the agent should ask, or the validator forces it to choose.
7. **Direct edits.** Click a filter chip to change its value. This applies without the agent. **History** (or *Undo this change* in the chat) reverts any change.
8. **Execution feedback.** Every widget loads independently with its own status and *last refreshed* time. Use ↻ to refresh one widget or a whole dashboard.
9. **Access.** Switch role to **viewer**: widgets over restricted data fail with an authorization error, while others keep working.
10. **Boundary audit.** As **admin**, `GET /api/audit/agent-calls` shows exactly what was sent to the model: metadata and definitions only, with filter values redacted.
11. **Schema change.** Edit the demo DB (for example `ALTER TABLE orders ADD COLUMN priority TEXT`) and click **Re-scan schema**: new or changed columns return to review, and affected saved widgets are listed.

## Development

```bash
make test        # backend tests (pytest)
make typecheck   # frontend type check
make reset-data  # wipe local state and demo DB (recreated on next start)
```

## Status

First working implementation of the PRD: onboarding, review, generation, refinement, persistence, history and undo, and per-widget execution. See [docs/decisions/0001-initial-architecture.md](docs/decisions/0001-initial-architecture.md) for what was decided and what is not done yet.

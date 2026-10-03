# Generative Dashboard

Create, explore and maintain multiple dashboards on one persistent infinite canvas by describing what you want in natural language.

An agent reads a reviewed business-metadata wrapper over the database, produces **data requests** and **UI descriptions**, and the application executes those requests and renders the results. Business records never pass through the agent.

- Product requirements: [docs/PRD.md](docs/PRD.md)
- Architecture decisions: [docs/decisions/](docs/decisions/)

## Layout

```
backend/    Python — FastAPI API, LangGraph agent, query execution service
frontend/   React + TypeScript — infinite canvas, dashboards, widgets
docs/       PRD and decision records
```

## Status

Pre-implementation. Repository scaffolded; feature work not started.

#!/usr/bin/env bash
# Start backend (http://localhost:8000) and frontend (http://localhost:5173) for local development.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

if [ ! -d "$ROOT/backend/.venv" ]; then
  python3 -m venv "$ROOT/backend/.venv"
  "$ROOT/backend/.venv/bin/pip" install -q -r "$ROOT/backend/requirements-dev.txt"
fi
if [ ! -d "$ROOT/frontend/node_modules" ]; then
  (cd "$ROOT/frontend" && npm install)
fi
[ -f "$ROOT/.env" ] || cp "$ROOT/.env.example" "$ROOT/.env"

trap 'kill 0' EXIT
(cd "$ROOT/backend" && .venv/bin/uvicorn app.main:app --reload --host 0.0.0.0 --port 8000) &
(cd "$ROOT/frontend" && npx vite --port 5173) &
wait

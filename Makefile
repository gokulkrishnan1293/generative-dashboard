.PHONY: dev setup test typecheck docker-up docker-down reset-data

dev:            ## Run backend + frontend locally
	./scripts/dev.sh

setup:          ## Install backend and frontend dependencies
	python3 -m venv backend/.venv && backend/.venv/bin/pip install -r backend/requirements-dev.txt
	cd frontend && npm install

test:           ## Backend tests
	cd backend && .venv/bin/python -m pytest -q

typecheck:      ## Frontend type check
	cd frontend && npx tsc -b

docker-up:      ## Build and run everything in Docker (UI on http://localhost:8080)
	docker compose up --build -d

docker-down:
	docker compose down

reset-data:     ## Delete local app state and demo database (recreated on next start)
	rm -f backend/data/app.db backend/data/demo_sales.db

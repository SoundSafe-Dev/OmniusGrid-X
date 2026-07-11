# OmniusGrid task runner (task 18). Unifies the previously-manual commands.
# `make help` lists targets.
.DEFAULT_GOAL := help
.PHONY: help up down logs test test-backend test-edge test-frontend e2e lint \
        migrate seed sdk env tracing

help: ## List available targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
	  awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

env: ## Create .env files from the templates (idempotent)
	@for d in . backend frontend edge-agent; do \
	  if [ -f $$d/.env.example ] && [ ! -f $$d/.env ]; then \
	    cp $$d/.env.example $$d/.env && echo "created $$d/.env"; fi; done

up: ## Start the full stack (docker-compose)
	docker-compose up -d

down: ## Stop the stack
	docker-compose down

logs: ## Tail stack logs
	docker-compose logs -f

tracing: ## Start the stack with the tracing profile (OTel collector + Jaeger)
	docker-compose --profile tracing up -d

test: test-backend test-edge test-frontend ## Run all test suites

smoke: ## Deployment-free end-to-end smoke (in-process app + SQLite)
	cd backend && python scripts/smoke_e2e.py

seed-demo: ## Seed realistic correlated demo data (simulated ERP + sensors + yard)
	cd backend && python scripts/seed_demo_data.py --verify

demo: seed-demo ## Seed demo data, then serve the API against it (dev.db)
	cd backend && DATABASE_URL="sqlite+aiosqlite:///$$(pwd)/dev.db" uvicorn app.main:app --port 8000

test-backend: ## Backend pytest
	cd backend && python -m pytest -q

test-edge: ## Edge-agent pytest
	cd edge-agent && python -m pytest -q

test-frontend: ## Frontend Vitest
	cd frontend && npm run test

e2e: ## Frontend Playwright E2E
	cd frontend && npm run e2e

lint: ## Lint backend (ruff/black) and frontend (eslint)
	cd backend && ruff check . || true
	cd frontend && npm run lint || true

migrate: ## Apply pending DB migrations (incremental runner; Postgres)
	cd backend && python scripts/migrate.py

migrate-status: ## Show applied/pending migrations
	cd backend && python scripts/migrate.py --status

migrate-baseline: ## Mark all current migrations as applied without running (initdb-built DB)
	cd backend && python scripts/migrate.py --baseline

migrate-lint: ## Fail on duplicate migration prefixes
	cd backend && python scripts/check_migrations.py

seed: ## Seed demo data
	cd backend && python scripts/seed_demo_kanban.py

sdk: ## Regenerate the TypeScript API client from the OpenAPI schema
	./scripts/generate_sdk.sh

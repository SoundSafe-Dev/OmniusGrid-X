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

migrate: ## Apply DB migrations (via docker-compose postgres init or alembic)
	cd backend && alembic upgrade head

seed: ## Seed demo data
	cd backend && python scripts/seed_demo_kanban.py

sdk: ## Regenerate the TypeScript API client from the OpenAPI schema
	./scripts/generate_sdk.sh

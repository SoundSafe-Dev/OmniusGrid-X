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
	# OTEL_ENABLED=true is the part that was missing: the profile started a
	# collector and a Jaeger UI, but the backend never enabled export, so the
	# UI was permanently empty and nothing indicated why.
	OTEL_ENABLED=true docker-compose --profile tracing up -d

lean: ## Drop the 1.5 GB training corpus from THIS checkout (keeps it in git)
	@git sparse-checkout init --no-cone 2>/dev/null || true
	@printf '/*\n!/backend/dataset/\n' > .git/info/sparse-checkout
	@git sparse-checkout reapply
	@echo "backend/dataset is no longer checked out. 'make unlean' restores it."

unlean: ## Restore the training corpus to this checkout
	@git sparse-checkout disable
	@echo "backend/dataset restored."

reap-test-containers: ## Remove testcontainers left behind by killed test runs (FS-371)
	# WHY THIS IS A TARGET AND NOT A CRON. Ryuk — testcontainers' own reaper — is
	# DISABLED in `backend/tests/conftest.py`, deliberately: it needs the docker socket
	# bind-mounted into a container, and colima's VM boundary makes that mount fail, so
	# with Ryuk enabled the suite could not start at all. The comment there states the
	# cost plainly: containers from a hard-killed run are no longer cleaned up.
	#
	# In the ordinary case the fixtures stop their own containers and nothing accumulates.
	# The leak is Ctrl-C, a crashed runner, an OOM — and it had reached 23 stopped
	# containers holding 13 GB, which is what gated the Docker-disk item.
	#
	# Matched on the testcontainers label rather than on an image name: the suite starts
	# postgres, redpanda and redis, and a list of images is a list to forget to update.
	# `--filter status=exited` so a container from a RUNNING suite is never touched — this
	# has to be safe to run while somebody else is testing.
	@stale=$$(docker ps -aq --filter "label=org.testcontainers=true" --filter "status=exited" 2>/dev/null); 	if [ -z "$$stale" ]; then 		echo "no stale test containers"; 	else 		echo "$$stale" | xargs docker rm -v; 		echo "reclaimed; run 'docker system df' to see the space back"; 	fi

test: test-backend test-edge test-frontend ## Run all test suites

compliance: ## Regenerate the SSP, Statement of Applicability and POA&M from the control catalogue
	cd backend && venv/bin/python scripts/compliance/render.py

smoke: ## Deployment-free end-to-end smoke (in-process app + SQLite)
	cd backend && python scripts/smoke_e2e.py

seed-demo: ## Seed realistic correlated demo data (simulated ERP + sensors + yard)
	cd backend && python scripts/seed_demo_data.py --verify

demo: seed-demo ## One-shot offline demo: seed, then serve the API against dev.db
	@echo ">> API on :8000 with dev-token auth. In another shell:"
	@echo ">>   make demo-ui                                (login: dev / any password)"
	@echo ">> Full walkthrough: docs/DEMO.md"
	cd backend && DATABASE_URL="sqlite+aiosqlite:///$$(pwd)/dev.db" ALLOW_DEV_TOKEN=true uvicorn app.main:app --port 8000

# THE SKIP-LOGIN DEMO NEEDS TWO GATES, NOT ONE, and this target exists because the
# instructions here previously named only the first. `ALLOW_DEV_TOKEN=true` (above) makes
# the BACKEND accept the `dev-token` bearer; `VITE_DEV_MODE=true` makes the FRONTEND offer
# the bypass at all — `Login.tsx` requires `import.meta.env.DEV && VITE_DEV_MODE === 'true'`.
# Without the second, typing `dev` falls through to the real login form and returns 401,
# which is exactly what the documented command did (verified against a running stack,
# 2026-08-01). A make target rather than a line to copy, so the pair cannot drift apart
# again; `test_demo_mode_instructions_work.py` pins them to what the code requires.
demo-ui: ## The demo UI, in real mode against the demo API (skip-login enabled)
	cd frontend && VITE_USE_MOCK=false VITE_DEV_MODE=true npm run dev

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

# Application Rollback - Disaster Recovery Runbook

## Overview
This runbook covers rolling back a bad OmniusGrid **application release** (backend,
ingestion worker, frontend, or edge agent) on both **Docker Compose** and
**Kubernetes**. Use it when a deploy introduces crashes, elevated error rates,
failed migrations, or regressions — and the fastest safe action is to return to the
last known-good version.

This is a **code/image rollback** runbook. For infrastructure failures (database,
broker, network) use the component-specific runbooks in the
[index](README.md).

## When to roll back
Roll back if, shortly after a deploy, you observe any of:
- Backend `/health/ready` failing or crash-looping pods/containers
- Error rate spike (5xx) or `BackendAPIDown` alert firing
- A database migration that failed midway or is causing query errors
- A regression confirmed in a critical user flow (login, telemetry, kanban)

Prefer rollback over forward-fixing when the cause is not immediately obvious and
users are impacted.

## Impact
- **RPO:** 0 minutes — application services are stateless; no telemetry/alarm data
  is lost by rolling back code. (Exception: a forward database migration that
  already changed the schema — see [Database migration rollbacks](#database-migration-rollbacks).)
- **RTO:** 5–10 minutes (image redeploy + health check).

## Pre-rollback checklist
- [ ] Identify the current (bad) version/tag and the target (last known-good) version/tag.
- [ ] Confirm whether the bad release included a **database migration**.
- [ ] Notify the incident channel (see [communication templates](incident-communication-templates.md)).
- [ ] Capture logs from the bad version **before** replacing it (for RCA).

```bash
# Docker Compose: capture logs first
docker compose logs --no-color backend > /tmp/backend-bad-release.log

# Kubernetes: capture logs first
kubectl logs deployment/prod-backend -n omniusgrid --tail=1000 > /tmp/backend-bad-release.log
```

---

## Docker Compose rollback

Compose services are defined in [`docker-compose.yml`](../../../docker-compose.yml)
(`backend`, `ingestion-worker`, `frontend`, `edge-agent-sim`).

### Step 1 — Identify the target version
The known-good version is whatever image tag / git commit was deployed before the
bad release.

```bash
# Which image is currently running?
docker compose images backend

# If you deploy from git on the host, find the previous good commit
git log --oneline -n 10
```

### Step 2 — Roll back the code/image

**If you build images from the repo (git-based deploy):**
```bash
# Check out the last known-good commit or tag
git checkout <last-good-tag-or-commit>

# Rebuild and restart only the affected services
docker compose up -d --build backend ingestion-worker
```

**If you deploy pre-built tagged images:**
```bash
# Pin the known-good tag (e.g. via .env: BACKEND_TAG=v1.4.2) then:
docker compose pull backend ingestion-worker
docker compose up -d backend ingestion-worker
```

### Step 3 — Verify
```bash
docker compose ps
curl -fsS http://localhost:8002/health/ready | jq .
./scripts/dr-validate-recovery.sh
```

### Step 4 — Roll back the frontend (if affected)
```bash
docker compose up -d --build frontend
# Host port is 9999 (compose maps 9999 -> container 3000).
curl -fsS http://localhost:9999 >/dev/null && echo "frontend OK"
```

---

## Kubernetes rollback

Manifests live in [`infrastructure/k8s/`](../../infrastructure/k8s/) (kustomize;
see its README). The backend Deployment is `prod-backend` (staging:
`staging-backend`) in namespace `omniusgrid` — the overlays' namePrefix.

Kubernetes keeps a rollout history per Deployment, so the fastest path is
`kubectl rollout undo`.

### Step 1 — Inspect rollout history
```bash
kubectl rollout history deployment/prod-backend -n omniusgrid
```

### Step 2 — Roll back

**Roll back to the immediately previous revision:**
```bash
kubectl rollout undo deployment/prod-backend -n omniusgrid
```

**Roll back to a specific revision:**
```bash
kubectl rollout undo deployment/prod-backend -n omniusgrid --to-revision=<N>
```

Repeat for other affected workloads (e.g. the ingestion deployment in
the worker Deployments in [`infrastructure/k8s/base/`](../../infrastructure/k8s/base/)).

### Step 3 — Watch the rollout complete
```bash
kubectl rollout status deployment/prod-backend -n omniusgrid --timeout=300s
kubectl get pods -n omniusgrid -l app=omniusgrid-backend
```

### Step 4 — Verify
```bash
# In-cluster health (port 8000); adjust if port-forwarding
kubectl exec deploy/omniusgrid-backend -n omniusgrid -- \
  curl -fsS http://localhost:8000/health/ready

./scripts/dr-validate-recovery.sh --target k8s --namespace omniusgrid
```

### Step 5 — Pin the image (prevent re-deploy of bad version)
If your CI auto-deploys `:latest`, pin the Deployment to the known-good digest so
the bad image is not re-pulled:
```bash
kubectl set image deployment/omniusgrid-backend \
  backend=omniusgrid/backend:<known-good-tag> -n omniusgrid
```

---

## Database migration rollbacks

> **Read this before rolling back if the bad release shipped a migration.**

Application code rolls back instantly; **schema changes do not**. If the bad release
applied a forward migration, rolling back code alone can leave old code running
against a new schema.

Migrations live in [`database/migrations/`](../../../database/migrations/).

Decision guide:

| Migration type | Safe to roll back code only? | Action |
|----------------|------------------------------|--------|
| Additive (new table/column, nullable) | Yes | Roll back code; leave schema (old code ignores new objects) |
| Destructive (drop/rename column, type change) | No | Restore DB to pre-migration point, then roll back code |
| Failed mid-migration | No | Restore DB, then roll back code |

For destructive or failed migrations, use point-in-time recovery to just before the
deploy:
```bash
# Pick a target time just BEFORE the bad deploy
infra/scripts/disaster_recovery.sh pitr "YYYY-MM-DD HH:MM:SS"
```
See [dr-timescaledb-failure.md](../dr-timescaledb-failure.md) for full restore
procedures and `infra/scripts/disaster_recovery.sh` for backup/restore commands.

---

## Verification (all paths)
1. **Readiness:** `/health/ready` returns 200 with all dependencies `ok`/`skipped`.
2. **Version:** confirm the running version matches the known-good target.
3. **Smoke test:** login, list assets, fetch latest telemetry, open kanban board.
4. **Validation script:** `./scripts/dr-validate-recovery.sh` passes.
5. **Alerts:** `BackendAPIDown` / error-rate alerts have cleared in Alertmanager.

## Post-incident actions
1. File an incident report (timestamp, bad version, target version, RTO actual).
2. Open a ticket to fix-forward the defect that triggered the rollback.
3. If a migration was involved, document the schema state and the fix-forward plan.
4. Add a regression test that would have caught the defect.

## Escalation matrix
| Time since detection | Action |
|----------------------|--------|
| 0–2 min | Confirm bad deploy, notify on-call, start rollback |
| 2–10 min | Complete rollback, verify health |
| 10–20 min | If rollback fails, escalate to backend lead |
| 20+ min | Escalate to CTO; consider DB restore if migration-related |

## Related documentation
- [Runbook index](README.md)
- [Backend crash runbook](../dr-backend-crash.md)
- [RTO/RPO verification checklist](rto-rpo-checklist.md)
- [Communication templates](incident-communication-templates.md)
- [docker-compose.yml](../../../docker-compose.yml)
- [infrastructure/k8s/base/backend-deployment.yaml](../../infrastructure/k8s/base/backend-deployment.yaml)

---

**Document Version:** 1.0
**Component:** Disaster Recovery — Application Rollback

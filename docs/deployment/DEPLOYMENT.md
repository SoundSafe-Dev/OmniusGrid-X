# Deploying OmniusGrid (greenfield)

Forward-deployment guide — the rest of this directory is disaster **recovery**
runbooks; this is how you stand the platform up in the first place.

## Option A — Docker Compose (single host)

```bash
# 1. Secrets: every ${VAR:?} in docker-compose.prod.yml is REQUIRED — startup
#    aborts if unset. Generate long random values.
export POSTGRES_PASSWORD=... JWT_SECRET_KEY=... SIGNED_URL_SECRET_KEY=... \
       EDGE_BOOTSTRAP_TOKEN=... GEOTAB_WEBHOOK_SECRET=... ERP_ENCRYPTION_KEY=... \
       CORS_ALLOW_ORIGINS=https://your-app.example.com \
       IMAGE_TAG=v1.0.0

# 2. Bring it up. The one-shot `migrate` service applies the SQL migrations
#    (backend/scripts/migrate.py, tracked in schema_migrations) before the API
#    starts; the frontend serves the built SPA via nginx on ${FRONTEND_PORT:-80}.
docker compose -f docker-compose.prod.yml up -d

# 3. Verify.
curl -sf http://localhost:8000/health/ready
```

The dev stack (`docker-compose.yml` / `make up`) is separate: bind-mounted
source, hot reload, permissive defaults, initdb-applied migrations.

**Existing database note:** a DB originally built via initdb has no
`schema_migrations` records. The runner detects this and refuses; adopt it once
with `python backend/scripts/migrate.py --baseline`.

## Option B — Kubernetes

The kustomize tree under `infrastructure/k8s/` is canonical — see
[infrastructure/k8s/README.md](../../infrastructure/k8s/README.md) for the
required pre-created secrets and apply commands. CI deploys staging on pushes
to `develop` and production on `v*` tags (`.github/workflows/ci-cd.yml`).

## Option C — Bare-metal edge agent

```bash
sudo edge-agent/deploy/install.sh     # venv under /opt/opsgrid-agent + systemd unit
sudo vi /etc/opsgrid-agent/agent.env  # org, agent id, CLOUD_URL, bootstrap token
sudo systemctl enable --now opsgrid-agent
```

## Production posture checklist

The backend **fails fast at startup** unless all of these hold in
`ENVIRONMENT=production` (see `validate_settings` in
`backend/app/core/config.py`):

| Setting | Required value |
|---|---|
| `JWT_SECRET_KEY` | real secret (not the dev default) |
| `DEBUG` | `false` |
| `ALLOW_DEV_TOKEN` / `ALLOW_OPEN_REGISTRATION` | `false` |
| `CORS_ALLOW_ORIGINS` | explicit origin allowlist |
| `EDGE_BOOTSTRAP_TOKEN` / `GEOTAB_WEBHOOK_SECRET` / `ERP_ENCRYPTION_KEY` | set |
| `GEOTAB_SIMULATED` | `false` (no demo telematics) |
| `EDGE_REQUIRE_PROOF_OF_POSSESSION` | `true` (signed edge requests) |

Edge agents in production should additionally set `EDGE_REQUIRE_TLS=true`,
`KAFKA_SECURITY_PROTOCOL=SSL`, `EDGE_REQUIRE_EXPLICIT_SOURCES=true`, and pin
`ENROLLMENT_CA_FINGERPRINT` (sha256 of the edge CA cert DER).

## Observability

Prometheus/Grafana/Loki configs live under `infra/`; alert rules include edge
agent reachability, ingest lag, and buffer growth
(`infra/prometheus/alerts.yml`).

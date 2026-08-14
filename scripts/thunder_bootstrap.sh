#!/usr/bin/env bash
# Bring up the RAG stack on a Thunder Compute instance (e.g. `ssh tnr-0`).
#
# WHY THIS EXISTS INSTEAD OF `docker compose --profile rag up`:
# A Thunder instance is itself a sandboxed container, and its Docker daemon:
#   * cannot BUILD images   - buildkit: "failed to mount .../buildkit-mount:
#                             operation not permitted" (fastvfs storage driver);
#                             legacy builder: "unshare: operation not permitted".
#   * cannot CREATE networks - only `host` and `none` exist; `docker network
#                             create` returns "operation not permitted", which
#                             makes compose unusable (it always makes a network).
#   * has no /dev/fd inside containers, breaking bash process substitution in
#     official entrypoints (postgres initdb dies on /dev/fd/63).
#   * blocks privilege-dropping entrypoints (redis: "setpriv: setresgid failed").
# `docker pull` and `docker run` work fine, so: datastores run as PRE-BUILT
# images on --network host, and the Python services run natively from .venv.
# Host ports then match the compose host-port mappings, so
# scripts/verify_rag_e2e.py runs unmodified.
#
# WHAT THIS DOES NOT VERIFY: the Dockerfiles, the compose service wiring, and
# the k8s manifests. Those need a box that can build images.
#
# Usage:  ./thunder_bootstrap.sh setup   # one-time: venv deps, ollama model
#         ./thunder_bootstrap.sh start   # datastores + migrations + services
#         ./thunder_bootstrap.sh stop
#         ./thunder_bootstrap.sh status
set -euo pipefail

REPO=${REPO:-/home/ubuntu/OmniusGrid-X}
VENV=$REPO/.venv
PGPASS=omniusgrid_dev_password
export DATABASE_URL=postgresql://omniusgrid:$PGPASS@localhost:5432/omniusgrid
DS="omniusgrid-timescaledb omniusgrid-redis omniusgrid-qdrant omniusgrid-seaweedfs"

write_env() {
  cat > /home/ubuntu/rag.env <<EOF
DATABASE_URL=$DATABASE_URL
REDIS_URL=redis://localhost:6379/0
REDPANDA_URL=localhost:29092
JWT_SECRET_KEY=dev_secret_key_change_in_production
SIGNED_URL_SECRET_KEY=dev_signed_link_secret_change_in_production
SCHEDULERS_IN_API=false
COMPLIANCE_REPORT_SCHEDULER_ENABLED=false
OTA_ROLLOUT_DISPATCH_ENABLED=false
EXPORT_STORAGE_PATH=/home/ubuntu/exports
QDRANT_URL=http://localhost:6333
S3_ENDPOINT_URL=http://localhost:8333
RAG_INFERENCE_URL=http://localhost:8001
RAG_EMBED_BATCH=8
RAG_INFERENCE_TIMEOUT=180
RAG_INDEX_WORKER_ENABLED=true
LLM_BASE_URL=http://localhost:11434/v1
LLM_MODEL=gemma4:12b
LLM_TEMPERATURE=0
VISION_MODEL_ENABLED=false
EOF
  mkdir -p /home/ubuntu/exports
}

setup() {
  # Python deps. FlagEmbedding resolves against the existing torch/transformers
  # with no downgrade (verified: torch 2.13.0+cu130, transformers 5.15.0).
  "$VENV/bin/pip" install -r "$REPO/backend/requirements.txt"
  "$VENV/bin/pip" install FlagEmbedding httpx boto3
  # LLM runs natively on the host (no GPU passthrough into containers here).
  command -v ollama >/dev/null || curl -fsSL https://ollama.com/install.sh | sh
  pgrep -x ollama >/dev/null || (setsid nohup ollama serve > /tmp/ollama.log 2>&1 < /dev/null &)
  sleep 3; ollama pull gemma4:12b
  for img in timescale/timescaledb:latest-pg15 redis:7-alpine \
             qdrant/qdrant:v1.12.4 chrislusf/seaweedfs:3.68; do docker pull "$img"; done
}

start_datastores() {
  docker rm -f $DS >/dev/null 2>&1 || true

  # The bash -c wrapper creates the /dev/fd symlink this sandbox is missing;
  # without it initdb fails on the entrypoint's <(...) pwfile.
  docker run -d --name omniusgrid-timescaledb --network host --restart unless-stopped \
    -e POSTGRES_USER=omniusgrid -e POSTGRES_PASSWORD=$PGPASS -e POSTGRES_DB=omniusgrid \
    -v timescaledb-data:/var/lib/postgresql/data \
    --entrypoint bash timescale/timescaledb:latest-pg15 \
    -c "ln -sfn /proc/self/fd /dev/fd; exec /usr/local/bin/docker-entrypoint.sh postgres -c shared_preload_libraries=timescaledb,pg_stat_statements"

  # --entrypoint redis-server skips docker-entrypoint.sh's blocked setpriv drop.
  docker run -d --name omniusgrid-redis --network host --restart unless-stopped \
    --entrypoint redis-server -v redis-data:/data redis:7-alpine --dir /data

  docker run -d --name omniusgrid-qdrant --network host --restart unless-stopped \
    -v qdrant-data:/qdrant/storage qdrant/qdrant:v1.12.4

  docker run -d --name omniusgrid-seaweedfs --network host --restart unless-stopped \
    -v seaweedfs-data:/data \
    -v "$REPO/infra/seaweedfs/s3config.json:/etc/seaweedfs/s3config.json:ro" \
    chrislusf/seaweedfs:3.68 \
    server -dir=/data -s3 -s3.config=/etc/seaweedfs/s3config.json -s3.port=8333 -ip.bind=0.0.0.0

  # NOTE: redpanda is deliberately absent - it dies inside Thunder's proot layer,
  # and the RAG path has no Kafka dependency (the rag_documents row IS the queue).

  echo "waiting for postgres..."
  for _ in $(seq 1 60); do
    "$VENV/bin/python" -c "import psycopg2,os;psycopg2.connect(os.environ['DATABASE_URL'])" 2>/dev/null && break
    sleep 2
  done
}

start_services() {
  write_env
  ( cd "$REPO/backend" && "$VENV/bin/python" scripts/migrate.py )

  # Native, so it gets the GPU: BGE-M3 + reranker load in ~36s at fp16, versus
  # the 600s CPU start_period the compose healthcheck budgets for.
  ( cd "$REPO/rag-inference" && HF_HOME=/home/ubuntu/hf-models USE_FP16=true \
      setsid nohup "$VENV/bin/uvicorn" app.main:app --host 0.0.0.0 --port 8001 \
      > /tmp/rag-inference.log 2>&1 < /dev/null & )

  ( set -a; . /home/ubuntu/rag.env; set +a; cd "$REPO/backend" && \
      setsid nohup "$VENV/bin/uvicorn" app.main:app --host 0.0.0.0 --port 8000 \
      > /tmp/backend.log 2>&1 < /dev/null & )

  ( set -a; . /home/ubuntu/rag.env; set +a; cd "$REPO/backend" && \
      setsid nohup "$VENV/bin/python" -m app.workers.rag_indexing \
      > /tmp/worker.log 2>&1 < /dev/null & )

  echo "logs: /tmp/{rag-inference,backend,worker}.log"
  echo "then: $VENV/bin/python $REPO/scripts/verify_rag_e2e.py"
}

status() {
  docker ps --format 'table {{.Names}}\t{{.Status}}'
  for p in 8001:rag-inference 8000:backend; do
    code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "http://localhost:${p%%:*}/health" || true)
    echo "${p##*:} /health -> ${code:-down}"
  done
  pgrep -af "app.workers.rag_indexing" >/dev/null && echo "worker: running" || echo "worker: down"
}

# Restart just the backend (not the worker or datastores) with retrieval
# ablation env overrides - RAG_SEARCH_MODE / RAG_RERANK_ENABLED, see
# app/core/config.py. Settings are read once at process startup, so picking
# up a new config means recreating the process, not an in-process toggle.
# Used by scripts/thunder_run_ablation.py between configs.
#
# Two non-obvious things here:
#  - `[u]vicorn ...` (bracket on the first char) instead of `uvicorn ...`:
#    plain `pkill -f 'uvicorn app.main:app ...'`, run non-interactively over
#    ssh, matches its OWN argv (which literally contains that pattern as the
#    -f value) and kills itself - and if the same literal string also occurs
#    later in this same script invocation (e.g. the launch line below), that
#    can kill the invoking shell before it gets there. The bracket avoids
#    self-matching.
#  - `disown` after backgrounding: without it, a `cmd &` launched via
#    non-interactive `ssh host "..."` can leave the remote shell hanging
#    indefinitely even though the child's stdio is fully redirected -
#    interactive sessions (`tnr connect`) don't show this, only one-shot
#    `ssh host "cmd"` invocations do.
restart_backend() {
  local search_mode="${1:?usage: restart-backend <hybrid|dense|sparse> <true|false>}"
  local rerank_enabled="${2:?usage: restart-backend <hybrid|dense|sparse> <true|false>}"
  pkill -f '[u]vicorn app.main:app --host 0.0.0.0 --port 8000' || true
  sleep 1
  ( set -a; . /home/ubuntu/rag.env; set +a
    export RAG_SEARCH_MODE="$search_mode" RAG_RERANK_ENABLED="$rerank_enabled"
    cd "$REPO/backend"
    setsid nohup "$VENV/bin/uvicorn" app.main:app --host 0.0.0.0 --port 8000 \
      > /tmp/backend.log 2>&1 < /dev/null &
    disown
  )
  sleep 1
  echo "backend relaunched: RAG_SEARCH_MODE=$search_mode RAG_RERANK_ENABLED=$rerank_enabled"
}

case "${1:-start}" in
  setup)  setup ;;
  start)  start_datastores; start_services; status ;;
  stop)   docker rm -f $DS >/dev/null 2>&1 || true
          pkill -f "uvicorn app.main:app" || true
          pkill -f "app.workers.rag_indexing" || true ;;
  status) status ;;
  restart-backend) restart_backend "${2:-}" "${3:-}" ;;
  *) echo "usage: $0 {setup|start|stop|status|restart-backend <mode> <rerank>}" >&2; exit 2 ;;
esac

#!/usr/bin/env bash
#
# rag.sh - local RAG stack helper (lean up/down, ingest, query, verify, doctor)
#
#   ./scripts/rag.sh doctor          # check the machine is ready (run this FIRST)
#   ./scripts/rag.sh up              # LEAN stack (qdrant+seaweedfs+bge+backend)
#   ./scripts/rag.sh up-full         # full stack incl. observability + RAG
#   ./scripts/rag.sh logs            # follow rag-inference (watch weights load)
#   ./scripts/rag.sh ingest FILE     # upload a document through the API
#   ./scripts/rag.sh query "text"    # ask a question (retrieval only)
#   ./scripts/rag.sh verify          # full data-plane E2E verification
#   ./scripts/rag.sh down            # stop the RAG services
#
set -euo pipefail

cd "$(dirname "$0")/.."   # repo root

BACKEND="${BACKEND_URL:-http://localhost:8000}"
INFER="${INFER_URL:-http://localhost:8001}"
TOKEN="dev-token"
LEAN_SERVICES="qdrant seaweedfs rag-inference backend"

G="\033[92m"; R="\033[91m"; Y="\033[93m"; B="\033[1m"; X="\033[0m"
ok(){ echo -e "  ${G}✓${X} $1"; }
warn(){ echo -e "  ${Y}!${X} $1"; }
bad(){ echo -e "  ${R}✗${X} $1"; }
have(){ command -v "$1" >/dev/null 2>&1; }

compose(){ if have docker && docker compose version >/dev/null 2>&1; then docker compose "$@"; else docker-compose "$@"; fi; }

# --------------------------------------------------------------------------- #
doctor(){
  echo -e "${B}RAG preflight — is this machine ready?${X}\n"
  local fail=0

  echo "Docker"
  if have docker && docker info >/dev/null 2>&1; then
    ok "docker installed and daemon running"
    local mem_bytes mem_gb
    mem_bytes=$(docker info --format '{{.MemTotal}}' 2>/dev/null || echo 0)
    mem_gb=$(( mem_bytes / 1024 / 1024 / 1024 ))
    if   [ "$mem_gb" -ge 12 ]; then ok "Docker memory: ${mem_gb}GB"
    elif [ "$mem_gb" -ge 8 ]; then warn "Docker memory: ${mem_gb}GB (ok for LEAN; raise to 12GB+ for full stack)"
    else bad "Docker memory: ${mem_gb}GB — RAISE to >=8GB (Docker Desktop → Settings → Resources)"; fail=1; fi
  else
    bad "docker not installed or daemon not running (start Docker Desktop)"; fail=1
  fi

  echo "Disk"
  local free_gb
  free_gb=$(df -g . 2>/dev/null | awk 'NR==2{print $4}' || echo "?")
  if [ "$free_gb" = "?" ] || [ "$free_gb" -ge 15 ] 2>/dev/null; then ok "free disk: ${free_gb}GB (need ~10GB: images + ~5GB BGE weights)"
  else warn "free disk: ${free_gb}GB — BGE weights alone are ~5GB, images add more"; fi

  echo "Python (for verify)"
  if have python3; then
    ok "python3: $(python3 --version 2>&1 | awk '{print $2}')"
    for m in httpx boto3; do
      if python3 -c "import $m" 2>/dev/null; then ok "python module '$m'"
      else warn "python module '$m' missing → pip install $m"; fi
    done
  else bad "python3 not found"; fail=1; fi

  echo "Ports free (nothing should be listening yet)"
  for p in 8000 6333 8333 8001; do
    if lsof -nP -iTCP:"$p" -sTCP:LISTEN >/dev/null 2>&1; then warn "port $p in use (a container may already be up, or another app)"
    else ok "port $p free"; fi
  done

  echo "LLM (optional — only needed for generate=true)"
  if have ollama; then
    ok "ollama installed"
    if curl -sf http://localhost:11434/api/tags >/dev/null 2>&1; then
      ok "ollama serving on :11434"
      if ollama list 2>/dev/null | grep -q "gemma2:2b"; then ok "model gemma2:2b pulled"
      else warn "gemma2:2b not pulled → ollama pull gemma2:2b"; fi
    else warn "ollama not serving → run 'ollama serve' (generation will be skipped otherwise)"; fi
  else warn "ollama not installed → brew install ollama (optional; retrieval works without it)"; fi

  echo
  if [ "$fail" -eq 0 ]; then echo -e "${G}Ready.${X} Run: ./scripts/rag.sh up"
  else echo -e "${R}Not ready — fix the ✗ items above.${X}"; return 1; fi
}

# --------------------------------------------------------------------------- #
wait_models(){
  echo "Waiting for BGE weights to load (first run downloads ~5GB)…"
  for _ in $(seq 1 180); do   # up to ~30 min at 10s
    if curl -sf "$INFER/health" 2>/dev/null | grep -q '"models_loaded":true'; then
      ok "rag-inference models loaded"; return 0
    fi
    sleep 10; printf "."
  done
  echo; bad "models still not loaded — check: ./scripts/rag.sh logs"; return 1
}

up(){ echo "Starting LEAN stack: $LEAN_SERVICES"; compose up -d $LEAN_SERVICES; echo; wait_models; }
up_full(){ echo "Starting FULL stack + RAG"; compose --profile rag up -d; echo; wait_models; }
down(){ compose stop $LEAN_SERVICES; ok "RAG services stopped"; }
logs(){ compose logs -f rag-inference; }

ingest(){
  local f="${1:?usage: rag.sh ingest <file>}"
  [ -f "$f" ] || { bad "no such file: $f"; exit 1; }
  echo "Uploading $(basename "$f") …"
  curl -sS -X POST "$BACKEND/api/v1/rag/ingest" \
    -H "Authorization: Bearer $TOKEN" -F "file=@$f" | python3 -m json.tool
  echo "Ingestion is async: poll GET $BACKEND/api/v1/rag/documents/{doc_id}/status until it reaches indexed/skipped/failed."
}

query(){
  local q="${1:?usage: rag.sh query \"your question\"}"
  local gen="${2:-false}"   # pass 'true' to use the LLM
  curl -sS -X POST "$BACKEND/api/v1/rag/query" \
    -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
    -d "{\"query\": $(python3 -c "import json,sys;print(json.dumps(sys.argv[1]))" "$q"), \"generate\": $gen}" \
    | python3 -m json.tool
}

verify(){ python3 scripts/verify_rag_e2e.py; }

# --------------------------------------------------------------------------- #
case "${1:-}" in
  doctor)   doctor ;;
  up)       up ;;
  up-full)  up_full ;;
  down)     down ;;
  logs)     logs ;;
  ingest)   shift; ingest "$@" ;;
  query)    shift; query "$@" ;;
  verify)   verify ;;
  *) echo "usage: $0 {doctor|up|up-full|down|logs|ingest FILE|query \"text\" [true]|verify}"; exit 1 ;;
esac

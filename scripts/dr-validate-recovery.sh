#!/bin/bash
# dr-validate-recovery.sh - Post-recovery data validation for OmniusGrid
#
# READ-ONLY: runs health checks and SELECT queries only. It never writes,
# updates, or deletes data, so it is safe to run at any time after a recovery
# (TimescaleDB failover, Redpanda recovery, backend restart, rollback, etc.).
#
# Usage:
#   ./scripts/dr-validate-recovery.sh                         # Docker Compose (default)
#   ./scripts/dr-validate-recovery.sh --target k8s --namespace omniusgrid
#
# Environment overrides:
#   DB_CONTAINER   (compose) TimescaleDB container name   [omniusgrid-timescaledb]
#   DB_USER        Postgres user                          [omniusgrid]
#   DB_NAME        Postgres database                      [omniusgrid]
#   HEALTH_URL     Backend readiness URL                  [http://localhost:8002/health/ready]
#   RPO_MINUTES    Max acceptable telemetry gap (minutes) [15]

set -uo pipefail

# ---- Configuration ----------------------------------------------------------
TARGET="compose"
NAMESPACE="omniusgrid"
DB_CONTAINER="${DB_CONTAINER:-omniusgrid-timescaledb}"
DB_USER="${DB_USER:-omniusgrid}"
DB_NAME="${DB_NAME:-omniusgrid}"
HEALTH_URL="${HEALTH_URL:-http://localhost:8002/health/ready}"
RPO_MINUTES="${RPO_MINUTES:-15}"
DB_POD_SELECTOR="${DB_POD_SELECTOR:-app=timescaledb}"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --target) TARGET="$2"; shift 2 ;;
        --namespace) NAMESPACE="$2"; shift 2 ;;
        --health-url) HEALTH_URL="$2"; shift 2 ;;
        --rpo-minutes) RPO_MINUTES="$2"; shift 2 ;;
        -h|--help)
            sed -n '2,/^set /p' "$0" | grep '^#' | sed 's/^# \{0,1\}//'
            exit 0 ;;
        *) echo "Unknown option: $1" >&2; exit 2 ;;
    esac
done

# ---- Output helpers ---------------------------------------------------------
# Only emit ANSI color when stdout is a terminal (keeps piped/CI output clean).
if [[ -t 1 ]]; then
    RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
else
    RED=''; GREEN=''; YELLOW=''; NC=''
fi
PASS=0; FAIL=0; WARN=0
DB_UP=0

pass() { echo -e "${GREEN}[PASS]${NC} $1"; PASS=$((PASS+1)); }
fail() { echo -e "${RED}[FAIL]${NC} $1"; FAIL=$((FAIL+1)); }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; WARN=$((WARN+1)); }
info() { echo -e "  $1"; }

# ---- DB query wrapper (read-only) -------------------------------------------
# Echoes a single scalar result, or empty string on error.
db_query() {
    local sql="$1"
    if [[ "$TARGET" == "k8s" ]]; then
        local pod
        pod=$(kubectl get pods -n "$NAMESPACE" -l "$DB_POD_SELECTOR" \
              -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)
        [[ -z "$pod" ]] && return 1
        kubectl exec -n "$NAMESPACE" "$pod" -- \
            psql -U "$DB_USER" -d "$DB_NAME" -tAc "$sql" 2>/dev/null
    else
        docker exec "$DB_CONTAINER" \
            psql -U "$DB_USER" -d "$DB_NAME" -tAc "$sql" 2>/dev/null
    fi
}

echo "==================================================================="
echo " OmniusGrid Post-Recovery Validation  (target: $TARGET)"
echo " $(date +'%Y-%m-%d %H:%M:%S %Z')"
echo "==================================================================="

# ---- 1. Database connectivity ----------------------------------------------
echo; echo "1. Database connectivity"
if [[ "$(db_query 'SELECT 1;')" == "1" ]]; then
    pass "Database reachable and accepting queries"
    DB_UP=1
else
    fail "Cannot query database (container/pod down or credentials wrong)"
fi

# DB-dependent checks (2-5) only run when connectivity succeeded.
if [[ "$DB_UP" -eq 1 ]]; then
    # ---- 2. Critical table row counts --------------------------------------
    echo; echo "2. Critical table row counts (expect > 0 on a seeded system)"
    for table in organizations assets alarms; do
        count=$(db_query "SELECT COUNT(*) FROM $table;")
        if [[ -z "$count" ]]; then
            fail "$table: query failed (table missing?)"
        elif [[ "$count" -gt 0 ]]; then
            pass "$table: $count rows"
        else
            warn "$table: 0 rows (expected on a fresh/empty deployment only)"
        fi
    done

    # ---- 3. Telemetry recency (RPO confirmation) ---------------------------
    echo; echo "3. Telemetry recency (RPO target: ${RPO_MINUTES} min)"
    gap_seconds=$(db_query "SELECT COALESCE(EXTRACT(EPOCH FROM (NOW() - MAX(time)))::bigint, -1) FROM telemetry;")
    if [[ -z "$gap_seconds" ]]; then
        warn "Could not read telemetry table (may not exist yet)"
    elif [[ "$gap_seconds" -lt 0 ]]; then
        warn "No telemetry rows present (empty deployment or no ingestion yet)"
    else
        gap_minutes=$(( gap_seconds / 60 ))
        if [[ "$gap_minutes" -le "$RPO_MINUTES" ]]; then
            pass "Latest telemetry is ${gap_minutes} min old (within RPO)"
        else
            fail "Latest telemetry is ${gap_minutes} min old (exceeds ${RPO_MINUTES} min RPO)"
        fi
    fi

    # ---- 4. Replication lag (TimescaleDB standby) --------------------------
    echo; echo "4. Replication lag (if this node is a standby)"
    in_recovery=$(db_query "SELECT pg_is_in_recovery();")
    if [[ "$in_recovery" == "t" ]]; then
        lag=$(db_query "SELECT COALESCE(EXTRACT(EPOCH FROM (NOW() - pg_last_xact_replay_timestamp()))::bigint, 0);")
        if [[ -n "$lag" && "$lag" -le 300 ]]; then
            pass "Replication lag ${lag}s (within 5 min)"
        else
            warn "Replication lag ${lag}s (review before promoting/closing incident)"
        fi
    else
        info "Node is primary (not in recovery) - replication lag check skipped"
    fi

    # ---- 5. Continuous aggregates ------------------------------------------
    echo; echo "5. TimescaleDB continuous aggregates"
    cagg_count=$(db_query "SELECT COUNT(*) FROM timescaledb_information.continuous_aggregates;")
    if [[ -z "$cagg_count" ]]; then
        info "Continuous aggregate info unavailable (extension/view not present)"
    elif [[ "$cagg_count" -gt 0 ]]; then
        pass "$cagg_count continuous aggregate(s) present"
    else
        info "No continuous aggregates defined"
    fi
else
    echo; echo "2-5. DB-dependent checks skipped (database unreachable)"
fi

# ---- 6. Backend readiness ---------------------------------------------------
echo; echo "6. Backend readiness ($HEALTH_URL)"
if command -v curl >/dev/null 2>&1; then
    code=$(curl -s -o /tmp/dr_health.json -w '%{http_code}' "$HEALTH_URL" 2>/dev/null)
    [[ -z "$code" ]] && code="000"
    if [[ "$code" == "200" ]]; then
        pass "Backend /health/ready returned 200"
        if command -v jq >/dev/null 2>&1; then
            # /health/ready returns checks as string values, e.g. {"database":"ok"}
            jq -r '.checks // {} | to_entries[] | "    - \(.key): \(.value)"' \
                /tmp/dr_health.json 2>/dev/null || true
        fi
    else
        fail "Backend readiness returned HTTP $code"
    fi
    rm -f /tmp/dr_health.json
else
    warn "curl not available - skipping backend health check"
fi

# ---- Summary ----------------------------------------------------------------
echo
echo "==================================================================="
echo -e " Result: ${GREEN}${PASS} passed${NC}, ${YELLOW}${WARN} warnings${NC}, ${RED}${FAIL} failed${NC}"
echo "==================================================================="

if [[ "$FAIL" -gt 0 ]]; then
    echo "Recovery NOT verified - investigate failed checks above."
    exit 1
fi
echo "Recovery checks passed. Complete the RTO/RPO checklist before closing the incident."
exit 0

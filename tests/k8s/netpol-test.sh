#!/usr/bin/env bash
# NetworkPolicy ENFORCEMENT test (matrix-driven).
#
# k8s-smoke runs on kind's default CNI (kindnet), which ignores NetworkPolicies:
# it proves they parse and apply, never that they work. This runs against Calico,
# where policy is enforced, and asserts real connectivity for each finding from
# infrastructure/k8s/NETWORK_SECURITY.md.
#
# Each ALLOW case guards a path the platform needs. Each DENY case proves the
# policies actually deny — without them a cluster with no enforcement at all
# would pass every ALLOW assertion and the suite would be worthless.
set -euo pipefail

TIMEOUT="${CONNECT_TIMEOUT:-5}"
NS=omniusgrid

# name | client-ns | client-pod | server-pod | port | expect | rationale
MATRIX=(
  "export->s3|omniusgrid|np-export-client|np-seaweedfs-stub|8333|ALLOW|S3 export upload path (finding #1)"
  "backend->s3|omniusgrid|np-backend-client|np-seaweedfs-stub|8333|ALLOW|S3 export download path (finding #1)"
  "ingestion->s3|omniusgrid|np-ingestion-client|np-seaweedfs-stub|8333|DENY|no rule grants this; proves enforcement is real"
  "cnpg->s3|omniusgrid|np-cnpg-stub|np-seaweedfs-stub|8333|ALLOW|CNPG WAL archiving to object store (finding #5)"
  "backend->cnpg|omniusgrid|np-backend-client|np-cnpg-stub|5432|ALLOW|app -> HA database (finding #5)"
  "export->redpanda|omniusgrid|np-export-client|np-redpanda-stub|9092|ALLOW|worker consumes its topic"
  "keda->redpanda|keda|np-keda-client|np-redpanda-stub|9092|ALLOW|KEDA reads consumer-group lag (finding #6)"
  "outsider->redpanda|netpol-outsider|np-outsider-client|np-redpanda-stub|9092|DENY|KEDA allowance must be namespace-scoped"
  "outsider->s3|netpol-outsider|np-outsider-client|np-seaweedfs-stub|8333|DENY|object store must not be namespace-open"
  "backend->redis|omniusgrid|np-backend-client|np-redis-stub|6379|ALLOW|rate limiting + idempotency + export job store (FS-196)"
  "export->redis|omniusgrid|np-export-client|np-redis-stub|6379|ALLOW|export job store"
  "outsider->redis|netpol-outsider|np-outsider-client|np-redis-stub|6379|DENY|cache must not be namespace-open"
  "prometheus->worker|omniusgrid|np-prometheus-client|np-worker-stub|9109|ALLOW|worker /metrics scrape (FS-213)"
  "outsider->worker|netpol-outsider|np-outsider-client|np-worker-stub|9109|DENY|worker metrics must not be namespace-open"
  "backend->otel|omniusgrid|np-backend-client|np-otel-stub|4317|ALLOW|API trace export (FS-226)"
  "ingestion->otel|omniusgrid|np-ingestion-client|np-otel-stub|4317|ALLOW|worker trace export (FS-226)"
  "otel->jaeger|omniusgrid|np-otel-client|np-jaeger-stub|4317|ALLOW|collector forwards spans to jaeger"
  "outsider->otel|netpol-outsider|np-outsider-client|np-otel-stub|4317|DENY|collector must not be namespace-open"
  "outsider->jaeger|netpol-outsider|np-outsider-client|np-jaeger-stub|4317|DENY|jaeger must not accept spans from anywhere"
)

fail() { echo "::error::$*"; exit 1; }

probe() { # <client-ns> <client-pod> <target-ip:port>
  kubectl -n "$1" exec "$2" -- \
    /agnhost connect --timeout="${TIMEOUT}s" --protocol=tcp "$3" >/dev/null 2>&1
}

echo "Waiting for probe pods..."
kubectl -n "$NS" wait --for=condition=Ready \
  pod/np-seaweedfs-stub pod/np-redpanda-stub pod/np-cnpg-stub pod/np-redis-stub pod/np-worker-stub pod/np-prometheus-client \
  pod/np-export-client pod/np-backend-client pod/np-ingestion-client --timeout=180s
kubectl -n keda wait --for=condition=Ready pod/np-keda-client --timeout=180s
kubectl -n netpol-outsider wait --for=condition=Ready pod/np-outsider-client --timeout=180s

# Resolve server pod IPs. Dialing the pod IP (not the Service name) isolates the
# NetworkPolicy verdict from DNS reachability, which is a separate rule.
declare -A IP
for p in np-seaweedfs-stub np-redpanda-stub np-cnpg-stub np-redis-stub np-worker-stub; do
  IP[$p]=$(kubectl -n "$NS" get pod "$p" -o jsonpath='{.status.podIP}')
  [ -n "${IP[$p]}" ] || fail "could not resolve pod IP for $p"
done

rc=0
pass=0
failed=0

for row in "${MATRIX[@]}"; do
  IFS='|' read -r name cns cpod spod port expect why <<< "$row"
  target="${IP[$spod]}:${port}"
  printf '%-22s %-5s ' "$name" "$expect"

  if [ "$expect" = "ALLOW" ]; then
    # Retry: Calico programs dataplane rules asynchronously after pod start.
    ok=1
    for _ in $(seq 1 6); do
      if probe "$cns" "$cpod" "$target"; then ok=0; break; fi
      sleep 5
    done
    if [ "$ok" -eq 0 ]; then
      echo "OK (reachable)"; pass=$((pass+1))
    else
      echo "FAILED (blocked, expected reachable)"
      echo "::error::${name}: ${why} — traffic is BLOCKED by NetworkPolicy."
      rc=1; failed=$((failed+1))
    fi
  else
    # Must stay blocked for the whole window; one success means reachable.
    blocked=0
    for _ in $(seq 1 3); do
      if probe "$cns" "$cpod" "$target"; then blocked=1; break; fi
    done
    if [ "$blocked" -eq 0 ]; then
      echo "OK (blocked)"; pass=$((pass+1))
    else
      echo "FAILED (reachable, expected blocked)"
      echo "::error::${name}: ${why} — traffic is ALLOWED but no policy grants it."
      echo "::error::Either a rule is over-broad, or policy is not being enforced at"
      echo "::error::all — in which case every ALLOW assertion here is vacuous."
      rc=1; failed=$((failed+1))
    fi
  fi
done

echo
echo "NetworkPolicy matrix: ${pass} passed, ${failed} failed, ${#MATRIX[@]} total"
[ "$rc" -eq 0 ] || fail "NetworkPolicy enforcement test failed."
echo "NetworkPolicy enforcement verified."

#!/usr/bin/env bash
# NetworkPolicy ENFORCEMENT test.
#
# The k8s-smoke job proves manifests apply; it cannot prove NetworkPolicies work,
# because kind's default CNI (kindnet) ignores them entirely. This runs against a
# Calico cluster where policy is actually enforced, and asserts real connectivity:
#
#   ALLOW  export-worker    -> seaweedfs:8333   (the S3 export-upload path)
#   DENY   ingestion-worker -> seaweedfs:8333   (not in any allow-list)
#
# The ALLOW case is the regression guard: the S3 object-store feature shipped with
# no matching egress rule, so under an enforcing CNI every export upload/download
# was silently denied. That bug would fail this test.
#
# The DENY case is the anti-vacuous guard: if policy were not enforced at all,
# everything would be reachable and the ALLOW case alone would still "pass".
set -euo pipefail

NS=omniusgrid
TIMEOUT="${CONNECT_TIMEOUT:-5}"

fail() { echo "::error::$*"; exit 1; }

# Dial $2:$3 from pod $1. Returns 0 if the TCP connect succeeded, non-zero if not.
# `agnhost connect` exits non-zero on refusal/timeout, which is exactly what a
# NetworkPolicy drop looks like from inside the pod.
probe() {
  local pod="$1" target="$2"
  kubectl -n "$NS" exec "$pod" -- \
    /agnhost connect --timeout="${TIMEOUT}s" --protocol=tcp "$target" >/dev/null 2>&1
}

echo "Waiting for probe pods to be Ready..."
kubectl -n "$NS" wait --for=condition=Ready pod/np-seaweedfs-stub \
  pod/np-export-client pod/np-ingestion-client --timeout=180s

# Resolve the stub's pod IP: the base `seaweedfs` Service is headless (clusterIP:
# None), so dialing the Service name depends on DNS being permitted too. Testing
# the pod IP isolates what we care about — the NetworkPolicy verdict.
STUB_IP=$(kubectl -n "$NS" get pod np-seaweedfs-stub -o jsonpath='{.status.podIP}')
[ -n "$STUB_IP" ] || fail "could not resolve np-seaweedfs-stub pod IP"
echo "SeaweedFS stub at ${STUB_IP}:8333"

rc=0

# --- ALLOW: export-worker -> seaweedfs:8333 --------------------------------
# Retry briefly: Calico programs dataplane rules asynchronously after pod start.
echo -n "ALLOW  export-worker -> seaweedfs:8333 ... "
allowed=1
for _ in $(seq 1 6); do
  if probe np-export-client "${STUB_IP}:8333"; then allowed=0; break; fi
  sleep 5
done
if [ "$allowed" -eq 0 ]; then
  echo "OK (reachable)"
else
  echo "FAILED"
  echo "::error::export-worker cannot reach seaweedfs:8333 — the S3 export/compliance"
  echo "::error::upload+download path is BLOCKED by NetworkPolicy. Check"
  echo "::error::allow-export-worker-egress and allow-seaweedfs-ingress in base/ingress.yaml."
  rc=1
fi

# --- DENY: ingestion-worker -> seaweedfs:8333 ------------------------------
# Must stay blocked for the whole window; a single success means it is reachable.
echo -n "DENY   ingestion-worker -> seaweedfs:8333 ... "
denied=0
for _ in $(seq 1 3); do
  if probe np-ingestion-client "${STUB_IP}:8333"; then denied=1; break; fi
done
if [ "$denied" -eq 0 ]; then
  echo "OK (blocked)"
else
  echo "FAILED"
  echo "::error::ingestion-worker CAN reach seaweedfs:8333 but no policy allows it."
  echo "::error::Either an over-broad rule was added, or NetworkPolicy is not being"
  echo "::error::enforced at all — in which case every other assertion here is vacuous."
  rc=1
fi

[ "$rc" -eq 0 ] && echo "NetworkPolicy enforcement verified." || fail "NetworkPolicy enforcement test failed."

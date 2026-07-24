# Network & pod-security model

## Model

The namespace runs **zero-trust**: `base/ingress.yaml` ships a `default-deny-all`
NetworkPolicy (`podSelector: {}`, `policyTypes: [Ingress, Egress]`) that denies
all pod traffic, and every workload gets a tightly-scoped allow-list for exactly
the destinations it dials and the sources that may reach it. All containers run
**non-root**, with a **read-only root filesystem** and **all Linux capabilities
dropped** (`securityContext` on every Deployment/StatefulSet; the exceptions are
the databases, which need a writable data dir).

## Audit of the enterprise stacks (this pass)

Adding the object store, monitoring, HA-DB and autoscaling stacks introduced
traffic that `default-deny-all` blocks. Findings and fixes:

| # | Finding | Fix |
|---|---------|-----|
| 1 | **Regression:** the export/compliance workers upload to `seaweedfs:8333` and the backend streams downloads from it (`EXPORT_USE_S3`), but their egress allow-lists never included SeaweedFS — so the whole S3 export/download path was denied under default-deny. | Added `seaweedfs:8333` egress to `backend`, `export-worker`, `compliance-reports-worker`. |
| 2 | SeaweedFS pod had no policy — unreachable + no DNS. | Added `allow-seaweedfs-ingress` (from backend/workers + CNPG on 8333) and `allow-seaweedfs-egress` (DNS). |
| 3 | Prometheus couldn't scrape `backend:8000` or `redpanda:9644` (their ingress lists didn't include it). | Added Prometheus to `allow-backend-ingress` and `allow-redpanda-ingress`. |
| 4 | The whole monitoring stack was denied under default-deny. | `monitoring/networkpolicies.yaml`: scoped ingress/egress for Prometheus, Alertmanager, kube-state-metrics, Grafana. |
| 5 | CNPG instance pods were denied (SQL clients, replication, exporter scrape, WAL archiving). | `database-ha/networkpolicies.yaml`: ingress from clients/pooler/peers/Prometheus, egress to peers + SeaweedFS/S3 + DNS + API. |
| 6 | **KEDA (in the `keda` namespace) couldn't reach `redpanda:9092`** to read consumer-group lag → every ScaledObject silently fails to scale. | Added the `keda` namespace to `allow-redpanda-ingress` on 9092. |

## CI coverage

| Job | CNI | What it proves |
|-----|-----|----------------|
| `k8s-manifests` | — | Every kustomization builds; policies are schema-valid |
| `k8s-smoke` | kindnet | Manifests apply to a real API server; operator CRs pass admission |
| `netpol-simulate` | — | The enforcement matrix evaluated against the policy YAML — same expectations as below, in seconds, no cluster |
| `k8s-netpol` | **Calico** | Policies are actually **enforced** — the matrix asserted with real TCP connections |

All four are blocking. `k8s-netpol` exists because finding #1 was invisible to
every other gate: the policies were valid and applied cleanly, they just denied
traffic the app needed. `netpol-simulate` is the fast feedback loop (a broken
path fails in ~20s instead of after a 5-minute kind+Calico spin-up); `k8s-netpol`
remains the source of truth, since only a real CNI can confirm the model.

### The enforcement matrix

| Case | Expect | Guards |
|------|--------|--------|
| `export-worker → seaweedfs:8333` | ALLOW | S3 export upload (finding #1) |
| `backend → seaweedfs:8333` | ALLOW | S3 export download (finding #1) |
| `cnpg → seaweedfs:8333` | ALLOW | WAL archiving to object store (finding #5) |
| `backend → cnpg:5432` | ALLOW | App → HA database (finding #5) |
| `export-worker → redpanda:9092` | ALLOW | Worker consumes its topic |
| `keda → redpanda:9092` | ALLOW | Consumer-group lag reads (finding #6), cross-namespace |
| `ingestion-worker → seaweedfs:8333` | DENY | No rule grants it — proves enforcement is real |
| `outsider-ns → redpanda:9092` | DENY | KEDA allowance is namespace-scoped, not allow-all |
| `outsider-ns → seaweedfs:8333` | DENY | Object store is not namespace-open |

The DENY cases are load-bearing: without them, a cluster with no policy
enforcement at all would satisfy every ALLOW assertion and the suite would be
worthless.

**Probe pods must carry all three labels** (`name` + `part-of` + `managed-by`) —
kustomize's `commonLabels` bakes `part-of`/`managed-by` into every generated
podSelector, so a probe missing one would not be selected by the real policy and
its assertion would be vacuous. The same trap applies to the CNPG pods: the
operator creates them at runtime, beyond kustomize's reach, so the Cluster
declares `spec.inheritedMetadata` to stamp those labels on. Drop that and the
CNPG policies select nothing — the database falls under `default-deny-all` with
no allow rules.

## Caveats operators must know

- **CNPG cutover egress — resolved.** The DB-client egress policies now list the
  CNPG cluster (`cnpg.io/cluster: omniusgrid-db`) alongside `timescaledb` on
  `:5432`, so repointing `DATABASE_URL` at `omniusgrid-db-rw` needs no policy
  edit. Before database-ha is deployed that selector simply matches nothing.
  (This was originally a documented manual step; the enforcement matrix flagged
  `backend → cnpg` as denied, so it was fixed at the source instead.)
- **Enforcement needs a real CNI.** kind's default `kindnet` **ignores**
  NetworkPolicies, so `k8s-smoke` validates them structurally but cannot prove
  they work. Staging/production must run an enforcing CNI (Calico / Cilium) for
  these to take effect at all.
- **kubelet health probes.** These policies follow the existing convention and do
  not special-case node-sourced liveness/readiness probes; verify probe traffic
  on your chosen CNI (most treat host→pod specially).

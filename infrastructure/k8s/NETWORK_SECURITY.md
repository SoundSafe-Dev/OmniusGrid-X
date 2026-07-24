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
| `k8s-manifests` | — | Every kustomization builds; policies are schema-valid (blocking) |
| `k8s-smoke` | kindnet | Manifests apply to a real API server; operator CRs pass admission (blocking) |
| `k8s-netpol` | **Calico** | Policies are actually **enforced** — asserts `export-worker → seaweedfs:8333` is reachable (the S3 path, finding #1) and `ingestion-worker → seaweedfs:8333` is blocked (proves enforcement is real, not vacuous) |

`k8s-netpol` exists because finding #1 was invisible to every other gate: the
policies were valid and applied cleanly, they just denied traffic the app needed.
Probe pods carry the real workload labels (including the `commonLabels`
`part-of`/`managed-by` that kustomize bakes into every podSelector) so the real
policies select them.

## Caveats operators must know

- **CNPG cutover egress.** The backend/worker egress policies open `:5432` to the
  `app.kubernetes.io/name: timescaledb` pod, **not** the CNPG pods
  (`cnpg.io/cluster`). When you repoint `DATABASE_URL` at `omniusgrid-db-rw`, add
  `cnpg.io/cluster` to those egress selectors — otherwise the app can't reach the
  HA database. Called out in `database-ha/README.md`.
- **Enforcement needs a real CNI.** kind's default `kindnet` **ignores**
  NetworkPolicies, so `k8s-smoke` validates them structurally but cannot prove
  they work. Staging/production must run an enforcing CNI (Calico / Cilium) for
  these to take effect at all.
- **kubelet health probes.** These policies follow the existing convention and do
  not special-case node-sourced liveness/readiness probes; verify probe traffic
  on your chosen CNI (most treat host→pod specially).

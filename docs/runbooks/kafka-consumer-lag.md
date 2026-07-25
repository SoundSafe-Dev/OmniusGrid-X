# Runbook: background workers & consumer lag

Covers the `opsgrid_workers` Prometheus alert group — `WorkerStalled`,
`WorkerDown`, `WorkerCrashLooping` — plus `IngestionLagHigh` /
`IngestionLagHighApp` from `opsgrid_data_quality` and `opsgrid_subsystems`.

## The four workers

Each runs as its own process (`python -m app.workers.<module>`), consumes a
Redpanda topic, and is deployed as a separate Deployment in Kubernetes and a
separate service in Compose.

| Worker | Module | Drains | Staleness window |
|--------|--------|--------|------------------|
| Ingestion | `app.workers.ingestion` | telemetry → TimescaleDB | **300s** |
| Export delivery | `app.workers.export_delivery` | scheduled exports → S3 + SMTP | disabled |
| Compliance reports | `app.workers.compliance_reports` | report generation → S3 + SMTP | disabled |
| OTA rollouts | `app.workers.ota_rollouts` | staged rollouts, health-gated rollback | disabled |

### Why staleness is only enabled on ingestion

All four serve `/metrics`, `/healthz` and `/readyz` on port **9109**
([`app/workers/health_server.py`](../../backend/app/workers/health_server.py)).
Liveness is **heartbeat-based**, not "the process exists": a worker calls `beat()`
per completed unit of work and `/healthz` fails once the last beat exceeds its
staleness window. That is what catches a wedged consumer — process alive, loop
dead, queue backing up — which a TCP or process check cannot see.

Ingestion carries continuous telemetry, so a 5-minute gap is genuinely wrong. The
other three are **event-driven and can idle for hours with nothing wrong**, so they
run with `stale_after_seconds=0` and keep readiness-only semantics. Enabling
staleness on them would restart healthy workers in a loop.

Consequently `WorkerStalled` is scoped to `worker="ingestion"`. That scoping is
asserted by a negative promtool test
([`tests/worker_alerts_test.yml`](../../infra/prometheus/tests/worker_alerts_test.yml)) —
a broken alert looks identical to a working one until it pages.

## Alerts

### WorkerStalled (critical)
> Ingestion's heartbeat is older than 10 minutes.

The liveness probe already restarts the pod at 300s. Reaching 600s means
**restarting is not curing it**: a crash loop, an unreachable broker, or a
consumer-group problem. The probe handles the transient case; this alert is for
when the probe's remedy has failed.

```bash
# 1. Is it actually restarting, or wedged and never killed?
kubectl -n omniusgrid get pods -l app.kubernetes.io/name=ingestion-worker
kubectl -n omniusgrid describe pod -l app.kubernetes.io/name=ingestion-worker | tail -30

# 2. What does the worker itself say?
kubectl -n omniusgrid port-forward deploy/ingestion-worker 9109:9109 &
curl -s localhost:9109/healthz | jq   # heartbeat_age_seconds vs stale_after_seconds
curl -s localhost:9109/readyz  | jq   # ready:false => never finished connecting

# 3. Logs from the run BEFORE the last restart — that is where the cause is.
kubectl -n omniusgrid logs deploy/ingestion-worker --previous --tail=200
```

Then, by what you found:

- **`ready: false`** — it never subscribed. Check Redpanda reachability and the
  NetworkPolicy — each worker has its own egress rule in `base/ingress.yaml`
  (`allow-ingestion-worker-egress`, `allow-export-worker-egress`,
  `allow-compliance-reports-worker-egress`, `allow-ota-rollout-worker-egress`) —
  then `REDPANDA_URL`.
- **`ready: true`, age climbing** — consuming stopped. Check consumer-group state
  (below) and for a poison message parked at the group offset.
- **Restart count climbing** — see `WorkerCrashLooping`.

```bash
# Consumer-group state and per-partition lag
kubectl -n omniusgrid exec -it redpanda-0 -- rpk group describe opsgrid-ingestion-workers
```

A single partition with growing lag while others are flat means one partition's
consumer is stuck — restart the pod owning it to force a rebalance.

### WorkerDown (high)
> Prometheus cannot scrape a worker's `/metrics`.

The process or its health server is gone. Distinct from `WorkerStalled`, which
requires a **reachable** worker reporting a stale heartbeat.

```bash
kubectl -n omniusgrid get pods -l app.kubernetes.io/component=worker
kubectl -n omniusgrid logs <pod> --previous --tail=100
```

If the pod is `Running` and `Ready` but still unscraped, the scrape path is the
problem, not the worker. **Both directions must permit it:**

- `allow-worker-metrics-ingress` (`base/ingress.yaml`) — prometheus → workers :9109
- `allow-prometheus-egress` (`monitoring/networkpolicies.yaml`) — must list :9109

Missing the egress port is a real regression this repo has hit: the ingress rule
alone is useless. `./tests/k8s/simulate-netpols.py` covers both and runs as a
blocking CI gate.

In Compose the job is static (`opsgrid-workers` in
[`infra/prometheus/prometheus.yml`](../../infra/prometheus/prometheus.yml)); in
Kubernetes the generic `kubernetes-pods` job discovers workers from their
`prometheus.io/*` pod annotations.

### WorkerCrashLooping (high)
> A worker container restarted more than twice in 30 minutes.

Its liveness probe keeps failing: the worker starts, wedges, gets killed, repeats.
This signal only exists because the workers have probes — before that, a wedged
worker sat at zero restarts forever.

```bash
kubectl -n omniusgrid logs <pod> --previous --tail=200
kubectl -n omniusgrid describe pod <pod> | grep -A5 'Last State'   # OOMKilled?
```

- **OOMKilled** — raise the memory limit on the Deployment (workers request
  256Mi / limit 512Mi).
- **Same exception each start** — a poison message at the group offset. Confirm
  with `rpk group describe`, then decide: fix the handler, or skip the offset
  (data loss — get sign-off).
- **Dependency unavailable at startup** — DB or broker. Fix the dependency; the
  restart loop is a symptom.

To stop the flapping while you investigate, scale to zero rather than deleting the
Deployment (KEDA will not fight a `replicas: 0` you set if you also pause the
ScaledObject):

```bash
kubectl -n omniusgrid annotate scaledobject <name> autoscaling.keda.sh/paused-replicas=0 --overwrite
```

### IngestionLagHigh / IngestionLagHighApp
> Consumer-group lag is high while the worker is otherwise healthy.

This is a **throughput** problem, not a stall — the worker is consuming, just not
fast enough. Check `WorkerAutoscalerAtMax` first: if the autoscaler is pinned at
its ceiling, raise `maxReplicaCount` **and** the topic's partition count (replicas
above partition count do nothing). See
[`autoscaling/README.md`](../../infrastructure/k8s/autoscaling/README.md#tuning).

## Compose

```bash
docker compose ps                          # workers now report healthy/unhealthy
docker compose logs --tail=200 ingestion-worker
curl -s localhost:9090/targets | grep -i worker   # via Prometheus
```

Worker healthchecks in Compose hit the same `/healthz`, so `docker compose ps`
distinguishes a wedged worker from a working one — it could not before FS-213.

## Escalation

| Condition | Responder | Escalate after |
|-----------|-----------|----------------|
| `WorkerStalled` on ingestion | On-call Data | 15 min |
| `WorkerDown` / `WorkerCrashLooping` | On-call Backend | 30 min |
| Lag high, workers healthy | On-call DevOps (capacity) | 60 min |

Telemetry already accepted by the API is durable in Redpanda, so a stalled
ingestion worker delays persistence rather than losing data — **as long as it is
recovered inside the topic's retention window.** Check retention before assuming
no loss:

```bash
# Ingestion subscribes by PATTERN (`^telemetry\..*`, `^state\..*`, `^alarms\..*`,
# plus `opsgrid.agent-status`), so there is no single "telemetry" topic — list them
# and describe the ones actually carrying the backlog.
kubectl -n omniusgrid exec -it redpanda-0 -- rpk topic list
kubectl -n omniusgrid exec -it redpanda-0 -- rpk topic describe telemetry.<site>
```

---

**Document Version:** 1.0
**Component:** Background workers — consumer lag & stalls

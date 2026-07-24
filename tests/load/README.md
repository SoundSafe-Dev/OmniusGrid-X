# Load testing

These drivers exist to validate the enterprise reliability layer **under
pressure** — that worker autoscaling (KEDA) actually scales on load, that the
HA database keeps up and fails over cleanly, and that the API/DB hold their SLOs.
They are operator-run tools against a deployed cluster, **not** CI gates (driving
KEDA needs a real cluster with the operator stacks applied; the advisory `k6`
job in CI is only a localhost smoke run).

Watch everything through the Grafana **"Platform / Infra"** dashboard
(`infrastructure/k8s/monitoring/`) while a test runs — it shows worker replicas
(current vs max), CNPG replication lag, and backup/health at a glance.

## 1. Ingestion load → ingestion-worker autoscaling + TimescaleDB writes

Ingestion is Kafka-driven (edge agents → Redpanda → ingestion worker → Timescale),
so this produces telemetry straight to the topics the worker consumes.

```bash
# from the backend venv (aiokafka is a backend dep)
backend/venv/bin/python tests/load/ingestion_load.py \
  --broker <redpanda-host>:9092 --rate 3000 --duration 300 \
  --org-id <seeded-org-uuid> --asset-ids <uuid1>,<uuid2>,...
```

- **`--rate` above what the workers can drain** builds consumer-group lag — that
  is the signal the KEDA ScaledObject scales on.
- Random asset UUIDs (omit `--asset-ids`) still drive lag/scaling; pass **real
  seeded** org/asset IDs to also validate the DB write path (otherwise rows
  dead-letter on the missing FK).

**Watch it scale:**
```bash
kubectl -n omniusgrid get hpa keda-hpa-ingestion-worker -w      # 2 -> up to 12
kubectl -n omniusgrid get pods -l app.kubernetes.io/name=ingestion-worker -w
```
Expected: replicas climb while lag is high, then settle back to the warm floor
(2) after the burst and `cooldownPeriod`. If lag keeps growing at max replicas,
`WorkerAutoscalerAtMax` fires — raise `maxReplicaCount` **and** the topic
partition count (a partition is read by only one consumer in a group).

## 2. API + DB read/write load → backend HPA + query latency

```bash
k6 run -e BASE_URL=https://<api-host> -e API_TOKEN=<jwt> tests/load/k6-load-test.js
```
Ramps to 1000 VUs across the read-heavy endpoints (assets, telemetry, alarms,
dashboard, kanban, registries) plus optional write flows. Thresholds: p95 < 500ms,
p99 < 1s, error rate < 1%. Validates the backend HPA (`overlays/production/hpa.yaml`,
5 → 20) and TimescaleDB read latency under concurrency.

## 3. Export path

- **On-demand async exports** (`GET /exports/telemetry/{asset_id}` over a wide
  date range > `SYNC_ROW_CAP` rows) run **in the API pod** via BackgroundTasks —
  they stress the DB streaming read + CSV generation + **S3 upload** (the
  cross-pod fix), but do NOT drive the export worker.
- **The export worker** (KEDA-scaled, consumes `opsgrid.exports`) is driven by
  **scheduled** exports. To load it, create N scheduled exports due now (via the
  API or a seeding SQL insert into `scheduled_exports`), then watch:
  ```bash
  kubectl -n omniusgrid get hpa keda-hpa-export-worker -w    # scales from 0
  ```
  `export-worker` (and `compliance-reports-worker`) scale to zero when idle, so
  the first run also validates cold-start scale-from-zero.

## 4. Database failover under load

The real HA test: fail the primary *while writes are in flight*.

```bash
# Terminal A: sustained ingestion (writes)
backend/venv/bin/python tests/load/ingestion_load.py --broker <host>:9092 --rate 2000 --duration 300 --org-id <uuid> --asset-ids <uuids>

# Terminal B: kill the primary, watch CloudNativePG promote a standby
kubectl -n omniusgrid cnpg status omniusgrid-db
kubectl -n omniusgrid delete pod <omniusgrid-db-primary>
kubectl -n omniusgrid get cluster omniusgrid-db -w
```
Expected: the operator promotes a standby and repoints the `-rw` Service within
seconds; writes resume with a brief blip. Confirm no committed data was lost
(synchronous replication) and that `CNPGReplicationLagHigh` did **not** linger.

## Interpreting results

| Signal | Where | Healthy |
|--------|-------|---------|
| ingestion-worker replicas | HPA / Grafana | rises with lag, returns to 2 |
| consumer-group lag | Grafana / `kafka` tooling | drains after the burst |
| CNPG replication lag | Grafana / `cnpg status` | < 30s throughout |
| API p95 / p99 | k6 summary | < 500ms / < 1s |
| backup age | Grafana | < 26h |

Tuning knobs: `infrastructure/k8s/autoscaling/README.md` (lagThreshold, max
replicas vs partitions) and `database-ha/README.md` (instances, sync replicas).

# RTO / RPO Verification Checklist

Use this checklist **after** completing any recovery, before declaring the incident
resolved. It confirms that recovery met its objectives and that no data was silently
lost.

- **RTO (Recovery Time Objective):** maximum acceptable time from failure to service restored.
- **RPO (Recovery Point Objective):** maximum acceptable amount of data loss, measured in time.

## Targets by scenario

| Scenario | RTO target | RPO target | Mechanism |
|----------|-----------|-----------|-----------|
| Backend API crash | 5 min | 0 min | Stateless restart |
| Application rollback | 10 min | 0 min | Image/revision rollback |
| Redpanda broker failure | 10 min | 0 min | Replication factor ≥ 3 |
| TimescaleDB primary failure | 15 min | 5 min | Patroni failover + WAL archiving |
| Network partition | 30 min | 15 min | Partition heal + resync |
| Data center outage | 60 min | 15 min | Cross-region replication + DNS failover |

## Step 1 — Record incident timing

Fill these in from monitoring/Alertmanager timestamps:

| Field | Value |
|-------|-------|
| Failure detected at | `[TIME]` |
| Recovery started at | `[TIME]` |
| Service restored at | `[TIME]` |
| **Measured RTO** (restored − detected) | `[DURATION]` |
| Last successful data write before failure | `[TIME]` |
| First successful data write after recovery | `[TIME]` |
| **Measured RPO** (data gap) | `[DURATION]` |

- [ ] Measured RTO ≤ target for the scenario
- [ ] Measured RPO ≤ target for the scenario

If either was **exceeded**, flag it in the post-incident report and open a
follow-up action.

## Step 2 — Service health verification

- [ ] Backend readiness: `curl -fsS http://localhost:8002/health/ready` returns 200
- [ ] All dependencies report `ok` or `skipped` in `/health/detailed`
- [ ] WebSocket accepts authenticated connections; the organization is derived from the token:
  `wscat -c "ws://localhost:8002/ws?token=$ACCESS_TOKEN"`
- [ ] All relevant alerts cleared in Alertmanager
- [ ] (k8s) All pods `Running` and `Ready`: `kubectl get pods -n omniusgrid`

```bash
curl -fsS -H "Authorization: Bearer $OPS_TOKEN" http://localhost:8002/health/detailed | jq .  # auth-gated
```

## Step 3 — Data integrity verification (RPO confirmation)

Run the read-only validation script — it automates the checks below:

```bash
./scripts/dr-validate-recovery.sh            # Docker Compose
./scripts/dr-validate-recovery.sh --target k8s --namespace omniusgrid
```

Manual equivalents if the script is unavailable:

- [ ] Critical tables have expected row counts (no unexpected drop):
  ```sql
  SELECT COUNT(*) FROM assets;
  SELECT COUNT(*) FROM alarms;
  SELECT COUNT(*) FROM organizations;
  ```
- [ ] Telemetry recency — latest data is within RPO window:
  ```sql
  SELECT MAX(time) AS latest, NOW() - MAX(time) AS gap FROM telemetry;
  ```
- [ ] No abnormal gap in recent telemetry:
  ```sql
  SELECT date_trunc('minute', time) AS minute, COUNT(*)
  FROM telemetry
  WHERE time > NOW() - INTERVAL '1 hour'
  GROUP BY 1 ORDER BY 1;
  ```
- [ ] (TimescaleDB failover) Replication lag is acceptable:
  ```sql
  SELECT NOW() - pg_last_xact_replay_timestamp() AS replication_lag;
  ```
- [ ] (TimescaleDB) Continuous aggregates current:
  ```sql
  SELECT view_name, completed_threshold
  FROM timescaledb_information.continuous_aggregates;
  ```
- [ ] (Redpanda) Consumer group lag draining toward 0:
  ```bash
  rpk group describe telemetry-consumer
  ```
- [ ] (Edge agents) Buffered messages draining (Prometheus):
  `opsgrid_edge_buffer_messages` trending down toward 0.

## Step 4 — Functional smoke test

- [ ] Login succeeds
- [ ] Asset list loads
- [ ] Latest telemetry returns for a known asset
- [ ] Kanban board loads
- [ ] A new telemetry point ingests end-to-end (edge/sim → DB → dashboard)

## Step 5 — Sign-off

| Field | Value |
|-------|-------|
| Incident ID | `[ID]` |
| Scenario / runbook used | `[RUNBOOK]` |
| RTO met? | `[YES/NO]` |
| RPO met? | `[YES/NO]` |
| Data loss (if any) | `[DESCRIPTION]` |
| Verified by | `[NAME]` |
| Verified at | `[TIME]` |

- [ ] Post-incident report filed
- [ ] Follow-up tickets opened for any exceeded objective
- [ ] Incident channel updated and customers notified of resolution
      (see [communication templates](incident-communication-templates.md))

---

**Document Version:** 1.0
**Component:** Disaster Recovery — RTO/RPO Verification

# RTO / RPO Verification Checklist

Use this checklist **after** completing any recovery, before declaring the incident
resolved. It confirms that recovery met its objectives and that no data was silently
lost.

- **RTO (Recovery Time Objective):** maximum acceptable time from failure to service restored.
- **RPO (Recovery Point Objective):** maximum acceptable amount of data loss, measured in time.

## Targets by scenario

> **CORRECTED 2026-08-20 (FS-799). Three of these rows named a mechanism that does not
> exist**, and the gap was roughly 100×: the table claimed an RPO of 5 minutes where the
> real figure is **up to 24 hours**.
>
> | claimed | mechanism named | reality |
> |---|---|---|
> | RPO 5 min | "Patroni failover + WAL archiving" | Patroni lives in `legacy-patroni/`, which **no kustomization applies**. No `archive_mode` or `archive_command` is set anywhere in `base/`, and the deployed image ships no `pgbackrest` binary |
> | RPO 15 min | "Cross-region replication + DNS failover" | `overlays/dr/kustomization.yaml` states in its own header that it **does NOT create cross-region data replication** |
> | RPO 15 min (partition) | "Partition heal + resync" | There is no resync mechanism; recovery is the same nightly dump |
>
> What actually runs is a nightly `pg_dump -Fc` to S3
> ([database-backup-restore.md](database-backup-restore.md)). **RPO is up to 24 hours for
> every database-loss scenario**, and RTO is *unmeasured* — the restore drill exists but
> has never been timed.
>
> These numbers are corrected here **before** the mechanisms are built, not after, because
> this table is where an SLA number gets quoted from. The target column below is what we are
> building toward; the **Actual today** column is what may be promised.
>
> **UPDATE 2026-08-20 (FS-800/801).** The mechanism now exists, and it distinguishes two
> RPOs the previous table conflated:
>
> | failure | RPO once the CNPG stack is applied | why |
> |---|---|---|
> | Primary instance lost | **≈ 0** | `minSyncReplicas: 1` — a standby has confirmed every acknowledged commit. Nothing is recovered from object storage at all |
> | Whole cluster / site lost | **≤ 5 minutes** | `archive_timeout: 5min` forces a WAL segment switch even when the segment is not full |
>
> `archive_timeout` is the parameter that actually bounds the second number, and it was
> **not set**. Postgres archives a WAL segment when it *fills* — 16 MB — so on a quiet
> system the tail of the log sat unarchived for as long as it took to produce 16 MB, which
> overnight can be many hours. WAL archiving existing is not the same as RPO being bounded.
>
> **This applies only where the CloudNativePG operator is installed and
> `infrastructure/k8s/platform/<env>/database-ha` has been applied.** The production overlay
> now includes the `cnpg-pooler` component so the application actually talks to that cluster
> (it previously did not, which meant WAL archiving would have faithfully archived a
> database nothing was writing to). Until an environment has been cut over, its RPO is still
> the nightly `pg_dump` — **up to 24 hours**.

| Scenario | RTO target | RPO target | **Actual today** | Mechanism today |
|----------|-----------|-----------|------------------|-----------------|
| Backend API crash | 5 min | 0 min | as stated | Stateless restart |
| Application rollback | 10 min | 0 min | as stated | Image/revision rollback |
| Redpanda broker failure | 10 min | 0 min | as stated *if* RF ≥ 3 | Replication factor ≥ 3 |
| TimescaleDB primary failure | 15 min | 5 min | **RTO: restore-path floor 0.75 s (FS-810), end-to-end untimed · RPO up to 24 h** | Restore last nightly `pg_dump` |
| Network partition | 30 min | 15 min | **RPO up to 24 h** if the database is lost | Partition heal; no resync exists |
| Data center outage | 60 min | 15 min | **RTO: restore-path floor 0.75 s (FS-810), end-to-end untimed · RPO up to 24 h** | Rebuild from the nightly dump; `overlays/dr` starts pods, not data |

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

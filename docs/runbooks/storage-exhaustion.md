# Runbook: storage exhaustion

Covers `PersistentVolumeFillingUp`, `PersistentVolumeCritical`,
`AuditLogTableGrowingUnbounded`, `AuditLogGrowthAccelerating`, and `DiskSpaceCritical` /
`HighMemoryUsage` from `opsgrid_critical`.

## Read this first

**None of these alerts existed before 2026-08-20, and neither did their inputs.**
`DiskSpaceCritical` (severity `critical`) and `HighMemoryUsage` read `node_*` while there was
no node-exporter in any environment; kube-state-metrics was scraped and **no rule used it**,
so nothing anywhere alerted on a filling volume. If you are reading this during an incident on
a cluster deployed before that date, check that `node-exporter` and the PVC rules are actually
present before trusting a quiet dashboard.

## Why this matters more than "a disk filled up"

The failure is circular and it ends on the `critical` tier:

```
audit_logs grows (no retention policy)  ->  volume fills  ->  the audit write fails
                                                          ->  AuditWriteFailing (critical)
```

The control that records what happened is the one that ends the system. The same loop runs
through telemetry: a full hypertable volume stops ingestion, the edge agents buffer, and
`EdgeBufferDropping` / `EdgeAgentDroppingTelemetry` follow once their local disks fill too.

**Do not free space by deleting audit rows.** See "What not to do" below — it is not a
judgement call.

## Detection

| Alert | Threshold | Meaning |
|---|---|---|
| `PersistentVolumeFillingUp` | > 85% for 15m | act today |
| `PersistentVolumeCritical` | > 95% for 5m | writes will begin failing shortly |
| `AuditLogTableGrowingUnbounded` | `audit_logs` > 20 GB | the table nothing prunes has a real deadline |
| `AuditLogGrowthAccelerating` | projected > 100 GB in 30 days | the deadline, before the volume |
| `DiskSpaceCritical` | node filesystem < 5% free | the node, not a PVC |

Which volume:

```bash
kubectl get pvc -n omniusgrid
kubectl exec -n omniusgrid <pod> -- df -h
```

What is consuming it — the same series the alerts read:

```promql
topk(10, pg_table_growth_total_bytes)
```

## Recovery, in order of preference

### 1. Expand the volume (preferred, no data loss)

If the StorageClass has `allowVolumeExpansion: true`:

```bash
kubectl patch pvc <name> -n omniusgrid -p '{"spec":{"resources":{"requests":{"storage":"200Gi"}}}}'
```

Most CSI drivers expand online. Some require a pod restart to grow the filesystem — check
`kubectl describe pvc <name>` for a `FileSystemResizePending` condition.

If the StorageClass does **not** allow expansion, that is the finding: record it and move to
step 2 for immediate relief.

### 2. Compress earlier (telemetry only, no data loss)

Telemetry compresses at 2 days and yields **7.3×** (measured: 142.7 → 19.4 bytes/row). If
chunks are sitting uncompressed, compressing them is the largest single win available and
loses nothing:

```sql
SELECT compress_chunk(c) FROM show_chunks('telemetry', older_than => INTERVAL '2 days') c
WHERE NOT (SELECT is_compressed FROM timescaledb_information.chunks
           WHERE chunk_schema || '.' || chunk_name = c::text);
```

### 3. Shorten a tenant's retention window (data loss, tenant-scoped, reversible only forward)

Raw telemetry retention is **per tenant** — `historian_retention_policies.hot_retention_days`,
default 90. Lowering it deletes that tenant's rows past the new window.

**This is a customer-affecting decision.** It deletes data the customer may be entitled to
under their contract, and it cannot be undone. Get an explicit decision, and record it in the
incident. Never lower the *default* to solve a single tenant's growth.

### 4. Emergency: stop the writer

If writes are already failing, stopping ingestion is better than a corrupt half-write:

```bash
kubectl scale deployment/prod-ingestion-worker -n omniusgrid --replicas=0
```

Edge agents buffer locally and backfill on reconnect — that is what the store-and-forward
buffer is for, and the conservation law (`produced == sent + buffered + dead_lettered +
dropped + expired`) holds across it. Watch `edge_buffer_messages` and restore the worker
before the agents' own disks fill.

## What not to do

**Do not `DELETE FROM audit_logs`.** Migration 069 makes each tenant's rows a hash chain, each
row hashing its predecessor's digest. Deleting the oldest rows leaves the earliest survivor's
`previous_hash` naming a row that no longer exists, and the verifier reports a **tamper
violation** — which, per FS-743, is indistinguishable from a control that never reports
anything, and will be ignored within a week. `audit_logs` has no retention policy *on purpose*;
see open decision #2 in [`open-decisions.md`](../engineering/open-decisions.md).

**Do not add a global `add_retention_policy` on `telemetry`.** A Timescale chunk holds rows for
many organisations, so dropping chunks deletes data belonging to tenants configured for longer
windows — silent, cross-tenant, irreversible. Migration 034 removed exactly that policy for
exactly this reason, and `test_compression_runs_before_retention_drops.py` blocks its return.

**Do not delete WAL.** It is what bounds RPO (`archive_timeout: 5min`). If WAL is filling the
volume, the archive is failing — fix the archive.

## Verification

```bash
kubectl get pvc -n omniusgrid          # usage back under 85%
```

```promql
pg_table_growth_total_bytes{table_name="audit_logs"}   # trending flat, not up
increase(opsgrid_audit_write_failed_total[10m])         # zero
```

Then confirm the edge buffers drained: `edge_buffer_messages` returning to baseline, and no
`EdgeBufferDropping` in the window.

## After the incident

- If expansion was not possible, that StorageClass is the finding (FS-820).
- If `audit_logs` drove it, the open decision has become urgent — it needs a WORM export and a
  retention window, in that order. It cannot be solved during an incident.
- Record the measured time-to-full so the forecast alert's threshold can be checked against
  reality.

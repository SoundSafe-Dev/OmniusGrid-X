# Runbook: a deploy wrote bad data

The release is out, it is running, and it has been writing wrong values. Rolling back the code
stops the bleeding and **does not undo the writes** — which is what makes this different from
every other deploy incident and why
[application-rollback.md](application-rollback.md) is only step one.

## The shape

Three things are true at once and they pull in different directions:

- the bad code is still writing, so **time is data**;
- the bad rows are interleaved with good ones from the same window, so a blanket restore loses
  legitimate work;
- the further back you restore, the more good data you discard.

Nothing here is reversible, so the ordering below is deliberate: **stop, then measure, then
decide.** The most expensive mistake is restoring before you know what you are restoring over.

## 1. Stop the writes

```bash
kubectl rollout undo deployment/prod-backend -n omniusgrid
kubectl rollout status deployment/prod-backend -n omniusgrid --timeout=600s
```

If the bad writer is a worker rather than the API, scale it to zero instead — the edge agents
buffer and backfill, and the conservation law (`produced == sent + buffered + dead_lettered +
dropped + expired`) holds across the gap:

```bash
kubectl scale deployment/prod-ingestion-worker -n omniusgrid --replicas=0
```

**Note the exact time you stopped it.** That timestamp is the upper bound of the damage window
and everything below depends on it.

## 2. Find the lower bound

The deploy time is the obvious answer and is usually wrong — the bad path may have needed a
particular request to trigger. Narrow it:

```bash
kubectl rollout history deployment/prod-backend -n omniusgrid
```

Then find the first bad row rather than assuming:

```sql
SELECT min(created_at), max(created_at), count(*)
FROM <table> WHERE <the condition that identifies a bad row>;
```

If you cannot write that condition, **stop and work it out before going further.** Every
option below needs it, and a restore performed without knowing what you are looking for cannot
be verified afterwards.

## 3. Choose the narrowest instrument that works

Ranked by how much good data they destroy. Prefer the top.

### a. Correct in place

If the bad rows are identifiable and the correct value is derivable, a targeted `UPDATE` is by
far the best outcome: no good data lost, no downtime, no restore.

Run it in a transaction and count first:

```sql
BEGIN;
SELECT count(*) FROM <table> WHERE <bad condition>;   -- does this match your estimate?
UPDATE <table> SET ... WHERE <bad condition>;
-- COMMIT only if the count matched
```

### b. Recompute

Derived data — OEE, aggregates, correlation output — can often be recomputed from raw
telemetry, which the bad deploy probably did not touch. Raw telemetry is retained **90 days**
per tenant by default (FS-816), so anything inside that window is reconstructible without a
restore at all.

### c. Point-in-time recovery to a side database

**Do not restore over production.** Recover to a *new* cluster at a timestamp just before the
lower bound, then copy the specific rows across:

```yaml
spec:
  bootstrap:
    recovery:
      source: omniusgrid-db
      recoveryTarget:
        targetTime: "<just before the first bad row>"
```

This gives you the old values as a queryable database beside the live one, so you can diff and
repair selectively rather than choosing between "all the bad data" and "all the good data".

⚠️ **PITR is not available in any environment yet** — no environment has been cut over to
CloudNativePG. See [database-backup-restore.md](database-backup-restore.md). What exists today
is the nightly `pg_dump`, so the equivalent move is restoring that dump into a scratch database
and diffing against it. The mechanism is proven; the deployment is not.

### d. Full restore

Last resort, and it is a data-loss decision, not a technical one: everything written between
the restore point and now is discarded — including legitimate work from other tenants who had
nothing to do with the bad deploy. **Get an explicit decision and record who made it.**

## 4. If tenants were affected differently

Almost always they were. One tenant's integration triggered the path; the rest are clean. A
full restore penalises all of them for one tenant's exposure, which is another reason (c) beats
(d) whenever it is available.

Scope it before deciding:

```sql
SELECT organization_id, count(*) FROM <table>
WHERE <bad condition> GROUP BY organization_id ORDER BY 2 DESC;
```

## Verification

- the bad condition returns zero rows;
- the row counts you expect to be unchanged **are** unchanged — check a table the bad path
  never touched, as a control;
- a fresh read through the API returns the corrected values, not just the database;
- `test_reporting_honesty.py` passes, because a repair that logs success for work it did not
  do is the same class of defect that caused this.

## After the incident

- **Why did nothing catch it?** A deploy that writes wrong values and stays green is a
  monitoring finding as much as a code one. If the wrong values were plausible, an alert on
  the *shape* of the data may be the real fix.
- If the correction needed data older than the retention window, that window is now a business
  decision with evidence attached (FS-816, open decision #2).
- Progressive delivery — canary with automated rollback on an SLO regression — is FS-826..828,
  and this incident is the argument for it.

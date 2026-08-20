# Runbook — database backup & restore

## What exists today

| | |
|---|---|
| **Mechanism** | Nightly logical backup (`pg_dump -Fc`) to S3 |
| **Manifest** | `infrastructure/k8s/base/db-backup-cronjob.yaml` (CronJob `db-backup`) |
| **Schedule** | 02:00 UTC daily, `concurrencyPolicy: Forbid` |
| **Location** | `s3://$BACKUP_S3_BUCKET/postgres/YYYY/MM/DD/HHMMSS.pgc`, SSE-AES256 |
| **RPO** | **Up to 24 h — no point-in-time recovery is available in any environment yet.** Every environment runs the legacy StatefulSet's nightly dump. The CNPG stack would give ≈0 for a lost primary and ≤5 min for a lost site, but that needs a cutover that has not happened; the mechanism is proven by `test_pitr_recovers_to_a_point_in_time_realdb.py` (FS-802..806) |
| **RTO** | **Floor measured 2026-08-20 (FS-810): 0.75 s** to restore a migrated schema in the drill. That is a floor, not the production figure — CI hardware, a near-empty database — but it is now measured on every run with a 120 s ceiling, so the restore path cannot silently become slow. The production number needs a game day against a real dump (FS-925); the documented target is 60 min for a full rebuild |
| **Verified by** | `backend/tests/test_backup_restore_drill.py`, in the blocking `backend-realdb` gate |

**There were no backups at all before this.** The only pgBackRest CronJob lives
in `infrastructure/k8s/legacy-patroni/`, which CI never applies, so every DR
runbook describing a pgBackRest restore was pointing at a repository nothing
wrote to. Treat any pgBackRest instructions in the `docs/deployment/dr-*.md`
runbooks as **not yet operational** — see "Point-in-time recovery" below, which
distinguishes a PITR mechanism that is proven in a drill but **not yet available** in any
environment from the legacy StatefulSet's nightly dump, which is what actually runs.

## Required secret

```bash
kubectl -n omniusgrid create secret generic backup-credentials \
  --from-literal=aws-access-key-id='<key>' \
  --from-literal=aws-secret-access-key='<secret>' \
  --from-literal=region='us-east-1' \
  --from-literal=bucket='opsgrid-backups'
```

### Bucket immutability — no longer an instruction (FS-811)

This used to read *"enable versioning + object lock so a compromised key cannot erase
history"*: one sentence describing the control that decides whether an attacker holding the
backup credentials can delete every backup you have. Nothing applied it and nothing checked
it, and that failure is invisible until somebody is actively destroying your data.

**Creating a bucket correctly:**

```sh
BACKUP_S3_BUCKET=opsgrid-backups AWS_DEFAULT_REGION=us-east-1 \
  infrastructure/k8s/base/scripts/bucket-immutability.sh bootstrap
```

Sets versioning, Object Lock in **COMPLIANCE** mode (35 days), the public-access block,
default encryption, and a lifecycle rule for retention — the upload job does not prune.

COMPLIANCE rather than GOVERNANCE is a real trade and worth understanding before you run it.
GOVERNANCE can be bypassed by a principal holding `s3:BypassGovernanceRetention`, which is
precisely the permission an attacker who has compromised the account grants themselves.
COMPLIANCE cannot be bypassed or shortened by anyone including the account root — which also
means **an object locked by mistake cannot be removed until its retention expires**, and you
pay to store it.

Object Lock is enabled *at bucket creation*. AWS has since allowed turning it on for an
existing versioned bucket, but support varies by account and region; creating a new bucket and
copying objects across is the path that always works.

**Checking a live bucket** is not something anyone has to remember. The
`backup-immutability-check` CronJob runs `verify` weekly with the credentials the cluster
already holds, and `BackupBucketNotImmutable` pages when it fails. To run it by hand:

```sh
BACKUP_S3_BUCKET=… AWS_DEFAULT_REGION=… \
  infrastructure/k8s/base/scripts/bucket-immutability.sh verify
```

It is read-only — every call is a `get-*`, so it cannot alter the bucket.

**Why it is a separate CronJob** rather than a step in the nightly backup: folding it in would
mean an unprotected bucket stops backups happening at all, turning a bad situation into a
worse one, and would stop `kube_cronjob_status_last_successful_time` advancing — firing
`DatabaseBackupStale` and telling an operator there are no backups when there are. Two
distinct problems, two distinct signals: `DatabaseBackupJobFailed` for *the backup did not
happen*, `BackupBucketNotImmutable` for *the backups exist and can be erased*.

## Restore

1. Pick the backup:
   ```sh
   aws s3 ls --recursive s3://$BACKUP_S3_BUCKET/postgres/ | tail -20
   ```
2. Scale the application down so nothing writes mid-restore:
   ```sh
   kubectl -n omniusgrid scale deploy/prod-backend deploy/prod-ingestion-worker \
     deploy/prod-export-worker deploy/prod-compliance-reports-worker --replicas=0
   ```
3. Restore into a **scratch** database first and diff it against expectations —
   never straight over the live one:
   ```sh
   aws s3 cp s3://$BACKUP_S3_BUCKET/postgres/<key>.pgc /tmp/restore.pgc
   createdb -h timescaledb -U omniusgrid restore_check
   pg_restore -h timescaledb -U omniusgrid -d restore_check --no-owner --no-acl /tmp/restore.pgc
   psql -h timescaledb -U omniusgrid -d restore_check -c 'SELECT max(version) FROM schema_migrations'
   ```
4. Promote: either point the app at `restore_check`, or restore over the live
   database with `--clean --if-exists` once you have confirmed the contents.
5. Scale back up and verify:
   ```sh
   curl -sf https://<host>/health && curl -sf https://<host>/api/v1/health/db
   ```
6. Record actual RTO/RPO in `docs/runbooks/rto-rpo-checklist.md`.

## Drill

`test_dump_restores_into_an_empty_database` runs the same `pg_dump -Fc` →
`pg_restore` round-trip against a migrations-built schema on every CI run and
compares row counts and `max(schema_migrations.version)`. It fails if the
restore produces nothing — verified by deleting the restore step and watching it
fail on `relation "schema_migrations" does not exist`.

It does **not** exercise S3, the CronJob's own scheduling, or the credentials.
Run a real end-to-end restore from an actual S3 object at least quarterly.

## Point-in-time recovery — proven in a drill, not yet available in any environment

**Status 2026-08-20 (FS-802..806): the mechanism is proven in a drill; PITR is NOT YET
available in any environment, because no environment has been cut over to CloudNativePG.**

Those are two different statements and the distinction is the whole section. What changed is
that point-in-time recovery is **not yet available** rather than undescribed: the mechanism
is now tested, and it requires a cutover that has not happened. During an incident today, on any running
environment, **you have the nightly logical dump and nothing else**: RPO up to 24 hours.

```bash
# Establish which database you are actually on before reading further.
kubectl get cluster.postgresql.cnpg.io -n omniusgrid   # present -> PITR would be available
kubectl get statefulset timescaledb -n omniusgrid      # present -> nightly dump only
```

### What the drill proves

`backend/tests/test_pitr_recovers_to_a_point_in_time_realdb.py` runs on every real-DB pass and
demonstrates recovery to a chosen instant against a real Postgres — base backup, continuous
WAL archiving, replay to a target time. It asserts the property that matters rather than "the
restore completed":

```
live database after a mistaken DELETE  ->  1 row  ("after the mistake")
recovered to a timestamp before it     ->  2 rows ("before", "also before")
```

The destroyed rows come back and the write made after the target does not. About 8 seconds.

**What it does not prove, stated so it is not read as more than it is.** It archives with `cp`
to a local directory, not barman to object storage, and it runs against a container rather
than the deployed stack. It establishes that the Postgres mechanics work and that our
understanding of them is correct. Restoring from a real S3 object is **FS-809, still
outstanding**. And a passing drill is not a deployed capability — see the status line above.

### What the CNPG cluster is configured to do, once it is what runs

Continuous WAL archiving to object storage, weekly base backups (`ScheduledBackup
omniusgrid-db-weekly`), and `archive_timeout: 5min` — the parameter that actually bounds the
number. Without it Postgres archives a segment only when it FILLS (16 MB), so on a quiet
system the tail of the log would sit unarchived for hours and the RPO would be unbounded
however good the rest of the configuration looked.

Two different figures, which the runbooks used to conflate — **both would apply only after a
cutover**:

| failure | RPO, post-cutover | why |
|---|---|---|
| the primary instance | ≈ 0 | `minSyncReplicas: 1` — a standby confirmed every acknowledged commit; the archive is not read at all |
| the whole cluster, or the site | ≤ 5 min | the archive is the only surviving copy, so the bound is `archive_timeout` |

Recovery would be a **new** Cluster bootstrapped from the backup, never an edit to the live
one:

```yaml
spec:
  bootstrap:
    recovery:
      source: omniusgrid-db
      recoveryTarget:
        targetTime: "2026-08-20 14:32:00+00"
```

The drill's second test asserts the cluster still declares all three prerequisites — WAL
archiving, a base-backup schedule, and `archive_timeout` — because any one going missing
leaves a repository that would recover nothing, silently.

### Until then: the legacy StatefulSet

`base/timescaledb-statefulset.yaml` is what every environment runs, and it has no WAL archive.
The route below was written for it and remains the only option there. It is superseded by
CNPG rather than wrong.

#### The pgBackRest route (superseded by CNPG)

Point-in-time recovery needs pgBackRest, which the deployed stack cannot
currently run: `timescale/timescaledb:latest-pg15` ships no `pgbackrest` binary
(verified by running the image) and no `archive_mode`/`archive_command` is
configured anywhere. `infra/pgbackrest/pgbackrest.conf` is now internally
consistent (stanza `opsgrid-db`, host `timescaledb`), so the remaining work is:

1. Move the StatefulSet to an image that ships pgBackRest (`timescale/
   timescaledb-ha:pg15`).
2. Set `archive_mode=on` and
   `archive_command = 'pgbackrest --stanza=opsgrid-db archive-push %p'`.
3. Mount `pgbackrest.conf` into the database pod and create the stanza
   (`pgbackrest --stanza=opsgrid-db stanza-create`).
4. Add the backup CronJob (weekly full + nightly differential) and extend the
   drill to restore to a timestamp.

Keep the logical backup running until that path has passed its own drill.

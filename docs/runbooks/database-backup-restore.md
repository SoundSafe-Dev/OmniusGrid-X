# Runbook — database backup & restore

## What exists today

| | |
|---|---|
| **Mechanism** | Nightly logical backup (`pg_dump -Fc`) to S3 |
| **Manifest** | `infrastructure/k8s/base/db-backup-cronjob.yaml` (CronJob `db-backup`) |
| **Schedule** | 02:00 UTC daily, `concurrencyPolicy: Forbid` |
| **Location** | `s3://$BACKUP_S3_BUCKET/postgres/YYYY/MM/DD/HHMMSS.pgc`, SSE-AES256 |
| **RPO** | Up to 24 h (no point-in-time recovery) |
| **RTO** | Restore time of one dump — measure it during the next drill |
| **Verified by** | `backend/tests/test_backup_restore_drill.py`, in the blocking `backend-realdb` gate |

**There were no backups at all before this.** The only pgBackRest CronJob lives
in `infrastructure/k8s/legacy-patroni/`, which CI never applies, so every DR
runbook describing a pgBackRest restore was pointing at a repository nothing
wrote to. Treat any pgBackRest instructions in the `docs/deployment/dr-*.md`
runbooks as **not yet operational** — see "Restoring PITR" below.

## Required secret

```bash
kubectl -n omniusgrid create secret generic backup-credentials \
  --from-literal=aws-access-key-id='<key>' \
  --from-literal=aws-secret-access-key='<secret>' \
  --from-literal=region='us-east-1' \
  --from-literal=bucket='opsgrid-backups'
```

Set a bucket lifecycle policy for retention (the job does not prune) and enable
versioning + object lock so a compromised key cannot erase history.

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

## Restoring PITR (not yet done)

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

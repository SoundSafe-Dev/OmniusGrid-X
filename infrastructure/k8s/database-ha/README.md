# High-availability database (CloudNativePG)

The base stack (`base/timescaledb-statefulset.yaml`) runs **one** TimescaleDB
pod: a node or disk failure is a full outage, and the only backup is a nightly
`pg_dump` (RPO up to 24h, no PITR). This directory replaces it with a 3-instance
[CloudNativePG](https://cloudnative-pg.io/) cluster:

- **Automatic failover** — the operator elects a new primary and repoints the
  `omniusgrid-db-rw` Service within seconds of a primary failure.
- **Synchronous replication** — every acknowledged commit is confirmed by at
  least one standby, so failover loses no committed data (RPO ≈ 0).
- **Point-in-time recovery** — continuous WAL archiving + base backups to S3
  (the PITR the `pg_dump` CronJob could not provide).
- **Connection pooling** — a PgBouncer `Pooler` (transaction mode) so the API +
  workers don't exhaust `max_connections`.

It supersedes both `base/timescaledb-statefulset.yaml` and the archived
`legacy-patroni/`.

## Prerequisites

1. **Install the CloudNativePG operator** (provides the `postgresql.cnpg.io`
   CRDs — `kustomize build` of this directory only produces the custom resources,
   it does not install the operator):

   ```bash
   kubectl apply --server-side -f \
     https://raw.githubusercontent.com/cloudnative-pg/cloudnative-pg/release-1.24/releases/cnpg-1.24.0.yaml
   ```

2. **A TimescaleDB-enabled image.** The stock CNPG image has no timescaledb
   extension. Build one (CNPG operand image + timescaledb) and push it to your
   registry, then set `spec.imageName` in `cluster.yaml`:

   ```Dockerfile
   FROM ghcr.io/cloudnative-pg/postgresql:15
   USER root
   RUN apt-get update && apt-get install -y postgresql-15-timescaledb && \
       rm -rf /var/lib/apt/lists/*
   USER 26
   ```

3. **Override the placeholder secrets** in `secrets.yaml` (app role password, S3
   backup keys). Keep the app role password in sync with the app's existing
   `database-credentials` Secret.

## Apply

```bash
kustomize build infrastructure/k8s/database-ha | kubectl apply -f -
```

CloudNativePG creates these Services automatically:

| Service                | Use                                             |
|------------------------|-------------------------------------------------|
| `omniusgrid-db-rw`     | read/write — always the current primary         |
| `omniusgrid-db-ro`     | read-only — standbys only (reporting/analytics) |
| `omniusgrid-db-r`      | any instance                                    |
| `omniusgrid-db-pooler-rw` | PgBouncer in front of `-rw`                  |

## Cutover from the single-node StatefulSet

1. Stop writers (scale backend + workers to 0).
2. `pg_dump` the old `timescaledb` StatefulSet and restore into the new cluster
   (or bootstrap CNPG directly from the old instance with a `bootstrap.pg_basebackup`
   / import — see CNPG "Importing an existing database").
3. Repoint the app: set `DATABASE_URL` host to `omniusgrid-db-pooler-rw` (or
   `omniusgrid-db-rw` without the pooler).
4. Remove `timescaledb-statefulset.yaml` from `base/kustomization.yaml`.
5. Scale writers back up; verify replication (`kubectl cnpg status omniusgrid-db`).

## Failover & recovery

- **Automatic:** kill the primary pod — the operator promotes a standby and
  updates `-rw` with no manual step. `kubectl cnpg status omniusgrid-db` shows
  the new topology.
- **Manual switchover** (e.g. to drain a node): `kubectl cnpg promote
  omniusgrid-db <instance>`.
- **PITR:** restore to a timestamp by creating a new `Cluster` with
  `bootstrap.recovery` pointing at the S3 backup and a `recoveryTarget`. See the
  runbook at `docs/runbooks/database-backup-restore.md`.

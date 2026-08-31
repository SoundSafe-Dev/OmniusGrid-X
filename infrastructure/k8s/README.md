# Kubernetes deployment (canonical stack)

This kustomize tree is the **canonical** Kubernetes deployment for OmniusGrid. Every
directory below has a `kustomization.yaml` and is built by CI:

| tree | what it is | applied by |
|---|---|---|
| `base/` | every workload, unprefixed, in `omniusgrid` | nothing directly — overlays reference it |
| `overlays/staging`, `overlays/production` | the app, image-pinned, `namePrefix`ed | the deploy jobs in `ci-cd.yml` |
| `overlays/dr` | the disaster-recovery site (FS-230) | **the runbook, not CI** — a DR site is cold, and continuously applying to it would defeat the point. Five gates build and validate it. |
| `monitoring/`, `autoscaling/`, `database-ha/` | the three operator stacks, deployed on their own lifecycle | nothing directly — see `platform/` |
| `platform/staging/monitoring`, `platform/staging/autoscaling`, `platform/staging/database-ha` | the three stacks with staging's namespace and scale targets (FS-509, FS-510) | the "Deploy platform stacks" step in the staging job |
| `platform/production/monitoring`, `platform/production/autoscaling`, `platform/production/database-ha` | the same, for production | the "Deploy platform stacks" step in the production job |
| `secrets/external-secrets`, `secrets/sealed-secrets` | two provisioning paths, one of which the operator picks | **the operator, per environment** — both need a real vault or a cluster keypair, so CI cannot apply either. `tests/k8s/check_every_secret_has_a_source.py` asserts every consumed Secret has a source in both. |
| `components/cnpg-pooler` | a kustomize **Component**, not a tree of its own: repoints all seven database clients — backend, four workers, migration Job, backup CronJob — at the CloudNativePG pooler (FS-801) | `overlays/production` includes it, so the production deploy performs the cutover. It replaced a manual "repoint DATABASE_URL" step in `database-ha/README.md`, and a manual step in a runbook is a step that gets skipped: the HA cluster would run, WAL archiving would work, and it would archive a database nothing was writing to. The deploy applies `database-ha` first, refuses without the operator's CRDs, and then refuses again if the data was never migrated (`tests/k8s/preflight_cnpg_cutover.py`). |
| `base/rag/` | the RAG stack — Qdrant, SeaweedFS, rag-inference — for its own `omniusgrid-rag` namespace. Deliberately standalone: **no kustomization references it**, including `base/kustomization.yaml`, so building `base/` does not build it. Whether it folds into the overlays is an open decision in that lane (`docs/rag_status_8.27.md`, item 3). Its three images run mutable tags, which `test_no_workload_runs_a_mutable_tag.py` exempts precisely because nothing deploys them — and that exemption fails automatically the moment any kustomization names this tree. The `rag-indexing-worker` itself is NOT here: it is an ordinary workload in `base/`. | nothing. Applied by hand into its own namespace, per that lane. |
| `cluster-scoped/` | the three `PriorityClass` tiers (FS-852). Deliberately outside `base/`: they are CLUSTER-scoped, and the overlays' `namePrefix` rewrites both the objects and every reference — so from base they became `prod-`/`staging-`/`dr-platform-critical`, nine cluster-wide objects for three tiers, with a staging pod outranking a production one on a shared cluster. `namePrefix` cannot tell a namespaced resource from a cluster-scoped one | **applied once per cluster, before the overlays that reference it** — `kubectl apply -k infrastructure/k8s/cluster-scoped` |
| `legacy-patroni/` | archived; in no kustomization and applied nowhere | nothing. Kept for reference only. |

`overlays/dr` was missing from this list for as long as it has existed, while the paragraph
above called the tree canonical and named `base/` and two overlays. A directory five CI gates
build, absent from the document that claims to describe all of them, is how an operator learns
the tree is not to be trusted. `tests/k8s/check_the_readme_describes_the_tree.py` now fails on
a buildable directory this table does not name.

The old hand-rolled manifests that lived in `infra/k8s/` (Patroni-based TimescaleDB, pgBackRest
CronJob) are archived under `legacy-patroni/` for reference; they are not
applied by CI and drift from the base names.

> **Database HA.** `base/` runs a **single** TimescaleDB pod — a node/disk loss
> is a full outage. `database-ha/` is the enterprise replacement: a 3-instance
> CloudNativePG cluster with automatic failover, synchronous replication (RPO≈0),
> continuous WAL archiving to S3 (point-in-time recovery — **not available on the
> deployed stack; see below**), and a PgBouncer pooler. It supersedes the archived
> `legacy-patroni/`. It is opt-in (needs the CloudNativePG operator and a
> TimescaleDB-enabled image) — see [`database-ha/README.md`](database-ha/README.md).
>
> **The cutover has not happened.** `base/` still ships the single-pod StatefulSet, and
> the deploy job applies `database-ha/` only where the CloudNativePG CRDs are already
> installed. So the PITR in the sentence above is a property of a stack nobody is running:
> what protects the deployed database is the nightly logical `pg_dump`, RPO up to 24 hours.
> `backend/tests/test_the_recovery_promise_matches_the_deployment.py` holds this paragraph
> and the runbooks to that, in both directions — the qualifier must go the day the cutover
> lands, because an under-promising runbook sends an operator to the slower recovery during
> an incident.

> **Backups.** Because `legacy-patroni/` is never applied, the pgBackRest
> CronJob living there meant staging and production had **no backups at all**,
> while the DR runbooks described restoring from a repository nothing wrote to.
> `base/db-backup-cronjob.yaml` is the working replacement: a nightly
> `pg_dump -Fc` to S3, verified by a restore drill in the blocking CI gate. It
> is *logical* — RPO is up to 24h and there is no PITR. Restoring PITR needs a
> database image that ships `pgbackrest` (`timescaledb-ha`) plus an
> `archive_command`; the current image has neither. See
> [`docs/runbooks/database-backup-restore.md`](../../docs/runbooks/database-backup-restore.md).

> **Monitoring stack.** In-cluster metrics/alerting live in `monitoring/`
> (Prometheus + Alertmanager + kube-state-metrics), deployed separately from the
> app base because it has its own lifecycle and pulls the canonical alert rules
> from `infra/prometheus/*.yml` (one source of truth shared with docker-compose):
>
> ```bash
> # Apply through the per-environment overlay, NOT the raw stack (FS-509):
> kustomize build --load-restrictor LoadRestrictionsNone \
>   infrastructure/k8s/platform/production/monitoring | kubectl apply -f -
> ```
>
> **Why the overlay.** `monitoring/`, `autoscaling/` and `database-ha/` each
> hardcode `namespace: omniusgrid`, and the staging deploy piped them into
> `kubectl apply -n omniusgrid-staging`. kubectl refuses an object whose embedded
> namespace disagrees with `-n` — and `-n` cannot override one, it can only supply
> one that is absent — so under `set -euo pipefail` the staging deploy failed at
> that line and staging never had any of the three applied. `platform/<env>/<stack>`
> declares the namespace per environment; `tests/k8s/check_namespaces_and_targets.py`
> holds every rendered object to it, checks that each KEDA `scaleTargetRef` names a
> workload the matching app overlay really deploys (they did not — the overlays add
> a `namePrefix` the autoscaling stack does not), and checks the deploy job still
> routes through the overlays.
>
> Prometheus discovers targets via the Kubernetes API (backend `/metrics`,
> Redpanda, kube-state-metrics, plus any pod annotated `prometheus.io/scrape`),
> evaluates the shared rules, and forwards firing alerts to Alertmanager, which
> routes by severity to PagerDuty/Slack. Override the placeholder
> `alertmanager-secrets` (Slack webhook, PagerDuty key) per environment. The
> otel-collector + Jaeger (tracing) remain in `base/`. This is the stack that
> makes backup-failure and migration-failure alerts actually fire.

> **Redis (FS-196).** `base/redis-statefulset.yaml` deploys Redis, which the
> platform hard-depends on for rate limiting, idempotency and the async export job
> store. It previously appeared ONLY as a NetworkPolicy destination — the policies
> permitted traffic to a Service that was never created. With Redis unreachable the
> always-on auth limiter raised on every `/auth` request, so login and register
> returned 500: an undeployed Redis meant a total authentication outage. The
> limiters now also degrade to per-process counters, but degraded is not deployed.

> **Worker autoscaling.** The base worker Deployments are fixed at `replicas: 1`.
> `autoscaling/` adds KEDA `ScaledObject`s that scale ingestion / export /
> compliance-reports workers on Redpanda consumer-group **lag** (export +
> compliance scale to zero when idle; ingestion keeps a warm floor). Opt-in —
> needs the KEDA operator. See [`autoscaling/README.md`](autoscaling/README.md).

> **Object storage.** Generated export/compliance artifacts go to SeaweedFS
> (`base/object-store.yaml`, S3-compatible) instead of a pod-local `emptyDir`:
> the worker writes on its pod and the backend API serves the download from
> another, so they must share one bucket. The backend and both workers set
> `EXPORT_USE_S3=true` and read the `s3-credentials` Secret — override its
> placeholder dev credentials per environment.

## Required external secrets (create BEFORE applying an overlay)

Secrets are intentionally **not** generated by kustomize — earlier
secretGenerators embedded credentials in git and didn't even produce the keys
the deployments read.

> **Production secrets:** for staging/production, provision these through a real
> mechanism instead of `kubectl create` — [`secrets/`](secrets/) ships both a
> **Sealed Secrets** path (encrypted, safe-in-git; `secrets/sealed-secrets/`) and
> an **External Secrets Operator** path (Vault / AWS SM / GCP SM;
> `secrets/external-secrets/`), covering every secret the platform expects. The
> placeholder Secrets in `base/object-store.yaml`, `monitoring/alertmanager.yaml`
> and `database-ha/secrets.yaml` are **dev/CI-only** — don't apply them to prod.

> **Required ConfigMap: `edge-agent-config`.** The edge agent's
> `ORGANIZATION_ID` is no longer defaulted in the manifest. It used to be
> hardcoded `dev-org`, which every real deployment would have inherited — and
> since the telemetry topic is `telemetry.{org}.{asset}`, a wrong org publishes
> into a tenant that does not exist and the data is silently lost. A missing key
> now stops the pod instead:
>
> ```bash
> kubectl -n omniusgrid create configmap edge-agent-config \
>   --from-literal=organization_id='<real org uuid>'
> ```
>
> `AGENT_ID` is derived from the pod name, so StatefulSet replicas get distinct
> identities automatically.

> **Placeholder credentials are enforced, not just documented.** `base/`,
> `monitoring/` and `database-ha/` ship dev placeholders so a throwaway cluster
> runs. Both overlays now `$patch: delete` the placeholder `s3-credentials`, and
> the platform-stack applies in `ci-cd.yml` pipe through
> `tests/k8s/strip_placeholder_secrets.py`. The blocking `k8s-manifests` gate runs
> `tests/k8s/check_placeholder_secrets.py`, which fails if a placeholder becomes
> reachable in staging or production **or** if the workflow stops piping through
> the stripper — a filter nobody calls is not enforcement.

For a quick throwaway cluster you can still create them by hand per namespace:

```bash
kubectl -n omniusgrid-staging create secret generic database-credentials \
  --from-literal=url='postgresql://omniusgrid:<password>@timescaledb:5432/omniusgrid'

kubectl -n omniusgrid-staging create secret generic jwt-secret \
  --from-literal=secret='<long random value>'

# signed report/export download links (export-worker + compliance-reports-worker)
kubectl -n omniusgrid-staging create secret generic signed-url-secret \
  --from-literal=secret='<long random value>'

# mTLS material for the edge gateway (see backend MTLS_ENABLED)
kubectl -n omniusgrid-staging create secret generic ca-certificate --from-file=ca.crt
kubectl -n omniusgrid-staging create secret tls backend-tls --cert=tls.crt --key=tls.key

# Nightly database backup (db-backup CronJob). WITHOUT THIS THERE ARE NO BACKUPS
# — the CronJob will fail every night. Set a bucket lifecycle policy for
# retention (the job does not prune) and enable versioning + object lock so a
# compromised key cannot erase history.
kubectl -n omniusgrid-staging create secret generic backup-credentials \
  --from-literal=aws-access-key-id='<key>' \
  --from-literal=aws-secret-access-key='<secret>' \
  --from-literal=region='us-east-1' \
  --from-literal=bucket='opsgrid-backups'
```

The `database-credentials` secret must carry `username`, `password` and
`database` in addition to `url`: the TimescaleDB StatefulSet and the backup
CronJob read the individual keys, while the app reads `url`.

Optional: a `smtp-credentials` secret (consumed via `envFrom`, `optional: true`
— absent means email delivery stays disabled) supplies `SMTP_HOST`,
`SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_FROM_EMAIL`,
`SMTP_USE_TLS`, `SMTP_START_TLS` and `COMPLIANCE_REPORT_EMAIL_ENABLED` to the
export and compliance-reports workers.

(Substitute `omniusgrid` for the production namespace. For GitOps, manage these
with SOPS or sealed-secrets rather than kubectl.)

## Deploying

```bash
kubectl apply -k infrastructure/k8s/overlays/staging
kubectl apply -k infrastructure/k8s/overlays/production
```

CI (`.github/workflows/ci-cd.yml`) pins image tags with `kustomize edit set
image` in the overlay before applying — the `images:` blocks in the
kustomizations are the single source of image names.

## Workers

Four single-replica worker Deployments run from the same backend image
(kustomize's `images:` transform re-tags them together with the API):

| Deployment | command |
| --- | --- |
| `ingestion-worker` | `python -m app.workers.ingestion` |
| `export-worker` | `python -m app.workers.export_delivery` |
| `compliance-reports-worker` | `python -m app.workers.compliance_reports` |
| `ota-rollout-worker` | `python -m app.workers.ota_rollouts` |

Workers expose no Service — nothing routes to them; edge ingest HTTP traffic
(`/api/v1/edge/ingest`) is served by the backend API, and the ingestion worker
only consumes from Redpanda.

Generated files go to SeaweedFS, not to a pod-local `emptyDir` — see **Object
storage** above. `export-worker`, `compliance-reports-worker` and the backend all set
`EXPORT_USE_S3=true` and share the `omniusgrid-exports` bucket, so a file written on a
worker pod is served by whichever API pod takes the download.

> This paragraph previously described the opposite, as a "known gap": workers writing to
> an `emptyDir` that the backend could not see, with "production needs a shared RWX PVC
> or object storage" as the remedy. That remedy had already been implemented — the
> manifests have set `EXPORT_USE_S3=true` on all three workloads for some time — but the
> stale text sat 110 lines below the paragraph that says so, and is the one an operator
> hunting for storage requirements reaches first. Corrected 2026-08-01 (FS-376).

## Redpanda broker TLS (FS-66)

The statefulset exposes an mTLS listener on 9094 (`require_client_auth` — the
agent's enrolled cert is the client cert) and mounts the `redpanda-broker-tls`
secret at /etc/redpanda/tls. Create it from certs issued by the edge CA:

```bash
cd backend && python scripts/issue_broker_cert.py \
  --cn redpanda --dns redpanda \
  --dns 'redpanda-0.redpanda.omniusgrid.svc.cluster.local' \
  --out-dir /tmp/broker-tls
kubectl -n omniusgrid create secret generic redpanda-broker-tls \
  --from-file=/tmp/broker-tls/broker.crt \
  --from-file=/tmp/broker-tls/broker.key \
  --from-file=/tmp/broker-tls/ca.crt
```

## Database migrations (db-migrate Job)

`base/migration-job.yaml` runs `python scripts/migrate.py --dir
/app/db-migrations` from the backend image. The migrations live at repo-root
`database/migrations`, which is baked into the image at `/app/db-migrations`
by `backend/Dockerfile` (compose prod bind-mounts the checkout instead; k8s
cannot) — that is why the backend image builds from the **repo root** context.

The TimescaleDB StatefulSet no longer mounts `docker-entrypoint-initdb.d`; the
Job owns the schema (initdb-built databases must be adopted with
`migrate.py --baseline` once — see the script header).

Jobs are immutable, so re-running migrations after the first apply requires
deleting the completed Job first:

```bash
kubectl -n omniusgrid-staging delete job staging-db-migrate --ignore-not-found
kubectl apply -k infrastructure/k8s/overlays/staging
kubectl -n omniusgrid-staging wait --for=condition=complete job/staging-db-migrate --timeout=300s
```

or clone the existing spec under a fresh name:

```bash
kubectl -n omniusgrid-staging create job --from=job/staging-db-migrate db-migrate-$(date +%s)
```

(Production: namespace `omniusgrid`, Job `prod-db-migrate`.) The Job also
self-cleans via `ttlSecondsAfterFinished: 86400`, so a next-day re-apply
usually just works. Note `--dir /app/db-migrations` is required — without it
migrate.py looks for a repo checkout that does not exist inside the container
and exits 1 on the empty dir.

## Production configuration contract

The backend fails fast at startup unless the production env is fully
configured — see `validate_settings` in `backend/app/core/config.py` for the
authoritative list (JWT secret, CORS allowlist, dev flags off, webhook + ERP
secrets, GEOTAB_SIMULATED=false, EDGE_REQUIRE_PROOF_OF_POSSESSION=true).

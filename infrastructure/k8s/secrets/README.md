# Secrets management

Several manifests in this repo ship **placeholder credentials** so that a local
/ CI cluster is runnable out of the box (`base/object-store.yaml`,
`monitoring/alertmanager.yaml`, `database-ha/secrets.yaml`). Those values are
**dev-only** and must never reach staging or production. This directory provides
the two supported ways to inject *real* secrets, so nothing sensitive is ever
committed in plaintext.

Pick one per environment:

| Mechanism | Secrets in git? | Needs | Use when |
|-----------|-----------------|-------|----------|
| **Sealed Secrets** (`sealed-secrets/`) | Yes — but **encrypted**, only the in-cluster controller can decrypt | the sealed-secrets controller | you want a self-contained GitOps flow with no external secret store |
| **External Secrets Operator** (`external-secrets/`) | **No** — only references | ESO + a backing store (Vault / AWS SM / GCP SM) | you already run a central secret store |

Both produce the **same** in-cluster `Secret` objects the workloads already
consume (`database-credentials`, `jwt-secret`, `signed-url-secret`,
`s3-credentials`, `alertmanager-secrets`, `cnpg-app-credentials`,
`cnpg-backup-credentials`, `backup-credentials`, `smtp-credentials`) — so no
Deployment/StatefulSet needs to change. You swap only *how* the Secret is
created.

## The secrets the platform expects

| Secret | Keys | Consumed by |
|--------|------|-------------|
| `database-credentials` | `url`, `username`, `password`, `database` | backend, all workers, migration Job, TimescaleDB |
| `jwt-secret` | `secret` | backend, workers |
| `signed-url-secret` | `secret` | backend, export + compliance workers |
| `s3-credentials` | `access-key`, `secret-key`, `s3config.json` | backend, export + compliance workers, SeaweedFS |
| `alertmanager-secrets` | `slack-webhook-url`, `pagerduty-service-key` | Alertmanager |
| `backup-credentials` | `aws-access-key-id`, `aws-secret-access-key`, `region`, `bucket` | db-backup CronJob |
| `smtp-credentials` | `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_FROM_EMAIL`, `SMTP_USE_TLS` | export + compliance workers (optional) |
| `cnpg-app-credentials` | `username`, `password` (type `kubernetes.io/basic-auth`) | CloudNativePG cluster (database-ha) |
| `cnpg-backup-credentials` | `ACCESS_KEY_ID`, `ACCESS_SECRET_KEY` | CloudNativePG WAL archiving (database-ha) |

## Policy

- **Never** commit a real secret value. The committed placeholders exist only to
  make `base/` + `monitoring/` apply on a throwaway cluster.
- Production overlays should NOT include the placeholder Secret manifests — apply
  `sealed-secrets/` or `external-secrets/` first, then the workloads.
- Rotate by re-sealing (Sealed Secrets) or rotating in the backing store (ESO);
  neither requires editing the workloads.

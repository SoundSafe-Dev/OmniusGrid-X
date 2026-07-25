# OmniusGrid Disaster Recovery Runbooks

Operational runbooks for detecting, recovering from, and verifying recovery of
OmniusGrid component failures. Start here during any incident.

> **First 60 seconds of an incident**
> 1. Open the matching runbook below.
> 2. Declare the incident and post in `#incident-response` (see
>    [communication templates](incident-communication-templates.md)).
> 3. Work the runbook's **Detection → Recovery → Verification** steps in order.
> 4. After recovery, run the [post-recovery validation](#post-recovery-validation)
>    and the [RTO/RPO checklist](rto-rpo-checklist.md).

## Runbook index

| Scenario | Runbook | Severity | RTO target | RPO target |
|----------|---------|----------|-----------|-----------|
| TimescaleDB primary failure (primary → standby promotion) | [dr-timescaledb-failure.md](../deployment/dr-timescaledb-failure.md) | Critical | 15 min | 5 min |
| Redpanda broker / cluster failure | [dr-redpanda-failure.md](../deployment/dr-redpanda-failure.md) | Critical | 10 min | 0 min |
| Backend API crash | [dr-backend-crash.md](../deployment/dr-backend-crash.md) | High | 5 min | 0 min |
| Network partition (split-brain) | [dr-network-partition.md](../deployment/dr-network-partition.md) | Critical | 30 min | 15 min |
| Full data center outage | [dr-datacenter-outage.md](../deployment/dr-datacenter-outage.md) | Critical | 60 min | 15 min |
| Application rollback (bad deploy) | [application-rollback.md](application-rollback.md) | High | 10 min | 0 min |

> **Note on TimescaleDB & Redpanda runbooks:** the failover (primary → standby
> promotion) and broker recovery/rebalance procedures already exist as the
> component runbooks linked above (`dr-timescaledb-failure.md`,
> `dr-redpanda-failure.md`). They were reviewed and are current as of 2026-06-02;
> rather than duplicate them, this index points to them. New work for this task is
> the rollback runbook, validation script, RTO/RPO checklist, and communication
> templates.

## Supporting documents

| Document | Purpose |
|----------|---------|
| [application-rollback.md](application-rollback.md) | Roll back a bad release on Docker Compose and Kubernetes |
| [rto-rpo-checklist.md](rto-rpo-checklist.md) | Verify recovery met its RTO/RPO targets before closing the incident |
| [incident-communication-templates.md](incident-communication-templates.md) | Copy-paste templates for internal, customer, and status-page comms |
| [compliance-tenant-data-cleanup.md](compliance-tenant-data-cleanup.md) | Review and resolve legacy compliance rows before enforcing tenant ownership |
| [leaked-key-rotation.md](leaked-key-rotation.md) | Rotate the private key committed in `acc35f92`; deferred history purge (**rotation outstanding**) |
| [kafka-consumer-lag.md](kafka-consumer-lag.md) | Background workers: stalled / down / crash-looping consumers and Redpanda consumer lag (`opsgrid_workers` alerts) |
| [database-backup-restore.md](database-backup-restore.md) | Nightly logical backup + restore procedure. **Read before trusting any pgBackRest instructions in `docs/deployment/dr-*.md` — that path is not yet operational.** |

## Post-recovery validation

After **any** recovery action, confirm data integrity and service health with the
validation script:

```bash
# Docker Compose deployment (default)
./scripts/dr-validate-recovery.sh

# Kubernetes deployment
./scripts/dr-validate-recovery.sh --target k8s --namespace omniusgrid
```

The script is **read-only** — it runs `SELECT` queries and health checks only, and
never mutates data. See [scripts/dr-validate-recovery.sh](../../scripts/dr-validate-recovery.sh).

## Recovery helper scripts

| Script | Scenario |
|--------|----------|
| [scripts/dr-timescaledb-recovery.sh](../../scripts/dr-timescaledb-recovery.sh) | TimescaleDB failover helper |
| [scripts/dr-redpanda-recovery.sh](../../scripts/dr-redpanda-recovery.sh) | Redpanda broker replacement |
| [scripts/dr-backend-recovery.sh](../../scripts/dr-backend-recovery.sh) | Backend pod restart |
| [scripts/dr-validate-recovery.sh](../../scripts/dr-validate-recovery.sh) | Post-recovery data validation (read-only) |
| [infra/scripts/disaster_recovery.sh](../../infra/scripts/disaster_recovery.sh) | pgBackRest backup / restore / PITR |

## Severity & escalation summary

| Severity | Examples | Initial responder | Escalate after |
|----------|----------|-------------------|----------------|
| Critical | DB down, Redpanda down, DC outage | On-call DevOps + DBA | 15 min |
| High | Backend down, bad deploy | On-call Backend | 10 min |
| Medium | Ingestion lag, asset offline | On-call Data | 30 min |

Each runbook contains its own detailed escalation matrix.

## Conventions used in these runbooks

- **Kubernetes namespace:** `omniusgrid`
- **Backend deployment:** `omniusgrid-backend` (container port `8000`)
- **pgBackRest stanza:** `opsgrid-db` (see `infra/pgbackrest/pgbackrest.conf`).
  Not to be confused with the Patroni **cluster** name `omniusgrid-db`, which is
  what `patronictl` commands in the DR runbooks take.
- **Local health base URL:** `http://localhost:8002` (Docker Compose), `http://localhost:8000` (in-cluster)
- Placeholders such as `[PHONE]`, `[EMAIL]`, `[TIME]` must be filled in before an
  incident — keep the on-call contact list current.

---

**Document Version:** 1.0
**Component:** Disaster Recovery — Runbook Index

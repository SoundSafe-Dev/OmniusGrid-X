# Uptime commitment

**Status: internal draft.** This is the engineering statement of what is measured and how.
It is the input to a contractual SLA, not the SLA itself — the credit schedule in §6 is a
proposal and needs a commercial owner before it is quoted to anyone.

Last measured: 2026-08-20.

---

## 1. The commitment

| | |
|---|---|
| **Availability** | **99.9%** of a rolling 28-day window |
| **Error budget** | 0.1% — **40 minutes 19 seconds** of unavailability per window |
| **RPO** (data loss ceiling) | **15 minutes** — target. **Currently 24 hours.** See §5 |
| **RTO** (restore ceiling) | **1 hour** — target. **Currently unmeasured.** See §5 |

Two of these four numbers are targets the system does not yet meet. They are written here
as targets rather than omitted because the gap is the point: an SLA quoting an RPO of 15
minutes against a nightly logical backup would be a contractual promise the architecture
cannot keep, and the difference is ~96× the stated exposure.

## 2. What "available" means

Availability is measured as **reachable × correctly-served**, sampled every 15 seconds:

```
availability = probe_success × (1 − 5xx_ratio)
```

- **`probe_success`** — a synthetic HTTP probe against the API's readiness endpoint, run by
  a blackbox exporter **in a separate process from the application**, from outside the
  cluster.
- **`5xx_ratio`** — the fraction of requests the application answered with a 5xx.

Both factors are necessary and neither is sufficient:

| | probe | 5xx ratio | availability |
|---|---|---|---|
| Healthy, serving traffic | 1 | 0 | 1.0 |
| Healthy, no traffic (3am) | 1 | 0 | 1.0 |
| Up, but failing every request | 1 | 1 | 0.0 |
| **Down entirely** | **0** | *(absent)* | **0.0** |
| Crash-looping, half the probes answered | 0.5 | 0 | 0.5 |

### Why the fourth row is stated so prominently

Until 2026-08-20, availability was computed from the 5xx ratio **alone** — a metric the
backend exports about itself. When the backend is down it does not report zero requests, it
reports nothing, and a ratio over an absent series produces no sample at all. Consequences,
measured with `promtool` and pinned in `infra/prometheus/tests/slo_outage_test.yml`:

- Neither burn-rate alert fired during a simulated 70-minute total outage, while both fired
  correctly for a backend that was up and returning 5xx to everything. **The alerting
  detected degradation and was blind to death.**
- A monthly figure computed by averaging skips absent samples, so the outage was not
  averaged in as zero — it was excluded from the window, and the month read ≈100%.

Any availability figure produced before 2026-08-20 should be treated as **unverifiable**,
and specifically as unable to reflect a full outage.

## 3. Where it is measured from

| Probe | Answers |
|---|---|
| External, through the public ingress | "Can a customer reach it" — includes DNS, TLS, ingress, and the app |
| In-cluster, against the Service | "Is the application alive" |

They disagree exactly when the ingress, DNS or certificate is the problem — the class no
in-process metric can see. **The external probe is the one the commitment is computed from.**

## 4. Exclusions

Time is excluded from the window only for:

1. **Announced maintenance**, notified at least 72 hours ahead and confined to a published
   window.
2. **Customer-caused** unavailability: exhausting a contractual quota, credentials revoked
   by the customer's own IdP, or a customer-supplied integration endpoint failing.
3. **Force majeure**, including a full region loss at the cloud provider — see the honesty
   note in §5, because the current architecture does not survive one.

Explicitly **not** excluded: deploys, migrations, scaling events, dependency failures,
certificate expiry, and any outage caused by our own change. Those consume error budget.
An SLA that excuses self-inflicted downtime measures nothing a customer cares about.

## 5. What the commitment does not yet rest on

Stated plainly, because a customer discovering these after signing is a worse outcome than
a customer declining to sign.

| Claim | Reality today | Tracked as |
|---|---|---|
| RPO 15 min | **Mechanism built 2026-08-20 (FS-800/801)**, not yet deployed. With the CNPG stack applied: **≈0** for a lost primary (synchronous replication) and **≤5 min** for a lost site (`archive_timeout: 5min` — the parameter that actually bounds it, and it was unset). The production overlay now points the application at that cluster's pooler, which it previously did not. **Until an environment is cut over its RPO is still the nightly `pg_dump` — up to 24 hours** | FS-799–806 |
| RTO 1 hour | Never measured. The restore drill skips silently without `testcontainers` | FS-808–810 |
| Regional resilience | Single region, single database instance in `base/`. No cross-region replication | FS-807, 855–859 |
| Backups are safe | Bucket versioning and object lock are documented as manual steps, so a compromised key can erase every backup | FS-811 |
| Telemetry is retained | **Corrected 2026-08-20.** This row said "dropped after 7 days", repeating `005_data_retention.sql:22` — a statement that is a **no-op**, because `001_init.sql:104` had already installed a 30-day policy and `if_not_exists => TRUE` does not change an existing interval. `034_historian_retention.sql:210` then removed the global policy altogether in favour of a per-tenant row DELETE. The real default was **30 days**, tenant-configurable; FS-816 raised it to **90** | FS-816 ✅ |
| Rollback | Rolling update only; images float on mutable tags, including the database engine and the broker, so "roll back to what was running" is unanswerable | FS-821–828 |

## 6. Credit schedule *(proposal — needs a commercial owner)*

| Monthly availability | Credit |
|---|---|
| < 99.9% and ≥ 99.5% | 10% |
| < 99.5% and ≥ 99.0% | 25% |
| < 99.0% | 50% |

Credits are proposed as a percentage of the monthly fee, requested by the customer within
30 days. **Nothing here has been reviewed by anyone commercial.**

## 7. Notification

| Severity | Customer notified within | Updates |
|---|---|---|
| Total unavailability | 30 minutes | Hourly |
| Degraded (elevated errors, major feature unavailable) | 2 hours | Every 4 hours |
| Data loss or exposure, any amount | 1 hour, and see below | Continuous |

Data-loss and data-exposure events additionally carry statutory deadlines that are shorter
than any of the above and are **not currently captured in any runbook**: GDPR Art. 33 (72
hours to the supervisory authority) and DFARS 252.204-7012 (72 hours to DoD). Closing that
is FS-829/831; the compliance catalogue records it as OG-IR-002.

## 8. How to verify any of this

| Question | Where |
|---|---|
| Current 28-day availability | `job:slo_availability:ratio28d` |
| Error budget remaining | `job:slo_error_budget_remaining:ratio28d` (1.0 untouched, 0.0 exhausted, negative = missed) |
| Minutes of downtime still affordable | `job:slo_error_budget_remaining:minutes28d` |
| Definitions | `infra/prometheus/slo_rules.yml` |
| Proof the instrument records an outage | `infra/prometheus/tests/slo_outage_test.yml` |
| Dashboard | Grafana → SLO overview |
| That the window is really 28 days | `--storage.tsdb.retention.time` on the Prometheus Deployment, against the longest `[...]` in `slo_rules.yml` — asserted by `test_the_retention_covers_the_slo_window.py` |

**Corrected 2026-08-31 (FS-859).** Everything above described a rolling 28-day window, and
until this date **Prometheus kept 15 days** (`--storage.tsdb.retention.time=15d` in
Kubernetes; no flag at all in compose, which is the same 15 by default). The number was
therefore computed over 28 days of which roughly half existed.

Prometheus does not fail on that. `avg_over_time` averages the samples present in the
window and ignores the absent ones, so the query returned a confident figure derived from
the most recent fortnight — and because the missing half is always the OLDEST, a bad start
to a month disappeared from its own budget. The error flattered.

Retention is now 35 days, with the volume grown to match, and the requirement is derived
from the rules rather than restated: widening a window without widening retention fails the
build. This is the same shape as the finding in §4 — an instrument that looked right and
was not — one layer further down, in the store rather than the expression.

If `ProbeSignalMissing` is firing, **no availability figure from that period is valid** —
the instrument was not reporting, which is a distinct state from the system being healthy
and must never be read as one.

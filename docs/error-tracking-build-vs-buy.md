# Error tracking: build vs. buy

A short decision record for why OpsGrid ships a small in-house error-triage v1
rather than adopting Sentry or GlitchTip outright today.

## The need

Before going public we had **no way to answer "what is our most common
production error this week?"** Unhandled exceptions became anonymous 500s and
disappeared. We needed grouping, counting, and a triage workflow.

## Options

| | In-house v1 (shipped) | Sentry (SaaS) | GlitchTip (self-hosted) |
| --- | --- | --- | --- |
| Cost | ~0 (uses existing Postgres/Grafana) | Per-event pricing, grows with volume | Infra + ops time |
| Setup | One migration + middleware | SDK + account | New service, DB, deploy |
| Data residency | Stays in our DB | Leaves our infra → **industrial clients object** | Stays in our infra |
| Grouping / dedupe | Yes (fingerprint) | Yes (best-in-class) | Yes |
| Triage workflow | Yes (open/ack/resolved + auto-reopen) | Yes | Yes |
| Release tracking, source maps, breadcrumbs | **No** | Yes | Partial |
| Alerting | Reuses our Prometheus/Alertmanager | Built-in | Built-in |
| Maintenance burden | We own the code | None | We own the service |

## Why build v1 now

1. **Data residency.** OpsGrid runs on industrial/OT customer sites whose
   operators are hostile to telemetry leaving their premises. Shipping error
   data to a third-party SaaS (Sentry) is a non-starter for those accounts, and
   it would contradict the GDPR work happening in parallel. Our v1 stores only
   scrubbed metadata in our own database.
2. **Cost & footprint.** v1 reuses infrastructure we already run (Postgres for
   storage, the existing Prometheus/Grafana/Alertmanager stack for metrics and
   alerts). No new service, no per-event bill.
3. **Speed to value.** It is one migration, one middleware, one admin page —
   small enough to land as a side project and immediately answer the question
   we could not answer before.

## What v1 deliberately does NOT do

Release health, source-map symbolication, breadcrumb trails, user-impact
estimation, cross-service distributed tracing. These are exactly where Sentry /
GlitchTip are worth their cost.

## Recommendation

Ship v1 now; it covers the 80% (group, count, rank, triage) at near-zero cost
and with zero data-residency risk. **Revisit at real client volume** — if we
find ourselves wanting release tracking or source maps, stand up **self-hosted
GlitchTip** (keeps data on our infra) before considering Sentry SaaS, which is
only viable for tenants that permit external telemetry.

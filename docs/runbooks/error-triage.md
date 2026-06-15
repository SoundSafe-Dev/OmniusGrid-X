# Runbook: API errors & Error Triage

This runbook covers the `opsgrid_api` Prometheus alert group and the Error
Triage admin feature (`/admin/errors`).

## What is Error Triage?

Unhandled exceptions (HTTP 500s) raised anywhere in the backend are caught by a
middleware, fingerprinted (so identical bugs collapse into one entry),
aggregated in-process, and flushed to the database. Admins view and triage them
at **`/admin/errors`**. Only metadata is stored — exception type, route
template, scrubbed message/traceback samples, and counts. No request bodies,
headers, query params, or user identity are ever captured.

Feature flags (both default **off**):

| Variable | Effect |
| --- | --- |
| `ERROR_TRACKING_ENABLED=true` | Turns on capture + the `/admin/errors` data + the `opsgrid_unhandled_exceptions_total` metric |
| `PROFILING_ENABLED=true` | Turns on the request/latency/DB metrics that power most of the Grafana **OpsGrid — API Overview** dashboard |

Dashboards and alerts depend on `PROFILING_ENABLED`; the exception-by-type panel
and `APIUnhandledExceptionSpike` alert additionally need `ERROR_TRACKING_ENABLED`.

## Alerts

### APIHighErrorRate (critical)
> 5% of requests are 5xx over 5 minutes.

1. Open **`/admin/errors`**, range = `24h`, sorted by Occurrences. The dominant
   fingerprint is almost always the cause.
2. Open its detail page — the scrubbed traceback points at the crash site. A
   `Regression ×N` badge means a previously *resolved* error has returned (check
   recent deploys).
3. Cross-check the Grafana **OpsGrid — API Overview** dashboard → *Request rate
   by status class* and *Top 10 endpoints by p95* to see whether it is one
   endpoint or systemic.
4. Mitigate (roll back the suspect deploy / disable the failing dependency).
5. Mark the fingerprint **Acknowledged** while you work, **Resolved** when fixed.

### APIErrorRateElevated (warning)
> 1% of requests are 5xx over 15 minutes. Same procedure, lower urgency — catch
it before it becomes critical.

### APIUnhandledExceptionSpike (warning)
> More than 1 unhandled exception/sec for 5 minutes. Go straight to
`/admin/errors` and triage the top fingerprint.

### APILatencyP95High (warning)
> p95 latency > 2s for 10 minutes. Use the dashboard's *Latency p50/p95/p99* and
*Top 10 endpoints by p95* panels, plus *DB query p95 + slow-query rate*, to
locate the slow path. Not necessarily error-related.

## Triage workflow (status model)

`open → acknowledged → resolved`. Resolved errors **auto-reopen** (and increment
`regression_count`) if the same fingerprint recurs — so a resolved item coming
back is a real signal, not noise. You can also manually reopen.

## Tracker health

The dashboard's *Error tracker health* panel shows:
- `pending` — fingerprints buffered awaiting flush (should hover near 0).
- `dropped/s` — occurrences dropped because the in-memory aggregator hit its cap
  (`ERROR_TRACKING_MAX_PENDING_FINGERPRINTS`, default 500). Sustained drops mean
  an error storm with very high fingerprint cardinality.
- `flush failures/s` — DB flush failures. The batch is re-queued and retried, so
  brief blips are harmless; sustained failures mean the database is unreachable.

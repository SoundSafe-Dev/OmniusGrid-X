# Runbook: one tenant is degrading the platform

One organisation's traffic is affecting everyone else's. Usually not an attack — a runaway
integration, a historian sweep, a retry loop with no backoff, a bulk import at 200 requests a
second.

## Read this before reaching for the rate limiter

**There is no per-tenant limit to turn up, and the per-user limit works against you here.**

`middleware/rate_limit.py` keys on the token's `sub` — the **user id**. So the budget is
per-user, and a tenant's total budget scales with its user count: a tenant with 500 users has
500× the throughput of a tenant with one, and machine-to-machine traffic from a single service
account is limited as if it were one person at a keyboard.

There are also **no quotas of any kind** — `quota`, `max_assets`, `tenant_limit` and
`plan_limit` return zero hits across the backend. Nothing bounds a tenant's assets, ingestion
rate, storage or export size (FS-842, FS-843).

That means: *the containment options below are all blunt.* Knowing that now is better than
discovering it while looking for a knob that does not exist.

## Detection

The alert is usually indirect — the platform is slow, not obviously attacked:

- `APILatencyP95High`, `APIHighErrorRate`
- `SLOErrorBudgetFastBurn` — the budget is being spent on one tenant's behalf
- `DatabaseConnectionsNearLimit`, `IdleInTransactionBackends`
- `IngestionLagHigh` if it is write traffic

Find the source. There is no per-tenant request metric — `http_requests_total` is labelled by
method and status class only, deliberately, to keep cardinality bounded — so the answer is in
the logs, which is why FS-789 deployed Loki in-cluster:

```logql
sum by (organization_id) (count_over_time({namespace="omniusgrid", app="backend"} | json [5m]))
```

Or from the database, which also tells you *what* they are doing:

```sql
SELECT usename, count(*), max(now() - query_start) AS longest, left(query, 80)
FROM pg_stat_activity WHERE state = 'active'
GROUP BY 1, 4 ORDER BY 2 DESC LIMIT 10;
```

## Containment, cheapest first

### 1. Find and stop the specific thing

Almost always better than any throttle. A stuck export, a retrying webhook, a scheduled sweep
someone set to every minute. Look for the same request shape repeating:

```bash
kubectl logs -n omniusgrid deploy/prod-backend --since=15m | grep -o '"path":"[^"]*"' | sort | uniq -c | sort -rn | head
```

If it is a background job rather than user traffic, cancelling that job costs one tenant one
feature for an hour, which is the smallest available blast radius.

### 2. Kill the queries, not the tenant

A single unbounded query can saturate the pool. `max_connections` is 200 on the CNPG cluster
and unset (Postgres default 100) on the base StatefulSet, while the HPA allows 20 backend
replicas — the arithmetic is tight (FS-839), so a few stuck queries are enough.

```sql
SELECT pg_cancel_backend(pid) FROM pg_stat_activity
WHERE state = 'active' AND now() - query_start > interval '5 minutes';
```

`pg_cancel_backend` first, always. `pg_terminate_backend` drops the connection and can leave
the client retrying immediately, which makes it worse.

### 3. Shed at the edge

`services/data_shedding.py` has five priority tiers with per-tenant overrides. Shedding
diagnostic and bulk traffic (tiers 4–5) protects safety and operational traffic (tiers 1–3) —
which is the right trade, and it is the mechanism designed for exactly this. Note it currently
applies edge-side; extending it to the cloud is FS-860..864.

### 4. Block the tenant

The blunt instrument, and it is a **customer-affecting decision**: deactivate the offending
API key, or add an ingress deny for the source. Record who decided, and start the
customer-notification clock from
[incident-response-plan.md](incident-response-plan.md) §4 — a tenant who cannot use the
product is a SEV-1 *for them* even if the platform is now healthy.

## If it is actually an attack

The distinction matters less than it seems: the containment is the same and the difference is
what happens afterwards.

- **Credential stuffing** — `AuthBruteForceSuspected` and `AuthFailureRatioHigh` fire. Be
  aware that **rate limiting is not lockout**: there is no `failed_login_count`, no
  `locked_until`, no progressive delay (OG-AC-004), so an attacker pacing below the limit is
  unbounded. Blocking the source is the only real containment today.
- **Volumetric** — this is upstream of the cluster. A NetworkPolicy will not help; the answer
  is the load balancer or CDN in front of the ingress.

Either way it becomes a security incident under
[incident-response-plan.md](incident-response-plan.md), with evidence capture *before* any
restart destroys it.

## Verification

- p95 latency back to baseline, error budget no longer burning;
- connection count well below the limit;
- **other tenants recovered** — that is the property that was actually broken, and the one
  worth checking explicitly rather than assuming from a global metric.

## After the incident

Every containment step above is blunt because the fine-grained ones do not exist. The incident
is the argument for them, and they are already scoped:

| gap | item |
|---|---|
| Rate limits are per-user, so a large tenant gets a proportionally larger budget | FS-843 |
| No quotas at all — assets, users, ingestion rate, storage, export size | FS-842 |
| No per-tenant concurrency cap; one tenant's sweep can take the whole pool | FS-844 |
| No global request timeout | FS-845 |
| Cloud-side shedding by tenant priority | FS-860..864 |

If this happens twice, stop treating it as an incident and treat it as the missing feature it
is.

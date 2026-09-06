"""HTTP request metrics for SLO computation (task 16).

The request-context middleware records one observation per request here, giving
Prometheus the request-rate / error-ratio / latency series the SLO recording
rules and burn-rate alerts are built on. Labels are deliberately low-cardinality
(method + status class, not raw path) so the series stay cheap.
"""

from prometheus_client import Counter, Gauge, Histogram

HTTP_REQUESTS = Counter(
    "http_requests_total",
    "HTTP requests by method and status class",
    ["method", "status_class"],
)

HTTP_REQUEST_DURATION = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency",
    ["method"],
    buckets=[0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0],
)


#: WHICH route failed, not merely that one did (FS-1015).
#:
#: `http_requests_total` is labelled by method and status class only, so a 500 on
#: `POST /yard/trailers/checkin` and a 500 anywhere else in the API are the same series.
#: `api/yard.py`, `api/transportation.py`, `api/shop_floor.py` and `api/fleet_targeting.py`
#: carry no counters of their own -- measured: zero `Counter(`, `_total` or `.inc()` across
#: all four -- so every write in the logistics and shop-floor surface was visible only as
#: an anonymous contribution to a global 5xx rate. An operator seeing that rate rise had no
#: way to narrow it without reading logs.
#:
#: LABELLED ONLY ON FAILURE, deliberately. Adding a `route` label to `http_requests_total`
#: would answer the same question and multiply the series count by every route in the API
#: -- roughly 550 of them -- for traffic that is overwhelmingly successful. Errors are rare,
#: so this stays small while carrying exactly the dimension the global counter lacks. The
#: route value is the matched TEMPLATE (`/assets/{asset_id}`), never the concrete path, or
#: every id would become its own series.
HTTP_ROUTE_ERRORS = Counter(
    "opsgrid_http_route_errors_total",
    "Non-2xx responses by matched route template, method and status class",
    ["route", "method", "status_class"],
)


def record_http(
    method: str,
    status_code: int,
    duration_seconds: float,
    route: str | None = None,
) -> None:
    status_class = f"{status_code // 100}xx"
    HTTP_REQUESTS.labels(method=method, status_class=status_class).inc()
    HTTP_REQUEST_DURATION.labels(method=method).observe(duration_seconds)
    # `route` is optional so any existing caller keeps working; without it the failure is
    # still counted globally, just not located.
    if status_code >= 400 and route:
        HTTP_ROUTE_ERRORS.labels(
            route=route, method=method, status_class=status_class
        ).inc()


# ---------------------------------------------------------------------------
# Auth + WebSocket metrics (FS-229)
# ---------------------------------------------------------------------------
# These exist because the alerts that need them could not be written without
# them. The sprint plan listed "auth brute-force" and "WebSocket drop rate" as
# MISSING ALERTS, but the underlying signals did not exist either — failures were
# only ever structlog lines, which Prometheus never sees. Writing the alert rules
# first would have produced rules that lint green, deploy fine, and can never
# fire: the exact silent-gap class this codebase keeps hitting.
#
# Cardinality is deliberately bounded. `reason` is a small closed set, and there
# is NO per-user or per-IP label: an attacker enumerating accounts would otherwise
# create one series per attempt, and the metric meant to detect the attack would
# become the outage.

AUTH_ATTEMPTS = Counter(
    "opsgrid_auth_attempts_total",
    "Authentication attempts by outcome",
    ["outcome", "reason"],
)

WEBSOCKET_CONNECTIONS = Gauge(
    "opsgrid_websocket_connections",
    "Currently open WebSocket connections",
)

WEBSOCKET_EVENTS = Counter(
    "opsgrid_websocket_events_total",
    "WebSocket lifecycle events by kind",
    ["event"],
)


def record_auth_attempt(outcome: str, reason: str = "none") -> None:
    """Record one authentication outcome.

    ``outcome`` is "success" or "failure"; ``reason`` narrows a failure
    ("bad_credentials", "inactive_user") and stays "none" on success.
    """
    AUTH_ATTEMPTS.labels(outcome=outcome, reason=reason).inc()


def record_websocket_event(event: str, delta: int = 0) -> None:
    """Record a WebSocket lifecycle event and adjust the open-connection gauge.

    ``delta`` is +1 on connect and -1 on any disconnect, so the gauge stays
    accurate without the caller tracking state.
    """
    WEBSOCKET_EVENTS.labels(event=event).inc()
    if delta:
        WEBSOCKET_CONNECTIONS.inc(delta)


#: Audit rows the middleware could not write (FS-536).
#:
#: THIS HAS ALREADY HAPPENED, AND THE COMMENT RECORDING IT IS IN THE SCHEMA.
#: `db/models.py:1561-1567`: migrations create `audit_logs.ip_address` as INET, the model
#: declared VARCHAR, every insert bound `$n::VARCHAR`, Postgres rejected it — "and
#: audit_trail swallows the failure as `audit_log_failed`, so **the audit trail has been
#: silently empty on real deployments while every write appeared to succeed**."
#:
#: The type mismatch was fixed. The condition that made it invisible was not: the handler
#: still logs and continues, and nothing counts. So the next thing that breaks an audit
#: write — a constraint, a migration, a full disk, an RLS policy — reproduces the same
#: outcome, and an auditor discovers it by finding a period with no rows.
#:
#: Continuing IS right. An audit write must not fail a user's request. But "do not fail the
#: request" and "do not tell anyone" are separate decisions, and only the first was made.
#:
#: Labelled by ACTION, which is a bounded vocabulary, never by error text.
AUDIT_WRITE_FAILURES = Counter(
    "opsgrid_audit_write_failed_total",
    "Audit rows the middleware could not persist",
    ["action"],
)


#: A correlation job store that fell back to process memory because Redis did not answer.
#:
#: The handler is right to continue — local development runs without a broker, and refusing
#: to start there would be worse than the fallback. What the fallback COSTS is invisible:
#: the in-memory store is per-process, so with more than one API worker a job created on one
#: is a 404 on the next, and a job whose progress is polled round-robin appears to move
#: backwards. The log line says "unavailable" once, at the first ping, and the degraded mode
#: then runs indefinitely with nothing to alert on.
#:
#: Unlabelled: there is one store and one reason, and error text is never a label value.
CORRELATION_JOB_STORE_DEGRADED = Counter(
    "opsgrid_correlation_job_store_degraded_total",
    "Times the correlation job store fell back to in-process memory because Redis was unreachable",
)


#: The error-tracking middleware's own tracker call failing (FS-910). The middleware is
#: right to swallow this -- "a bug in the tracker must never change what the client
#: receives" -- but a tracker that silently stops recording is the same class of failure
#: as an audit trail that silently goes empty (FS-536): the symptom is an incident with no
#: fingerprint in error_tracker rather than an error anywhere loud enough to be noticed.
ERROR_TRACKER_RECORD_FAILURES = Counter(
    "opsgrid_error_tracker_record_failed_total",
    "Times the error-tracking middleware could not record an exception it caught",
)


#: The edge fleet sweep's per-pass loop failing (FS-910). `_run` is right to keep looping --
#: one bad pass must not end the sweep -- but a sweep that keeps failing silently degrades
#: `EdgeAgentStatus`/`Asset` freshness for every organisation with nothing to alert on.
EDGE_FLEET_SWEEP_FAILURES = Counter(
    "opsgrid_edge_fleet_sweep_failed_total",
    "Times one pass of the edge fleet sweep raised and was skipped",
)


# --- CONNECTION POOL (FS-841) -------------------------------------------------------
#
# WHY A COLLECTOR AND NOT COUNTERS. The pool's state is already held by SQLAlchemy —
# `checkedout()`, `size()`, `overflow()` are exact at any instant. Incrementing our own
# counters on checkout and return would duplicate that state and then drift from it the
# first time a connection is invalidated rather than returned. Reading it at scrape time
# cannot drift, and costs nothing between scrapes.
#
# WHAT THIS WATCHES FOR. `pg_connections_used` from postgres_exporter sees the database's
# total and is the LATER signal: by the time it saturates, every client is already
# failing. Saturation happens first inside one process's pool, where requests queue
# against `pool_timeout` while the database still has capacity — the API is slow, the
# database looks healthy, and nothing connects the two. FS-839 sized the pools; this is
# how anyone finds out the sizing was wrong.

DB_POOL_CONNECTIONS = Gauge(
    "opsgrid_db_pool_connections",
    "SQLAlchemy connection pool state for this process",
    ["state"],
)

DB_POOL_LIMIT = Gauge(
    "opsgrid_db_pool_limit",
    "Connections this process's pool may open (pool_size + max_overflow)",
)


def observe_db_pool(pool) -> None:
    """Refresh the pool gauges from a live SQLAlchemy pool.

    Tolerant on purpose: `NullPool` and SQLite's pools implement none of these methods,
    and a metrics scrape must not be the thing that raises. A pool that cannot report is
    simply not reported — the absence is visible in Prometheus as a missing series, which
    `absent()` alerting already treats as a fault rather than as health.
    """
    try:
        checked_out = pool.checkedout()
        size = pool.size()
        overflow = pool.overflow()
    except (AttributeError, NotImplementedError):
        return
    DB_POOL_CONNECTIONS.labels(state="in_use").set(checked_out)
    DB_POOL_CONNECTIONS.labels(state="idle").set(max(0, size - checked_out))
    # `overflow()` is NEGATIVE until the pool is full — it counts from -pool_size — so a
    # raw export would read as a nonsense gauge for the entire healthy range.
    DB_POOL_CONNECTIONS.labels(state="overflow").set(max(0, overflow))
    # The ceiling, exported beside the usage so an alert can be written as a RATIO rather
    # than against a literal. A threshold hard-coded in a rule is a second copy of the
    # pool size that nobody updates when the manifest changes — and this platform runs two
    # different pool sizes on purpose (API 10, workers 4), so one literal could not be
    # right for both.
    limit = getattr(pool, "_max_overflow", 0)
    DB_POOL_LIMIT.set(size + max(0, limit))


# --- LOAD SHEDDING (FS-860..864) ----------------------------------------------------
#
# `DataSheddingManager` drops telemetry under pressure, by design and correctly: five
# priority tiers with per-tenant overrides, so a vibration stream yields before an
# emergency stop. What it did NOT do is say so. The only record of a dropped reading was
# `logger.debug("data_shedded", ...)`, and the deployed LOG_LEVEL is `info` — so on a
# production cluster a tenant's data was discarded and **nothing anywhere recorded it**.
#
# That is deliberate data loss with no signal, which is the class this sprint opened on:
# an operator cannot alert on it, a dashboard cannot show it, and the first person to
# notice is the customer asking why a chart has gaps.
#
# LABELS ARE BOUNDED ON PURPOSE. `organization_id` is the customer list and `priority` is
# 1-5; `metric_name` is deliberately absent, because it is caller-supplied and would let a
# misconfigured device mint unbounded series — the cardinality failure FS-794 alerts on.
# The metric name is still in the debug log for anyone investigating one tenant.
TELEMETRY_SHED = Counter(
    "opsgrid_telemetry_shed_total",
    "Telemetry readings dropped by load shedding, by tenant and priority tier",
    ["organization_id", "priority"],
)

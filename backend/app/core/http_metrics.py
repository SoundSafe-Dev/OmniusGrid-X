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


def record_http(method: str, status_code: int, duration_seconds: float) -> None:
    status_class = f"{status_code // 100}xx"
    HTTP_REQUESTS.labels(method=method, status_class=status_class).inc()
    HTTP_REQUEST_DURATION.labels(method=method).observe(duration_seconds)


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

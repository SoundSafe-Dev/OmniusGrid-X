"""HTTP request metrics for SLO computation (task 16).

The request-context middleware records one observation per request here, giving
Prometheus the request-rate / error-ratio / latency series the SLO recording
rules and burn-rate alerts are built on. Labels are deliberately low-cardinality
(method + status class, not raw path) so the series stay cheap.
"""

from prometheus_client import Counter, Histogram

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

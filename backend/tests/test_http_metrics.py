"""Test HTTP request metrics recording for SLOs (task 16)."""

from app.core.http_metrics import HTTP_REQUESTS, record_http


def _count(method: str, status_class: str) -> float:
    return HTTP_REQUESTS.labels(method=method, status_class=status_class)._value.get()


def test_record_http_buckets_by_status_class():
    before = _count("GET", "2xx")
    record_http("GET", 200, 0.01)
    record_http("GET", 204, 0.02)
    assert _count("GET", "2xx") == before + 2

    err_before = _count("POST", "5xx")
    record_http("POST", 503, 0.5)
    assert _count("POST", "5xx") == err_before + 1

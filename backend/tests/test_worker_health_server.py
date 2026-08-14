"""Tests for the worker health/metrics endpoint (FS-213/214).

The point of this endpoint is to distinguish a WEDGED worker from a healthy one —
a process that is still running but has stopped consuming. A probe that only
checks "is the port open" cannot do that, so these tests focus on the staleness
semantics rather than on the HTTP plumbing.
"""
import json
import threading
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from app.workers.health_server import WorkerHealth, create_server


@pytest.fixture
def served():
    """Run the health server on an ephemeral port and yield (base_url, health)."""
    health = WorkerHealth("test-worker", stale_after_seconds=100.0)
    server: ThreadingHTTPServer = create_server(0, health)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{port}", health
    finally:
        server.shutdown()
        server.server_close()


def _get(url: str):
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:  # probes care about the status code
        return e.code, e.read()


def test_readyz_is_503_until_the_worker_reports_ready(served):
    base, health = served
    status, _ = _get(f"{base}/readyz")
    assert status == 503, "a worker that hasn't connected yet must not be Ready"

    health.ready()
    status, body = _get(f"{base}/readyz")
    assert status == 200
    assert json.loads(body)["ready"] is True


def test_healthz_fails_once_the_heartbeat_goes_stale(served):
    """The case a plain liveness check cannot detect: alive but not consuming."""
    base, health = served
    health.ready()
    assert _get(f"{base}/healthz")[0] == 200

    # Simulate the consumer loop having stopped: last beat far in the past.
    health._last_beat -= 1_000  # noqa: SLF001 — deliberately forcing staleness
    status, body = _get(f"{base}/healthz")
    assert status == 503, "a wedged worker must report unhealthy so it gets restarted"
    payload = json.loads(body)
    assert payload["status"] == "error"
    assert payload["heartbeat_age_seconds"] > payload["stale_after_seconds"]

    # A completed unit of work clears it.
    health.beat()
    assert _get(f"{base}/healthz")[0] == 200


def test_staleness_only_condemns_a_worker_that_was_already_ready(served):
    """Startup must not be reported as wedged before the worker has connected."""
    base, health = served
    health._last_beat -= 1_000  # noqa: SLF001
    status, body = _get(f"{base}/healthz")
    assert status == 200, "pre-ready staleness must not fail liveness"
    assert json.loads(body)["ready"] is False


def test_stale_after_zero_opts_out_of_staleness():
    """A worker with unbounded idle periods can keep readiness-only semantics."""
    health = WorkerHealth("idle-worker", stale_after_seconds=0)
    health.ready()
    health._last_beat -= 1_000_000  # noqa: SLF001
    assert health.snapshot()["status"] == "ok"


def test_metrics_exposes_the_heartbeat_gauge(served):
    base, health = served
    health.ready()
    health.beat()
    status, body = _get(f"{base}/metrics")
    assert status == 200
    text = body.decode()
    # Labelled by worker so ONE Prometheus job can cover all four workers.
    assert "opsgrid_worker_heartbeat_age_seconds" in text
    assert 'worker="test-worker"' in text
    assert "opsgrid_worker_units_total" in text


def test_the_scrape_itself_refreshes_the_age(served):
    """FS-697. `snapshot()` is what sets WORKER_HEARTBEAT_AGE, and it used to run only on
    /healthz — so the age Prometheus read was as fresh as the LAST LIVENESS PROBE. Both
    deployments happen to probe /healthz today; switch the probe to a TCP check and the
    gauge freezes (or, in a process never probed, never materializes its label child at
    all) while `IngestionWorkerStalled` keeps passing its hand-fed promtool test. This
    drives /metrics WITHOUT ever touching /healthz and requires the age to be current.
    """
    import re
    import time as _time

    # A UNIQUE label, not the shared fixture's "test-worker": the gauge is
    # process-global, and the staleness test earlier in this file materializes
    # test-worker's child via /healthz with a large age — against which the first
    # version of this test could not detect the refresh being removed (its own
    # mutation run proved it: 8 passed with the fix deleted). A label nothing else
    # touches has no sample at all unless THIS scrape produces one.
    health = WorkerHealth("never-probed-worker", stale_after_seconds=100.0)
    server: ThreadingHTTPServer = create_server(0, health)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        health.ready()
        health.beat()

        # Last beat 500 monotonic seconds ago, and /healthz never called.
        health._last_beat = _time.monotonic() - 500.0

        _status, body = _get(f"{base}/metrics")
    finally:
        server.shutdown()
        server.server_close()
    match = re.search(
        r'opsgrid_worker_heartbeat_age_seconds\{worker="never-probed-worker"\}\s+([0-9.e+]+)',
        body.decode(),
    )
    assert match, (
        "the age gauge has no sample for this worker — /metrics no longer refreshes it, "
        "so its freshness depends on something else polling /healthz"
    )
    assert float(match.group(1)) >= 499.0, (
        f"the scraped age is {match.group(1)}s for a worker 500s past its last beat — "
        f"Prometheus is reading a stale snapshot, and IngestionWorkerStalled fires late "
        f"or never"
    )


def test_unknown_path_is_404_not_a_crash(served):
    base, _ = served
    assert _get(f"{base}/nope")[0] == 404


def test_no_port_means_no_server_and_no_error():
    """Workers run outside Kubernetes too — absence of a port must be a no-op."""
    from app.workers.health_server import start_health_server

    assert start_health_server("x", port=None) is None

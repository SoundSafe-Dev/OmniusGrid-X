"""A collector that cannot collect must be visible as a number, not only a log line (FS-691).

WHAT WAS WRONG. `metrics.errors_total` existed, and across fifteen collectors **nothing
incremented it**. The coordinator calls `record_error` only when a message *handler* raises
(`coordinator.py:432`), which cannot fire for a failed poll — a failed poll produces no
message to hand to a handler. `metrics.py`'s own docstring asserted the opposite: that the
coordinator seam covers every collector "without editing individual collectors". True of
deliveries. False of failures, and the gap was the whole error surface.

HOW IT WAS FOUND — by running the real thing (rule 191). `test_the_http_collector_actually_collects.py`
drives the real collector through the real adapter with a *stubbed transport*, and its own
docstring warns that "a poll that raises on every cycle looks exactly like a poll that works".
Driving it instead against a live `http.server` returning 500 made that concrete: three seconds
of polling, **zero readings, `running` True, and no counter naming the asset**.

WHY NOTHING ELSE CAUGHT IT. `connection_state` is set from
`task is not None and not task.done()` (`coordinator.py:504`) — the poll task is perfectly
healthy; it is the device that is not. And no rule in `infra/prometheus/alerts.yml` keys on a
collector that is up and silent: `EdgeAgentOffline` watches `edge_agent_up`, which is 1
because the agent is heartbeating fine, and `EdgeAgentBufferHigh` watches buffer depth, which
is 0 *because* nothing was collected. So the alert that would fire on a broken machine is
silenced by the very breakage. An asset that stopped reporting a month ago and one that is
idle produce identical monitoring.

These tests drive a real socket, not a mock, because a mock is what hid this.
"""

from __future__ import annotations

import asyncio
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from opsgrid_agent import metrics
from opsgrid_agent.collectors.base import BaseCollector
from opsgrid_agent.collectors.http_rest import HTTPRestCollector


class _AlwaysFails(BaseHTTPRequestHandler):
    """A device that is reachable and answering — with an error, every time.

    This is the case that hid: not a refused connection (which surfaces fast and loudly)
    but a machine that responds promptly and uselessly.
    """

    def do_GET(self):  # noqa: N802 - http.server's required spelling
        self.send_response(500)
        self.end_headers()
        self.wfile.write(b"boom")

    def log_message(self, *_args):
        pass


@pytest.fixture
def failing_device():
    server = HTTPServer(("127.0.0.1", 0), _AlwaysFails)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/"
    finally:
        server.shutdown()


def _errors_for(asset_id: str) -> float:
    """Read the counter the way a Prometheus query would — by label, not by index.

    `errors_total.collect()` yields both the `_total` sample and a `_created` timestamp
    sample, and the timestamp is a large float that looks like a plausible count. An
    earlier read of this counter printed both and the created-at value was the eye-catching
    one. Select on the metric name.
    """
    return sum(
        sample.value
        for metric in metrics.errors_total.collect()
        for sample in metric.samples
        if sample.name.endswith("_total") and sample.labels.get("asset_id") == asset_id
    )


async def _drive(url: str, asset_id: str, seconds: float = 1.2) -> list:
    readings: list = []
    collector = HTTPRestCollector(
        {"asset_id": asset_id, "url": url, "poll_interval": 0.3}
    )
    collector.collector_type = "http_rest"
    collector.add_data_handler(readings.append)
    await collector.start()
    try:
        await asyncio.sleep(seconds)
    finally:
        await collector.stop()
    return readings


class TestAFailingDeviceIsCounted:
    @pytest.mark.asyncio
    async def test_polling_a_500_increments_the_error_counter(self, failing_device):
        """THE PROPERTY. Before the fix this counter stayed at zero forever, for every
        collector in the package, and the only trace of a dead machine was an ERROR line."""
        before = _errors_for("press-counted")
        readings = await _drive(failing_device, "press-counted")

        assert readings == [], "a server returning 500 must not produce readings"
        assert _errors_for("press-counted") > before, (
            "a collector polling a device that fails every time produced no readings AND "
            "moved no counter — which is indistinguishable from an idle machine. Failures "
            "on a collection path belong in `record_failure`, not a bare `logger.error`."
        )

    @pytest.mark.asyncio
    async def test_it_counts_once_per_failed_poll(self, failing_device):
        """A single increment on the first failure would still leave a permanently-broken
        device looking like a one-off blip. The rate is the signal an alert can use."""
        before = _errors_for("press-rate")
        await _drive(failing_device, "press-rate")
        assert _errors_for("press-rate") - before >= 2, (
            "roughly four polls at 0.3s over 1.2s should each be counted"
        )

    @pytest.mark.asyncio
    async def test_a_healthy_device_moves_nothing(self, failing_device):
        """NEGATIVE CONTROL. A counter that increments on every poll regardless would pass
        both tests above and be worthless. Here the same collector talks to a server that
        works, and the counter must stay put."""

        class _Works(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"state": "running"}')

            def log_message(self, *_args):
                pass

        server = HTTPServer(("127.0.0.1", 0), _Works)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            before = _errors_for("press-healthy")
            readings = await _drive(f"http://127.0.0.1:{server.server_address[1]}/", "press-healthy")
        finally:
            server.shutdown()

        assert readings, "the control server answers 200 and must produce readings"
        assert _errors_for("press-healthy") == before


class TestTheLabelsJoin:
    """The counter and the gauge must describe the same collector in the same words.

    `connection_state` is labelled with the CONFIGURED type ("http_rest"), so a counter
    labelled with the class name ("HTTPRestCollector") could not be joined to it in a
    query — `errors_total` and `connection_state` would look like different collectors.
    """

    def test_the_configured_type_is_used_when_the_coordinator_sets_it(self):
        collector = HTTPRestCollector({"asset_id": "a", "url": "http://x/"})
        collector.collector_type = "http_rest"
        collector.record_failure("probe_failed", error="x")

        labels = {
            sample.labels["collector_type"]
            for metric in metrics.errors_total.collect()
            for sample in metric.samples
            if sample.labels.get("asset_id") == "a"
        }
        assert labels == {"http_rest"}

    def test_the_class_name_is_the_fallback(self):
        """A collector built directly — as tests do — still counts, under a name that
        identifies it. Falling back to empty string would collapse every collector type
        into one unusable series."""
        collector = HTTPRestCollector({"asset_id": "b", "url": "http://x/"})
        collector.record_failure("probe_failed", error="x")

        labels = {
            sample.labels["collector_type"]
            for metric in metrics.errors_total.collect()
            for sample in metric.samples
            if sample.labels.get("asset_id") == "b"
        }
        assert labels == {"HTTPRestCollector"}

    def test_the_adapter_still_exposes_what_the_coordinator_unwraps(self):
        """BaseCollector-style collectors are wrapped, so setting `collector_type` on what
        `SUPPORTED_COLLECTORS` constructs sets it on the adapter and NOT on the collector
        that does the counting. The coordinator unwraps `_collector`; this pins that it
        still finds a BaseCollector to label."""
        from opsgrid_agent.collectors.adapter import coordinator_adapter

        adapter = coordinator_adapter(HTTPRestCollector)(url="http://x/", asset_id="c")
        inner = getattr(adapter, "_collector", adapter)
        assert isinstance(inner, BaseCollector), (
            "the coordinator labels `collector._collector` — if the adapter renames that "
            "attribute the label silently reverts to the class name for every wrapped "
            "collector, and no test would have noticed"
        )

    @pytest.mark.asyncio
    async def test_the_coordinator_actually_labels_the_collector_it_starts(self):
        """The test above pins the ADAPTER's attribute name. It does not pin that the
        coordinator uses it — and that distinction is not academic: replacing the unwrap
        with `inner = collector` leaves the adapter failing the `isinstance` check, so
        labelling is skipped in silence and every wrapped collector reverts to its class
        name. That mutation passed every test in this package until this one existed.

        So this drives the real `_start_collector` and reads the label off the collector
        that will do the counting.
        """
        import os
        import tempfile

        from opsgrid_agent.buffer.store_forward import StoreForwardBuffer
        from opsgrid_agent.collectors.coordinator import (
            CollectorConfig,
            UnifiedCollectorCoordinator,
        )

        buffer = StoreForwardBuffer(
            buffer_path=os.path.join(tempfile.mkdtemp(), "buffer.db"),
            retention_hours=24,
        )
        coordinator = UnifiedCollectorCoordinator(buffer=buffer, kafka_producer=None)
        config = CollectorConfig(
            collector_type="http_rest",
            asset_id="labelled-by-coordinator",
            config={"asset_id": "labelled-by-coordinator", "url": "http://127.0.0.1:1/"},
        )
        try:
            await coordinator._start_collector(config)
            collector = coordinator.collectors["labelled-by-coordinator"]
            inner = getattr(collector, "_collector", collector)
            assert inner.collector_type == "http_rest", (
                "the coordinator knows the configured type and the collector does not; if "
                "it does not hand it over, `errors_total` is labelled with the class name "
                "while `connection_state` uses the config type, and the two cannot be "
                "joined for the same collector"
            )
        finally:
            await coordinator.stop_all()

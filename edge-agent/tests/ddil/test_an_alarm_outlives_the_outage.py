"""S3 — a local alarm has to do something local (FS-755).

THE ACCEPTANCE CRITERION, from the DDIL plan: *with the uplink blackholed, a breach writes
to a local sink within 1s and survives restart.*

What it replaces. `LocalAlertingEngine` fired and three things happened: a Prometheus
counter incremented, a warning was logged, and the alert joined an in-memory list capped at
1,000. Every one of those is either read across the network — the scrape, the log shipper —
or lost when the process restarts. A counter is not an action when the thing that reads it
is on the far side of the outage.

The fourth thing that did not happen: `analytics/pipeline.py` discarded the fired alerts, so
they never reached the store-and-forward buffer either. The alarm did not merely fail to
arrive during the outage; it never travelled at all. The backend saw the raw reading and had
to re-derive the breach, unaware that the edge had already decided.

These scenarios assert the local half. The uplink half rides on FS-754: an alarm is a tier-1
message, so it leaves ahead of the backlog rather than behind it.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pytest

from opsgrid_agent.analytics import alerting_tracker, pipeline
from opsgrid_agent.analytics.alert_sink import LocalAlertSink
from opsgrid_agent.buffer.priority import priority_for
from opsgrid_agent.buffer.store_forward import StoreForwardBuffer
from opsgrid_agent.collectors.coordinator import UnifiedCollectorCoordinator

from .link import FakeUplink, LinkController, drain

pytestmark = pytest.mark.ddil

RULE = {
    "rule_id": "bearing-temp-critical",
    "metric_name": "temp_bearing",
    "condition": ">",
    "threshold": 85.0,
    "severity": "critical",
    "message_template": "bearing at {value}C, limit {threshold}C",
    "cooldown_seconds": 0,
}


def _reading(value: float, asset: str = "press-01") -> dict:
    return {
        "asset_id": asset,
        "collector_type": "modbus",
        "topic": "telemetry",
        "timestamp_edge": datetime.now(timezone.utc).isoformat(),
        "payload": {"temp_bearing": value},
    }


class _Harness:
    """A coordinator wired to a real buffer and a real sink, with the link denied."""

    def __init__(self, directory: str, *, with_sink: bool = True):
        self.directory = Path(directory)
        self.buffer = StoreForwardBuffer(buffer_path=str(self.directory / "buffer.db"))
        self.sink = (
            LocalAlertSink(self.directory / "local_alerts.db") if with_sink else None
        )
        self.coordinator = UnifiedCollectorCoordinator(
            buffer=self.buffer, alert_sink=self.sink
        )
        alerting_tracker.reset()
        alerting_tracker.configure("press-01", [RULE])

    def feed(self, value: float):
        asyncio.run(self.coordinator._on_collector_message(_reading(value)))


@pytest.fixture(autouse=True)
def _clean_trackers():
    pipeline.reset()
    yield
    pipeline.reset()


class TestTheBreachIsWrittenLocally:
    def test_a_breach_reaches_the_local_sink_well_inside_one_second(self):
        with TemporaryDirectory() as directory:
            harness = _Harness(directory)

            started = time.monotonic()
            harness.feed(97.0)
            elapsed = time.monotonic() - started

            recorded = harness.sink.recent()
            assert len(recorded) == 1, recorded
            assert recorded[0]["rule_id"] == "bearing-temp-critical"
            assert recorded[0]["severity"] == "critical"
            assert recorded[0]["value"] == 97.0
            assert recorded[0]["asset_id"] == "press-01", (
                "the recorded alarm does not say which machine it came from. The rule does "
                "not know the asset and the engine does, so if the engine stops stamping it "
                "the row is still written, still readable, and useless to a technician "
                "holding a laptop in front of a line of presses."
            )
            assert recorded[0]["metric_name"] == "temp_bearing"
            assert elapsed < 1.0, (
                f"the whole message path took {elapsed:.3f}s, and the acceptance criterion "
                "is one second for the local write"
            )

    def test_a_reading_under_the_threshold_records_nothing(self):
        """The control case. Without it, a sink that recorded EVERY reading would pass the
        test above and nobody would know the rule was not being consulted."""
        with TemporaryDirectory() as directory:
            harness = _Harness(directory)
            harness.feed(40.0)
            assert harness.sink.recent() == []
            assert harness.sink.count() == 0

    def test_the_alarm_is_readable_after_a_restart(self):
        """The acceptance criterion's second half. Everything the old code did — counter,
        log line, in-memory list — is gone at this point in the scenario."""
        with TemporaryDirectory() as directory:
            harness = _Harness(directory)
            harness.feed(97.0)
            del harness  # the process, as far as this test is concerned

            reopened = LocalAlertSink(Path(directory) / "local_alerts.db")
            survivors = reopened.recent()
            assert len(survivors) == 1, (
                "the alarm did not survive the restart, which is the failure mode a "
                "counter and an in-memory list both have"
            )
            assert survivors[0]["message"] == "bearing at 97.0C, limit 85.0C"

    def test_the_write_is_durable_and_not_merely_committed(self):
        """`synchronous=FULL`, asserted rather than assumed.

        WAL with the default `synchronous=NORMAL` can lose the last commits to a power cut,
        and a power cut is an entirely ordinary way for the conditions that raised an alarm
        to end. The pragma is the difference between "survives a restart" and "survives the
        thing that caused the restart"."""
        with TemporaryDirectory() as directory:
            sink = LocalAlertSink(Path(directory) / "local_alerts.db")
            with sqlite3.connect(sink.path) as conn:
                pass
            connection = sink._connect()
            try:
                mode = connection.execute("PRAGMA synchronous").fetchone()[0]
            finally:
                connection.close()
            assert mode == 2, (
                f"synchronous={mode}; FULL is 2. NORMAL (1) can lose the last commit on "
                "power loss, which is exactly the case this sink is for."
            )


class TestTheAlarmAlsoLeavesFirstWhenTheLinkReturns:
    def test_the_alarm_is_buffered_as_tier_one(self):
        with TemporaryDirectory() as directory:
            harness = _Harness(directory)
            harness.feed(97.0)

            with sqlite3.connect(harness.buffer.buffer_path) as conn:
                rows = conn.execute(
                    "SELECT topic, priority FROM messages ORDER BY id"
                ).fetchall()

            # The reading itself (tier 3, temp_bearing is unclassified process data) and
            # the alarm it raised (tier 1).
            assert ("alarm", 1) in rows, rows
            assert priority_for("alarm") == 1

    def test_the_alarm_overtakes_a_backlog_built_during_the_outage(self):
        """S3 and S2 composed. The alarm happens FIRST, then 3,000 vibration readings pile
        up behind it during the rest of the outage; it must still be drained first."""
        with TemporaryDirectory() as directory:
            harness = _Harness(directory)
            harness.feed(97.0)

            outage_start = datetime.now(timezone.utc)
            for index in range(3_000):
                asyncio.run(
                    harness.buffer.store(
                        timestamp_edge=outage_start + timedelta(milliseconds=index),
                        asset_id="press-01",
                        topic="telemetry",
                        payload={"vibration": 0.1 * index},
                    )
                )

            uplink = FakeUplink(LinkController())
            asyncio.run(drain(harness.buffer, uplink, batch_size=1, rounds=1))

            first = json.loads(uplink.delivered[0]["payload"])
            assert first.get("alarm") == "critical", first

    def test_the_sink_records_whether_the_alarm_was_queued_for_uplink(self):
        """Distinguishing "queued but the link is down" from "never left this box" is the
        difference between a delayed alarm and a lost one, and only the sink can tell you."""
        with TemporaryDirectory() as directory:
            harness = _Harness(directory)
            harness.feed(97.0)
            assert harness.sink.recent()[0]["uplink_queued"] == 1

    def test_a_failed_uplink_queue_does_not_lose_the_local_record(self):
        with TemporaryDirectory() as directory:
            harness = _Harness(directory)
            original = harness.buffer.store

            async def fail_only_the_alarm(**kwargs):
                # Failing EVERY store would abort the message before analytics ran and the
                # alarm would never be raised at all — the test would then pass for the
                # wrong reason by proving nothing was recorded because nothing happened.
                if kwargs.get("topic") == "alarm":
                    raise OSError("disk gone")
                return await original(**kwargs)

            with patch.object(harness.buffer, "store", side_effect=fail_only_the_alarm):
                harness.feed(97.0)

            recorded = harness.sink.recent()
            assert len(recorded) == 1, (
                "the local write happens FIRST precisely so a broken uplink cannot take "
                "the alarm with it"
            )
            assert recorded[0]["uplink_queued"] == 0


class TestTheDegradedConfigurationsAreVisible:
    def test_an_agent_with_no_sink_says_so_rather_than_silently_forgetting(self):
        with TemporaryDirectory() as directory:
            harness = _Harness(directory, with_sink=False)
            with patch("opsgrid_agent.collectors.coordinator.logger") as log:
                harness.feed(97.0)
            warned = [c for c in log.warning.call_args_list
                      if c.args and c.args[0] == "local_alert_not_durable"]
            assert warned, (
                "a coordinator with no alert sink logged nothing; a silently non-durable "
                "alarm path is the defect this work exists to remove"
            )

    def test_the_sink_swallows_its_own_write_failures(self):
        """`record` is documented as never raising, because it is called from the collector
        message path and an alarm sink that can take down data collection is a worse
        failure than the one it prevents. Documented is not enforced; this enforces it."""
        with TemporaryDirectory() as directory:
            sink = LocalAlertSink(Path(directory) / "a.db")
            with patch.object(sink, "_connect", side_effect=sqlite3.Error("disk full")):
                assert sink.record({"rule_id": "r", "severity": "critical"}) is None
                assert sink.recent() == []
                sink.mark_uplink_queued(1)  # also must not raise

    def test_a_broken_sink_does_not_cost_the_reading(self):
        with TemporaryDirectory() as directory:
            harness = _Harness(directory)
            with patch.object(harness.sink, "record", return_value=None):
                harness.feed(97.0)

            with sqlite3.connect(harness.buffer.buffer_path) as conn:
                topics = [r[0] for r in conn.execute("SELECT topic FROM messages")]
            assert "telemetry" in topics, (
                "the reading was lost when the sink returned nothing; the alarm path must "
                "be additive to data collection, never in its way"
            )
            assert "alarm" in topics


class TestRetention:
    def test_alarms_older_than_the_window_are_pruned_and_recent_ones_are_not(self):
        with TemporaryDirectory() as directory:
            sink = LocalAlertSink(Path(directory) / "a.db", retention_days=7)
            old = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
            new = datetime.now(timezone.utc).isoformat()
            sink.record({"rule_id": "r", "asset_id": "a", "metric_name": "m",
                         "severity": "critical", "timestamp": old})
            sink.record({"rule_id": "r", "asset_id": "a", "metric_name": "m",
                         "severity": "critical", "timestamp": new})

            removed = sink.prune()

            assert removed == 1, removed
            assert sink.count() == 1


class TestTheEndpointAnOperatorCanActuallyReach:
    """`/alerts` is the only alarm surface that does not cross the link, so it needs a test
    that actually speaks HTTP to it. Renaming the route away from `/alerts` left every other
    scenario green — the sink was still recording, nothing was reading."""

    def test_a_get_returns_the_recorded_alarms(self):
        import http.client
        import threading

        from opsgrid_agent.metrics_server import create_server

        with TemporaryDirectory() as directory:
            harness = _Harness(directory)
            harness.feed(97.0)

            server = create_server(
                0,  # any free port; the DDIL suite must not fight for a fixed one
                health_provider=lambda: {"status": "ok"},
                alerts_provider=lambda: harness.sink.recent(),
            )
            port = server.server_address[1]
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                connection.request("GET", "/alerts")
                response = connection.getresponse()
                body = json.loads(response.read())
            finally:
                server.shutdown()
                server.server_close()

            assert response.status == 200, response.status
            assert body["count"] == 1, body
            assert body["alerts"][0]["rule_id"] == "bearing-temp-critical"
            assert body["alerts"][0]["asset_id"] == "press-01"

    def test_an_unknown_path_is_still_a_404(self):
        """The control case: a handler that answered everything with the alert list would
        pass the test above."""
        import http.client
        import threading

        from opsgrid_agent.metrics_server import create_server

        server = create_server(0, alerts_provider=lambda: [])
        port = server.server_address[1]
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            connection.request("GET", "/nope")
            assert connection.getresponse().status == 404
        finally:
            server.shutdown()
            server.server_close()

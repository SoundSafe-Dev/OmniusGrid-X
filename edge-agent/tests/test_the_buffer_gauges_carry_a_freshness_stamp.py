"""A gauge is only as honest as its last write (FS-694).

`edge_buffer_messages` is refreshed by the agent's stats loop every five minutes. If that
loop fails every cycle — a corrupted SQLite file, a schema drift in `get_stats` — the gauge
does not go to zero and does not disappear: it FREEZES at its final value. `EdgeBufferGrowing`
then reasons about a number that stopped meaning anything, and the heartbeat's
`_buffer_snapshot` freezes with it, so `EdgeAgentBufferHigh` goes quiet in the same breath.
One failing loop mutes both buffer alerts, at exactly the moment the buffer may be growing.

This is rule 196 applied to the instrument itself: the gauge measures the buffer, but nothing
measured the *measuring*. The repair is the standard watchdog: `set_buffer_stats` stamps
`edge_buffer_stats_last_success_timestamp_seconds` on every successful refresh, the agent
stamps a baseline at loop start so the series exists even if no refresh ever succeeds (the
absent-series trap, closed at the source this time), and `EdgeBufferStatsStale` alerts on the
age — with a promtool test in `infra/prometheus/tests/buffer_stats_staleness_test.yml`
driving both directions.
"""

from __future__ import annotations

import pathlib
import time

from opsgrid_agent import metrics


def _stamp() -> float:
    for metric in metrics.buffer_stats_last_success.collect():
        for sample in metric.samples:
            if sample.name == "edge_buffer_stats_last_success_timestamp_seconds":
                return sample.value
    raise AssertionError("the freshness stamp is no longer exported")


class TestTheStampIsMaintained:
    def test_a_refresh_stamps_the_current_time(self):
        """THE PROPERTY. Every successful buffer-stats write must move the watchdog, or a
        frozen gauge and a live one are indistinguishable to the alert."""
        before = _stamp()
        metrics.set_buffer_stats(pending=7, backfill_lag_seconds=0.0)
        after = _stamp()
        assert after >= before
        assert abs(after - time.time()) < 2.0, (
            f"the stamp is {after}, which is not the current unix time — the alert "
            f"computes time() minus this value, so anything else breaks the age"
        )

    def test_the_stamp_travels_with_the_gauges_it_vouches_for(self):
        """The stamp must be written by `set_buffer_stats` itself, not beside it. A stamp
        updated in the loop but outside the helper would keep reading fresh through a
        refactor that calls the helper from somewhere the stats are stale."""
        import inspect

        source = inspect.getsource(metrics.set_buffer_stats)
        assert "buffer_stats_last_success" in source, (
            "set_buffer_stats no longer stamps the freshness watchdog — a stats loop "
            "failing every cycle is invisible to EdgeBufferStatsStale again"
        )

    def test_the_loop_stamps_a_baseline_before_first_success(self):
        """The absent-series trap: a loop that NEVER succeeds would never create the
        series, and `time() - <absent>` evaluates to nothing — the alert cannot fire for
        precisely the agent that has been broken since boot. The baseline stamp at loop
        start is what closes that. Source-level, because starting the full agent needs a
        broker."""
        main = pathlib.Path(__file__).resolve().parent.parent / "opsgrid_agent" / "main.py"
        source = main.read_text()
        loop_start = source.index("async def _stats_reporter")
        loop_body = source[loop_start:loop_start + 2500]
        first_while = loop_body.index("while self._running")
        assert "buffer_stats_last_success.set" in loop_body[:first_while], (
            "_stats_reporter no longer stamps a baseline before its loop — an agent whose "
            "stats loop never succeeds once has no series for EdgeBufferStatsStale to age"
        )


class TestTheAlertExists:
    """The metric without the alert is half the fix — the promtool test drives the alert's
    behaviour; this pins the wiring so neither half can be deleted alone."""

    ALERTS = pathlib.Path(__file__).resolve().parent.parent.parent / "infra" / "prometheus" / "alerts.yml"

    def test_the_staleness_rule_watches_this_metric(self):
        text = self.ALERTS.read_text()
        assert "EdgeBufferStatsStale" in text
        assert "edge_buffer_stats_last_success_timestamp_seconds" in text

    def test_its_promtool_test_exists(self):
        tests_dir = self.ALERTS.parent / "tests"
        assert (tests_dir / "buffer_stats_staleness_test.yml").exists(), (
            "the alert's unit test is gone — promtool check rules passes on an alert that "
            "can never fire, so without the test the rule is only known to parse"
        )

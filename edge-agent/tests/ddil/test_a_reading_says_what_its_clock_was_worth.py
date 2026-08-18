"""S8 — the clock correction that was never applied (FS-760).

`ClockSkewEstimator` has sampled the server clock and maintained an EWMA of the offset since
task 21. `correct()` had **no callers anywhere in the agent**. The offset was used to judge
request-signature freshness and whether a replayed command had expired, and never applied to
a single telemetry timestamp — so every reading this system holds carries the raw clock of a
device that frequently has no NTP.

The module docstring said the opposite: *"Timestamps are corrected by that offset before
forward, and the raw edge time is preserved alongside for audit."* Neither clause was true.
That is how it survived — a reader checking whether time was handled found a paragraph
saying it was, and no reason to look further.

CORRECTING IT IS ONLY HALF THE FIX, and on a DDIL link the other half matters more. The
estimator can only sample while the cloud is reachable. During an outage it carries the last
offset forward while the device keeps drifting, and an air-gapped deployment never samples at
all. A corrected-looking timestamp from a device that has not seen a clock in three days
invites trust it has not earned, so every reading now carries what its time is actually
worth: `synced`, `holdover`, or `unsynced`.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from opsgrid_agent.main import EdgeAgent
from opsgrid_agent.timesync import ClockSkewEstimator

pytestmark = pytest.mark.ddil

STAMP = "2026-08-18T10:00:00+00:00"


class _Agent:
    """Only what `_time_fields` reads."""

    def __init__(self, skew):
        self._skew = skew
        self._time_fields = EdgeAgent._time_fields.__get__(self)


def _calibrated(offset_seconds: float, *, sampled_ago: float = 0.0) -> ClockSkewEstimator:
    estimator = ClockSkewEstimator()
    now = datetime.now(timezone.utc) - timedelta(seconds=sampled_ago)
    estimator.observe(now, now + timedelta(seconds=offset_seconds))
    return estimator


class TestTheCorrectionIsActuallyApplied:
    def test_a_synced_agent_shifts_the_timestamp_by_the_offset(self):
        fields = _Agent(_calibrated(12.0))._time_fields(STAMP)
        assert fields["time_quality"] == "synced"
        assert fields["clock_offset_seconds"] == 12.0
        assert fields["timestamp_edge"] == "2026-08-18T10:00:12+00:00", (
            "the offset was computed and not applied — which is precisely the state this "
            "item exists to end, and the state the module docstring denied for years"
        )

    def test_the_raw_edge_clock_is_preserved_beside_it(self):
        """Ground truth survives. A corrected value derived from an estimate that later
        turns out to be wrong is only recoverable if the uncorrected one is still there."""
        fields = _Agent(_calibrated(12.0))._time_fields(STAMP)
        assert fields["timestamp_edge_raw"] == STAMP
        assert fields["timestamp_edge"] != fields["timestamp_edge_raw"]

    def test_a_negative_offset_moves_the_timestamp_backwards(self):
        fields = _Agent(_calibrated(-30.0))._time_fields(STAMP)
        assert fields["timestamp_edge"] == "2026-08-18T09:59:30+00:00"

    def test_the_buffered_row_is_not_rewritten(self):
        """Correction happens at SEND, not at store. The offset current when a reading was
        taken is not the offset current when it is finally delivered — during a three-day
        outage the estimator has no samples at all — and rewriting the row in place would
        destroy the only unambiguous value in the record."""
        agent = _Agent(_calibrated(5.0))
        first = agent._time_fields(STAMP)
        agent._skew.observe(datetime.now(timezone.utc),
                            datetime.now(timezone.utc) + timedelta(seconds=60))
        second = agent._time_fields(STAMP)

        assert first["timestamp_edge_raw"] == second["timestamp_edge_raw"] == STAMP
        assert first["timestamp_edge"] != second["timestamp_edge"], (
            "the same buffered row produced the same corrected time after the estimate "
            "changed, so the correction is not being taken from the current estimate"
        )


class TestWhatTheTimeIsWorth:
    def test_an_agent_that_has_never_seen_a_server_says_unsynced(self):
        fields = _Agent(ClockSkewEstimator())._time_fields(STAMP)
        assert fields["time_quality"] == "unsynced"
        assert fields["clock_offset_seconds"] == 0.0
        assert fields["timestamp_edge"] == STAMP, (
            "an unsynced agent applied a correction. There is nothing to correct BY, so any "
            "shift is invention"
        )

    def test_an_agent_with_no_estimator_at_all_says_unsynced(self):
        assert _Agent(None)._time_fields(STAMP)["time_quality"] == "unsynced"

    def test_a_stale_sample_degrades_to_holdover(self):
        """The DDIL state. The offset is still the best available and it is no longer
        current, and a reading labelled `synced` in that state is the silent lie this whole
        item is about."""
        estimator = _calibrated(12.0, sampled_ago=600)
        fields = _Agent(estimator)._time_fields(STAMP)
        assert fields["time_quality"] == "holdover"
        assert fields["clock_offset_seconds"] == 12.0
        assert fields["timestamp_edge"] == "2026-08-18T10:00:12+00:00", (
            "holdover still applies the last known offset — it is the best estimate there "
            "is. What changes is that the reading says so."
        )

    def test_the_freshness_boundary_is_where_it_says_it_is(self):
        estimator = ClockSkewEstimator(freshness_seconds=100.0)
        now = datetime.now(timezone.utc)
        estimator.observe(now, now + timedelta(seconds=3))
        assert estimator.quality(now + timedelta(seconds=99)) == "synced"
        assert estimator.quality(now + timedelta(seconds=101)) == "holdover"

    def test_a_recovered_link_returns_to_synced(self):
        """The control case. A quality that only ever degrades would pass every assertion
        above and mark a healthy fleet as permanently untrustworthy."""
        estimator = _calibrated(12.0, sampled_ago=600)
        assert estimator.quality() == "holdover"
        now = datetime.now(timezone.utc)
        estimator.observe(now, now + timedelta(seconds=12))
        assert estimator.quality() == "synced"


class TestItDoesNotCompoundAnExistingDefect:
    def test_an_unparseable_stored_timestamp_is_passed_through_unchanged(self):
        """A stored timestamp we cannot read is its own defect. Inventing a corrected value
        for it would turn an obviously broken row into a plausible one."""
        fields = _Agent(_calibrated(12.0))._time_fields("not-a-timestamp")
        assert fields["timestamp_edge"] == "not-a-timestamp"
        assert fields["timestamp_edge_raw"] == "not-a-timestamp"
        assert fields["time_quality"] == "synced"

    def test_a_zero_offset_leaves_the_timestamp_byte_identical(self):
        """A calibrated agent on a perfectly-set clock must not reformat the timestamp.
        Round-tripping through `fromisoformat`/`isoformat` can change the spelling, and a
        changed spelling for an unchanged instant is churn that looks like a correction."""
        estimator = ClockSkewEstimator()
        now = datetime.now(timezone.utc)
        estimator.observe(now, now)
        fields = _Agent(estimator)._time_fields(STAMP)
        assert fields["clock_offset_seconds"] == 0.0
        assert fields["timestamp_edge"] == STAMP


class TestTheEstimatorItself:
    def test_correct_is_no_longer_a_method_nobody_calls(self):
        """The finding, asserted. `correct()` existed with a docstring describing behaviour
        the agent did not have; this is the guard that it stays wired."""
        import pathlib

        source = (pathlib.Path(__file__).resolve().parents[2]
                  / "opsgrid_agent" / "main.py").read_text()
        assert "_time_fields" in source and "self._skew.quality()" in source, (
            "the skew estimate is no longer consulted when a reading is sent; the "
            "correction has gone back to being computed and discarded"
        )

    def test_observing_records_when_rather_than_only_what(self):
        estimator = ClockSkewEstimator()
        assert estimator.last_observed_at is None
        now = datetime.now(timezone.utc)
        estimator.observe(now, now + timedelta(seconds=1))
        assert estimator.last_observed_at == now, (
            "without the sample TIME there is no way to tell a current offset from one "
            "carried through a three-day outage, and `holdover` cannot exist"
        )


class TestTheGuardIsRealAndNotIncidental:
    """`if offset and quality != "unsynced"` — the second clause, held on its own.

    A mutation removing it survived, because `ClockSkewEstimator` reports `unsynced` exactly
    when its offset is `None`, and `offset_seconds` is then `0.0` — so the first clause
    happens to cover the second. That is true of today's estimator and is not the invariant.
    An estimator that retained a last-known offset across a reset, or any other clock source
    plugged into this duck-typed slot, would report `unsynced` with a non-zero offset and
    silently start correcting again.

    The contract is "never correct when the clock is unsynced", so it is asserted against
    the contract rather than against the one implementation that makes it redundant.
    """

    class _UnsyncedButOffset:
        offset_seconds = 99.0

        @staticmethod
        def quality(now=None):
            return "unsynced"

    def test_an_unsynced_source_reporting_an_offset_still_corrects_nothing(self):
        fields = _Agent(self._UnsyncedButOffset())._time_fields(STAMP)
        assert fields["time_quality"] == "unsynced"
        assert fields["timestamp_edge"] == STAMP, (
            "a source that says it is unsynced had its offset applied anyway. Whatever that "
            "number is, it is not a measured correction."
        )


class TestTheBackfillActuallyAttachesThem:
    """The call site, not the function — FS-759's lesson, one item later.

    Removing `value.update(self._time_fields(...))` from the backfill loop left every
    assertion above green: `_time_fields` was thoroughly tested and nothing checked that
    anything called it. That is exactly the shape `compression.py` had for a year.
    """

    class _Harness:
        def __init__(self, skew):
            from opsgrid_agent.main import EdgeAgent

            self._running = True
            self._skew = skew
            self.kafka_producer = self
            self.coordinator = type("C", (), {"kafka_producer": None})()
            self.config = {'organization_id': 'org-1'}
            self._uplink_failure_streak = 0
            self._draining = False
            self._backfill_batch = 100
            self.sent = []
            self._served = False
            self.buffer = self
            self._backfill_worker = EdgeAgent._backfill_worker.__get__(self)
            self._time_fields = EdgeAgent._time_fields.__get__(self)

        async def get_pending_messages(self, batch_size=100, max_retry=5):
            from opsgrid_agent.buffer.store_forward import BufferedMessage

            if self._served:
                return []
            self._served = True
            return [BufferedMessage(id=1, timestamp_edge=STAMP, asset_id="press-01",
                                    topic="telemetry", payload='{"vibration": 1.0}',
                                    sequence_num=0)]

        async def mark_sent(self, ids):
            return None

        async def increment_retry(self, ids):
            return None

        async def send(self, topic, value=None, key=None):
            self.sent.append(value)

        async def _recycle_uplink(self):
            return None

        async def run(self):
            import asyncio as _asyncio
            from unittest.mock import patch as _patch

            real_sleep = _asyncio.sleep
            waits = []

            async def fake_sleep(delay):
                waits.append(delay)
                if len(waits) >= 3:
                    self._running = False
                await real_sleep(0)

            with _patch("opsgrid_agent.main.asyncio.sleep", fake_sleep):
                await self._backfill_worker()

    def test_a_backfilled_reading_carries_its_time_quality(self):
        import asyncio

        harness = self._Harness(_calibrated(12.0))
        asyncio.run(harness.run())

        assert harness.sent, "nothing was sent; the harness is not exercising the loop"
        value = harness.sent[0]
        assert value["time_quality"] == "synced", value
        assert value["timestamp_edge"] == "2026-08-18T10:00:12+00:00", value
        assert value["timestamp_edge_raw"] == STAMP, value
        assert value["clock_offset_seconds"] == 12.0, value

    def test_an_unsynced_agents_reading_says_so_on_the_wire(self):
        import asyncio

        harness = self._Harness(ClockSkewEstimator())
        asyncio.run(harness.run())

        value = harness.sent[0]
        assert value["time_quality"] == "unsynced"
        assert value["timestamp_edge"] == value["timestamp_edge_raw"] == STAMP

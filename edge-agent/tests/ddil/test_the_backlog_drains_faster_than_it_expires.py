"""S5 — the recovery rate was the data-loss mechanism (FS-757).

MEASURED FIRST, from the constants that were in `main.py`:

    batch_size=100, sleep(5), unconditionally  ->  20 messages/second, always

    72h outage @ 10 msg/s = 2,592,000 rows -> 36.0h to drain, retention deletes at 24h
    24h outage @ 50 msg/s = 4,320,000 rows -> 60.0h to drain, retention deletes at 24h
    steady 50 msg/s ingest: drain 20 - ingest 50 = -30 msg/s -> NEVER CATCHES UP

The last line is the one that reframes this. It is not "recovery is slow after an outage".
The agent could not keep up with its own collectors at 50 readings per second **with a
perfectly healthy link** — the buffer grows forever and the cleaner deletes the oldest end
of it, so the system silently converts a throughput shortfall into permanent data loss and
reports nothing wrong.

And during any recovery long enough to matter, the drain and the retention cleaner race for
the same rows. The backlog is by definition the oldest data in the buffer, which is exactly
what age-based expiry deletes first.

THREE CHANGES, each with scenarios below:

  1. Pace from the backlog. Full batch -> double it and take a 0.05s breath; short batch ->
     back to idle. The 0.05s is not zero: a drain that never yields starves the collectors
     sharing the loop, and the readings still arriving are the ones most likely to matter.
  2. Suspend AGE-based expiry while draining. The bound is not removed — the size cap still
     runs, and since FS-754 it sheds by priority, so a buffer that cannot drain gives up
     debug and bulk telemetry rather than its alarms. Shedding the cheapest is a better
     answer than shedding the oldest, which is all age can express.
  3. Stop counting link failures against individual messages. `get_pending_messages` filters
     `retry_count < 5`, so five failures hide a row forever — and five failures against a
     broker that is reachable but rejecting is an ordinary degraded reconnect. That is the
     stranded-backlog finding recorded under FS-753, and this is its decision.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pytest

from opsgrid_agent.buffer.store_forward import StoreForwardBuffer
from opsgrid_agent.main import (
    BACKFILL_IDLE_BATCH,
    BACKFILL_IDLE_SLEEP,
    BACKFILL_MAX_BATCH,
    _is_transport_failure,
)

pytestmark = pytest.mark.ddil

#: What the loop used to give, whatever was pending.
OLD_CEILING_MSG_PER_SEC = 100 / 5


class _Drainer:
    """The real `_backfill_worker`, with a real buffer and a scripted producer."""

    def __init__(self, buffer, *, fail_with=None, fail_first_batches=0):
        from opsgrid_agent.main import EdgeAgent

        self._running = True
        self.buffer = buffer
        self.kafka_producer = self
        self.coordinator = type("C", (), {"kafka_producer": None})()
        self.config = {'organization_id': 'org-1'}
        self._uplink_failure_streak = 0
        self._draining = False
        self._backfill_batch = BACKFILL_IDLE_BATCH
        self.sent = 0
        self.batches = []
        self.waits = []
        self.recycled = 0
        self._fail_with = fail_with
        self._fail_first_batches = fail_first_batches
        self._batch_index = 0
        self._backfill_worker = EdgeAgent._backfill_worker.__get__(self)

    async def send(self, topic, value=None, key=None):
        if self._fail_with is not None and self._batch_index <= self._fail_first_batches:
            raise self._fail_with
        self.sent += 1

    async def _recycle_uplink(self):
        self.recycled += 1
        self._uplink_failure_streak = 0

    async def run(self, *, cycles: int):
        real_sleep = asyncio.sleep
        original = self.buffer.get_pending_messages

        async def counting_fetch(batch_size=100, max_retry=5):
            self._batch_index += 1
            rows = await original(batch_size=batch_size, max_retry=max_retry)
            self.batches.append((batch_size, len(rows)))
            return rows

        async def fake_sleep(delay):
            self.waits.append(delay)
            if len(self.waits) >= cycles:
                self._running = False
            await real_sleep(0)

        self.buffer.get_pending_messages = counting_fetch
        try:
            with patch("opsgrid_agent.main.asyncio.sleep", fake_sleep):
                await self._backfill_worker()
        finally:
            self.buffer.get_pending_messages = original


def _buffer(directory: str, **kwargs) -> StoreForwardBuffer:
    return StoreForwardBuffer(buffer_path=str(Path(directory) / "buffer.db"), **kwargs)


def _seed(buffer, count: int, *, age_hours: float = 0.0):
    base = datetime.now(timezone.utc) - timedelta(hours=age_hours)
    created = (datetime.now(timezone.utc) - timedelta(hours=age_hours)).strftime(
        "%Y-%m-%d %H:%M:%S"
    )
    with sqlite3.connect(buffer.buffer_path) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executemany(
            "INSERT INTO messages (timestamp_edge, asset_id, topic, payload, "
            "sequence_num, priority, created_at) VALUES (?, ?, ?, ?, ?, 4, ?)",
            [
                (
                    (base + timedelta(milliseconds=i)).isoformat(),
                    "press-01",
                    "telemetry",
                    buffer.cipher.encrypt(json.dumps({"seq": i, "vibration": 0.1})),
                    i,
                    created,
                )
                for i in range(count)
            ],
        )
        conn.commit()


def _pending(buffer) -> int:
    with sqlite3.connect(buffer.buffer_path) as conn:
        return conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]


class TestTheCeilingIsGone:
    def test_the_batch_grows_while_there_is_a_backlog(self):
        with TemporaryDirectory() as directory:
            buffer = _buffer(directory)
            _seed(buffer, 20_000)

            drainer = _Drainer(buffer)
            asyncio.run(drainer.run(cycles=12))

            asked = [size for size, _ in drainer.batches]
            assert asked[0] == BACKFILL_IDLE_BATCH, asked[:3]
            assert max(asked) > BACKFILL_IDLE_BATCH * 4, (
                f"the batch never grew past {max(asked)}; this is still a fixed-rate drain "
                f"({asked[:8]})"
            )
            assert max(asked) <= BACKFILL_MAX_BATCH, asked

    def test_it_moves_far_more_than_the_old_ceiling_in_the_same_number_of_cycles(self):
        """The measurement the item exists for. Twelve cycles at the old pacing moved
        1,200 rows and took 60 seconds of wall clock doing it."""
        with TemporaryDirectory() as directory:
            buffer = _buffer(directory)
            _seed(buffer, 20_000)

            drainer = _Drainer(buffer)
            asyncio.run(drainer.run(cycles=12))

            old_would_have_sent = 12 * BACKFILL_IDLE_BATCH
            assert drainer.sent > old_would_have_sent * 5, (
                f"drained {drainer.sent} rows in 12 cycles; the old fixed pacing would "
                f"have moved {old_would_have_sent}. This is not an improvement worth the "
                "change."
            )

    def test_it_yields_rather_than_monopolising_the_loop(self):
        """A drain that never sleeps starves the collectors sharing this event loop. The
        readings still arriving are the ones most likely to matter, so the fast path takes
        a small breath rather than none."""
        with TemporaryDirectory() as directory:
            buffer = _buffer(directory)
            _seed(buffer, 20_000)

            drainer = _Drainer(buffer)
            asyncio.run(drainer.run(cycles=10))

            assert all(w > 0 for w in drainer.waits), (
                f"a zero-length wait appeared ({drainer.waits}); the drain can starve the "
                "collectors it shares a loop with"
            )
            # The tail of the run catches up and takes the idle sleep, which is correct —
            # so this asserts about the DRAINING waits rather than all of them. Written the
            # other way first, and it failed on a buffer that emptied inside ten cycles:
            # the assertion was about the wrong phase, not about a defect.
            draining_waits = [w for w in drainer.waits if w < BACKFILL_IDLE_SLEEP]
            assert len(draining_waits) >= 5, (
                f"only {len(draining_waits)} short waits in {drainer.waits}; the drain is "
                "still taking the idle sleep between batches"
            )

    def test_the_drain_flag_is_raised_while_the_backlog_is_being_cleared(self):
        """Asserted directly, because the cleanup worker keys retention off this flag.

        The mutation that removed `self._draining = True` did fail the suite — but through
        an AttributeError in an unrelated harness that had not defined the attribute, which
        is a coincidence rather than a guard. A flag nothing asserts is a flag that can
        quietly stop being set.
        """
        with TemporaryDirectory() as directory:
            buffer = _buffer(directory)
            _seed(buffer, 20_000)

            drainer = _Drainer(buffer)
            seen = []
            real_run = drainer.run

            asyncio.run(drainer.run(cycles=4))
            assert drainer._draining is True, (
                "the buffer holds 20,000 rows and four batches did not clear it, yet the "
                "drain flag is unset — so retention would delete the backlog underneath it"
            )

    def test_it_returns_to_the_idle_cadence_once_caught_up(self):
        """The control case. A loop that stayed at the maximum batch and the short sleep
        would pass every assertion above and poll an empty buffer 20 times a second."""
        with TemporaryDirectory() as directory:
            buffer = _buffer(directory)
            _seed(buffer, 150)

            drainer = _Drainer(buffer)
            asyncio.run(drainer.run(cycles=6))

            assert drainer.waits[-1] == BACKFILL_IDLE_SLEEP, drainer.waits
            assert drainer._backfill_batch == BACKFILL_IDLE_BATCH
            assert drainer._draining is False


class TestRetentionDoesNotDeleteWhatTheDrainHasNotReached:
    def test_expiry_is_suspended_while_a_drain_is_in_progress(self):
        from opsgrid_agent.main import EdgeAgent

        with TemporaryDirectory() as directory:
            buffer = _buffer(directory, retention_hours=1)
            _seed(buffer, 5_000, age_hours=48)

            agent = type("A", (), {})()
            agent._running = True
            agent.buffer = buffer
            agent._draining = True
            cleanup = EdgeAgent._cleanup_worker.__get__(agent)

            async def stop_after_one(delay):
                agent._running = False

            with patch("opsgrid_agent.main.asyncio.sleep", stop_after_one):
                asyncio.run(cleanup())

            assert _pending(buffer) == 5_000, (
                "retention deleted rows while a drain was in progress. The backlog IS the "
                "oldest data in the buffer, so age-based expiry and the drain are racing "
                "for the same rows — and at the old 20 msg/s the cleaner won."
            )

    def test_expiry_resumes_when_the_drain_finishes(self):
        """The control case, and the one that matters: a suspension that never lifts is an
        unbounded buffer wearing a feature's name."""
        from opsgrid_agent.main import EdgeAgent

        with TemporaryDirectory() as directory:
            buffer = _buffer(directory, retention_hours=1)
            _seed(buffer, 500, age_hours=48)

            agent = type("A", (), {})()
            agent._running = True
            agent.buffer = buffer
            agent._draining = False
            cleanup = EdgeAgent._cleanup_worker.__get__(agent)

            async def stop_after_one(delay):
                agent._running = False

            with patch("opsgrid_agent.main.asyncio.sleep", stop_after_one):
                asyncio.run(cleanup())

            assert _pending(buffer) == 0, (
                "retention did not run on a caught-up buffer; the suspension is permanent "
                "and the buffer is now unbounded by age"
            )

    def test_the_drain_flag_clears_itself_when_the_backlog_does(self):
        with TemporaryDirectory() as directory:
            buffer = _buffer(directory)
            _seed(buffer, 300)

            drainer = _Drainer(buffer)
            asyncio.run(drainer.run(cycles=8))

            assert drainer._draining is False, (
                "the drain flag is still set after the buffer emptied, so retention would "
                "stay suspended forever"
            )

    def test_the_size_cap_is_still_enforced_while_expiry_is_suspended(self):
        """The bound is CHANGED, not removed.

        If suspending age-based expiry also stopped the size cap, a long outage would fill
        the disk — and the entire argument for suspending is that priority-shedding is a
        better bound than age, which only holds if priority-shedding still happens.

        Written first as a source-index comparison (`enforce_size_limit` must appear after
        the `_draining` check) and it failed, because the phrase also appears in the comment
        explaining the design. A test that greps for a word cannot tell code from prose.
        """
        from opsgrid_agent.main import EdgeAgent

        with TemporaryDirectory() as directory:
            buffer = _buffer(directory, retention_hours=1, max_size_mb=1)
            base = datetime.now(timezone.utc) - timedelta(hours=48)
            with sqlite3.connect(buffer.buffer_path) as conn:
                conn.execute("PRAGMA journal_mode=WAL")
                conn.executemany(
                    "INSERT INTO messages (timestamp_edge, asset_id, topic, payload, "
                    "sequence_num, priority) VALUES (?, ?, ?, ?, ?, 4)",
                    [
                        (
                            (base + timedelta(milliseconds=i)).isoformat(),
                            "press-01", "telemetry",
                            buffer.cipher.encrypt(
                                json.dumps({"seq": i, "vibration": 0.1, "pad": "x" * 512})
                            ),
                            i,
                        )
                        for i in range(4_000)
                    ],
                )
                conn.commit()
            before = _pending(buffer)

            agent = type("A", (), {})()
            agent._running = True
            agent.buffer = buffer
            agent._draining = True          # age-based expiry suspended
            cleanup = EdgeAgent._cleanup_worker.__get__(agent)

            async def stop_after_one(delay):
                agent._running = False

            with patch("opsgrid_agent.main.asyncio.sleep", stop_after_one):
                asyncio.run(cleanup())

            after = _pending(buffer)
            assert after < before, (
                f"the buffer is over its 1 MB cap and mid-drain, and nothing was shed "
                f"({before} -> {after}). Suspending age-based expiry has left it with no "
                "bound at all."
            )
            assert buffer.losses["dropped"] > 0


class TestALinkFailureIsNotAMessageFault:
    """The FS-753 stranded-backlog decision, taken here."""

    def test_a_transport_failure_does_not_burn_the_rows_retry_budget(self):
        with TemporaryDirectory() as directory:
            buffer = _buffer(directory)
            _seed(buffer, 50)

            drainer = _Drainer(buffer, fail_with=ConnectionResetError("broker gone"),
                               fail_first_batches=99)
            asyncio.run(drainer.run(cycles=4))

            with sqlite3.connect(buffer.buffer_path) as conn:
                counts = [r[0] for r in conn.execute("SELECT retry_count FROM messages")]
            assert set(counts) == {0}, (
                f"retry counts rose to {sorted(set(counts))} because the BROKER was down. "
                "Five of those and get_pending_messages stops returning the row entirely — "
                "an outage condemning the backlog it created."
            )

    def test_a_message_the_broker_refuses_still_counts_against_it(self):
        """The counter is not removed. A message that is too large or unserialisable will
        fail identically forever and must reach the dead-letter table."""
        with TemporaryDirectory() as directory:
            buffer = _buffer(directory)
            _seed(buffer, 50)

            drainer = _Drainer(buffer, fail_with=ValueError("message too large"),
                               fail_first_batches=99)
            asyncio.run(drainer.run(cycles=4))

            with sqlite3.connect(buffer.buffer_path) as conn:
                counts = [r[0] for r in conn.execute("SELECT retry_count FROM messages")]
            assert max(counts) >= 1, (
                "a message-level rejection did not increment retry_count, so a genuinely "
                "poisonous row would be retried forever and never dead-lettered"
            )

    def test_the_classifier_separates_the_two(self):
        class KafkaConnectionError(Exception):
            pass

        class MessageSizeTooLargeError(Exception):
            pass

        assert _is_transport_failure(KafkaConnectionError())
        assert _is_transport_failure(ConnectionResetError())
        assert _is_transport_failure(OSError("unreachable"))
        assert _is_transport_failure(asyncio.TimeoutError())
        assert not _is_transport_failure(MessageSizeTooLargeError())
        assert not _is_transport_failure(ValueError("unserialisable"))

    def test_a_reconnect_clears_the_counts_the_dead_link_left_behind(self):
        with TemporaryDirectory() as directory:
            buffer = _buffer(directory)
            _seed(buffer, 20)
            with sqlite3.connect(buffer.buffer_path) as conn:
                conn.execute("UPDATE messages SET retry_count = 5")
                conn.commit()

            assert asyncio.run(buffer.get_pending_messages()) == [], (
                "setup is wrong: rows at retry_count 5 should already be invisible"
            )

            cleared = asyncio.run(buffer.reset_retry_counts())

            assert cleared == 20
            assert len(asyncio.run(buffer.get_pending_messages())) == 20, (
                "the rows are still hidden after a reconnect. They were condemned by a "
                "producer that no longer exists."
            )

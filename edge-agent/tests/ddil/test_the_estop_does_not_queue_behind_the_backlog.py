"""S2 — what leaves first when the link comes back (FS-754).

THE DEFECT, stated as the scenario that motivated it. A press buffers vibration at 10 Hz
across a shift-long outage. Somebody hits the emergency stop. The link returns. The buffer
drained strictly by `timestamp_edge`, so the E-stop was row 400,001 of 400,001 — batch 401
of 401 at the production batch size, and at the measured backfill rate of 20 msg/s that is
**five and a half hours** behind the vibration samples recorded before it. The tiers that
would have fixed this already existed in `backend/app/services/data_shedding.py`, deciding
what the BACKEND sheds under load: correct tiers, wrong side of the link, applied only after
the data has already crossed the scarce resource.

These scenarios are graded by the FS-753 harness rather than by inspection, so the
conservation law still holds at the end of each one — reordering a queue is exactly the kind
of change that loses rows down the side.

WHY 400,000 ROWS ARE INSERTED IN BULK. `store()` runs at a measured 4,497 rows/s on this
machine, so producing the backlog through it would cost ~89s of a nightly run to prove
something already proved at 4,000. The bulk helper opens one connection and calls the SAME
`priority_for` the production insert calls, and `TestTheProductionPathClassifies` covers the
production path separately at small scale. The split is deliberate: scale is asserted where
scale matters (ordering), the code path is asserted where the path matters (classification).
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from opsgrid_agent.buffer.priority import priority_for
from opsgrid_agent.buffer.store_forward import StoreForwardBuffer

from .link import FakeUplink, LinkController, conservation, drain

pytestmark = pytest.mark.ddil

#: The production backfill batch size (`main.py`'s backfill loop).
PRODUCTION_BATCH = 100


def _buffer(directory: str, **kwargs) -> StoreForwardBuffer:
    return StoreForwardBuffer(buffer_path=str(Path(directory) / "buffer.db"), **kwargs)


def _bulk(buffer, count: int, *, metric: str, base: datetime, asset: str = "press-01"):
    """Insert `count` readings of one metric on a single connection.

    Priority comes from `priority_for` — the same call `_insert_row` makes — so this
    shortcut cannot accidentally classify rows in a way production would not.
    """
    payload_template = {"seq": 0, metric: 0.0}
    tier = priority_for("telemetry", payload_template)
    with sqlite3.connect(buffer.buffer_path) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executemany(
            "INSERT INTO messages "
            "(timestamp_edge, asset_id, topic, payload, sequence_num, priority) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [
                (
                    (base + timedelta(milliseconds=i)).isoformat(),
                    asset,
                    "telemetry",
                    buffer.cipher.encrypt(json.dumps({"seq": i, metric: 0.1 * i})),
                    i,
                    tier,
                )
                for i in range(count)
            ],
        )
        conn.commit()
    return tier


def _priorities(buffer) -> list:
    # ORDER BY id explicitly. Without it SQLite is free to answer from the new
    # `(priority, timestamp_edge)` index — a covering scan that returns rows already
    # sorted by tier, which made an assertion about insertion order pass by accident.
    with sqlite3.connect(buffer.buffer_path) as conn:
        return [
            row[0]
            for row in conn.execute("SELECT priority FROM messages ORDER BY id")
        ]


def _tier_counts(buffer) -> dict:
    with sqlite3.connect(buffer.buffer_path) as conn:
        return dict(
            conn.execute("SELECT priority, COUNT(*) FROM messages GROUP BY priority")
        )


class TestAnEmergencyStopDoesNotQueueBehindTheBacklog:
    """The headline. 400,000 buffered vibration samples, then an E-stop, then the link."""

    BACKLOG = 400_000

    def _loaded(self, directory):
        buffer = _buffer(directory)
        outage_start = datetime.now(timezone.utc) - timedelta(hours=11)
        _bulk(buffer, self.BACKLOG, metric="vibration", base=outage_start)
        # The E-stop happens LAST, at the end of the outage, through the production path.
        asyncio.run(
            buffer.store(
                timestamp_edge=datetime.now(timezone.utc),
                asset_id="press-01",
                topic="telemetry",
                payload={"emergency_stop": True, "reason": "light curtain"},
                sequence_num=self.BACKLOG,
            )
        )
        return buffer

    def test_the_estop_is_the_very_first_message_drained(self):
        with TemporaryDirectory() as directory:
            buffer = self._loaded(directory)
            uplink = FakeUplink(LinkController())

            asyncio.run(drain(buffer, uplink, batch_size=PRODUCTION_BATCH, rounds=1))

            assert uplink.sent == PRODUCTION_BATCH
            first = json.loads(uplink.delivered[0]["payload"])
            assert first.get("emergency_stop") is True, (
                "the E-stop was not the first message off the edge. Drained instead: "
                f"{first}. `get_pending_messages` must ORDER BY priority ASC before "
                "timestamp_edge, or a safety event waits behind every reading that "
                "happened to be recorded before it."
            )

    def test_under_the_old_fifo_order_it_would_have_been_batch_4001(self):
        """The denominator. Without this the headline could pass on a 3-row buffer and
        nobody would know the number it is supposed to be beating."""
        with TemporaryDirectory() as directory:
            buffer = self._loaded(directory)

            with sqlite3.connect(buffer.buffer_path) as conn:
                position = conn.execute(
                    """
                    SELECT COUNT(*) FROM messages
                    WHERE timestamp_edge <= (
                        SELECT MAX(timestamp_edge) FROM messages WHERE priority = 1
                    )
                    """
                ).fetchone()[0]

            assert position == self.BACKLOG + 1, position
            fifo_batches = -(-position // PRODUCTION_BATCH)  # ceil
            assert fifo_batches == 4001, fifo_batches
            # At main.py's backfill pacing — batch 100, sleep 5s — that is the wait the
            # tiers remove. Asserted so the docstring's claim is a measurement.
            fifo_seconds = fifo_batches * 5
            assert fifo_seconds > 5 * 3600, (
                f"{fifo_seconds}s; if this ever drops below hours the scenario has "
                "stopped representing the outage it was written for"
            )

    def test_the_books_still_balance_after_reordering_the_queue(self):
        with TemporaryDirectory() as directory:
            buffer = self._loaded(directory)
            uplink = FakeUplink(LinkController())

            asyncio.run(drain(buffer, uplink, batch_size=5_000, rounds=200))

            ledger = asyncio.run(conservation(buffer, uplink, self.BACKLOG + 1))
            assert ledger["unaccounted"] == 0, ledger
            assert ledger["sent"] == self.BACKLOG + 1, ledger


class TestTheDrainOrderItself:
    def test_tiers_come_off_in_order_and_never_interleave(self):
        with TemporaryDirectory() as directory:
            buffer = _buffer(directory)
            base = datetime.now(timezone.utc) - timedelta(hours=2)
            # Written WORST-FIRST, so insertion order is the exact inverse of drain order
            # and a buffer that ignored priority would fail visibly rather than by luck.
            for metric in ("debug", "vibration", "temp_bed", "job_status", "alarm"):
                _bulk(buffer, 40, metric=metric, base=base)
                base += timedelta(minutes=1)

            uplink = FakeUplink(LinkController())
            asyncio.run(drain(buffer, uplink, batch_size=200, rounds=1))

            tiers = []
            for message in uplink.delivered:
                payload = json.loads(message["payload"])
                tiers.append(priority_for("telemetry", payload))

            assert tiers == sorted(tiers), (
                "tiers interleaved in the drained stream: "
                f"{[t for t in tiers[:20]]}... — ORDER BY priority is not being applied"
            )
            assert tiers[:40] == [1] * 40 and tiers[-40:] == [5] * 40

    def test_within_one_tier_it_is_still_oldest_first(self):
        """Priority is the FIRST key, not the only one. If it silently replaced ordered
        delivery, every consumer that assumes per-asset ordering would break, and the
        headline test above would not notice."""
        with TemporaryDirectory() as directory:
            buffer = _buffer(directory)
            base = datetime.now(timezone.utc) - timedelta(hours=1)
            _bulk(buffer, 300, metric="vibration", base=base)

            uplink = FakeUplink(LinkController())
            asyncio.run(drain(buffer, uplink, batch_size=300, rounds=1))

            seqs = [json.loads(m["payload"])["seq"] for m in uplink.delivered]
            assert seqs == list(range(300)), seqs[:10]


class TestAFullBufferShedsTheCheapestData:
    """20% over the cap. Something has to go; it must not be the alarms."""

    def _fill(self, directory, cap_mb: int):
        buffer = _buffer(directory, max_size_mb=cap_mb)
        base = datetime.now(timezone.utc) - timedelta(hours=3)
        # Padded payloads: 4,000 scalar rows do not reach a megabyte, which is how the
        # FS-753 size-limit scenario originally passed while measuring nothing.
        with sqlite3.connect(buffer.buffer_path) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            for metric, count in (("alarm", 200), ("temp_bed", 200), ("vibration", 4_000)):
                tier = priority_for("telemetry", {metric: 0.0})
                conn.executemany(
                    "INSERT INTO messages (timestamp_edge, asset_id, topic, payload, "
                    "sequence_num, priority) VALUES (?, ?, ?, ?, ?, ?)",
                    [
                        (
                            (base + timedelta(milliseconds=i)).isoformat(),
                            "press-01",
                            "telemetry",
                            buffer.cipher.encrypt(
                                json.dumps({"seq": i, metric: 0.1, "pad": "x" * 512})
                            ),
                            i,
                            tier,
                        )
                        for i in range(count)
                    ],
                )
            conn.commit()
        return buffer

    def test_it_sheds_bulk_telemetry_and_leaves_the_alarms_alone(self):
        with TemporaryDirectory() as directory:
            buffer = self._fill(directory, cap_mb=2)
            before = _tier_counts(buffer)
            # `_on_disk_bytes`, not `buffer.db`'s size: in WAL mode the rows just written
            # are still in the sidecar, and measuring the main file alone reports 0.00 MB
            # for a buffer holding 2 MB. That was a real defect in `enforce_size_limit`
            # itself, found by this scenario and fixed alongside it.
            size_mb = buffer._on_disk_bytes(checkpoint=True) / (1024 * 1024)
            assert size_mb > 2 * 1.2, (
                f"buffer is only {size_mb:.2f} MB against a 2 MB cap — the scenario is not "
                "over the limit, so nothing would be shed and this would pass vacuously"
            )

            pruned = asyncio.run(buffer.enforce_size_limit())

            after = _tier_counts(buffer)
            assert pruned > 0, "nothing was shed; the size limit did not engage"
            assert after.get(1, 0) == before[1], (
                f"alarms were shed: {before[1]} -> {after.get(1, 0)}. A full buffer that "
                "discards safety data to keep vibration samples has inverted its purpose."
            )
            assert after.get(3, 0) == before[3], (
                f"process data was shed while tier-4 rows remained: {after}"
            )
            assert after.get(4, 0) < before[4], after

    def test_the_shed_is_counted_so_the_books_balance(self):
        with TemporaryDirectory() as directory:
            buffer = self._fill(directory, cap_mb=2)
            produced = sum(_tier_counts(buffer).values())
            uplink = FakeUplink(LinkController())

            pruned = asyncio.run(buffer.enforce_size_limit())
            asyncio.run(drain(buffer, uplink, batch_size=1_000, rounds=50))

            ledger = asyncio.run(conservation(buffer, uplink, produced))
            assert ledger["dropped"] == pruned, ledger
            assert ledger["unaccounted"] == 0, ledger

    def test_the_disk_full_prune_also_sheds_cheapest_first(self):
        """A SECOND prune path, and it needed its own scenario.

        `enforce_size_limit` is the hourly cycle; `_prune_oldest_sync` is the emergency one,
        called when an INSERT hits SQLITE_FULL. Reverting the ORDER BY on this one alone
        left every other scenario green — the same hole FS-753 found when deleting a loss
        counter passed eight scenarios out of eight."""
        with TemporaryDirectory() as directory:
            buffer = _buffer(directory)
            base = datetime.now(timezone.utc) - timedelta(hours=6)
            # The alarms are the OLDEST rows, so age-ordered pruning takes them first and
            # priority-ordered pruning takes none of them.
            for metric in ("alarm", "vibration", "debug"):
                _bulk(buffer, 300, metric=metric, base=base)
                base += timedelta(hours=1)
            before = _tier_counts(buffer)

            pruned = buffer._prune_oldest_sync(400)

            after = _tier_counts(buffer)
            assert pruned == 400, pruned
            assert after.get(1, 0) == before[1], (
                f"the disk-full path discarded alarms first: {before[1]} -> "
                f"{after.get(1, 0)}. They are the oldest rows, which is exactly why "
                "age-ordered pruning gets this backwards."
            )
            assert after.get(5, 0) == 0, "tier-5 debug should have gone first"
            assert buffer.losses["dropped"] == 400

    def test_when_only_protected_tiers_are_left_it_still_sheds(self):
        """The documented trade. Refusing to shed tier 1 would leave the buffer over its
        cap, and the next INSERT — possibly the NEXT E-stop — would fail. A stale safety
        record is given up to keep taking live ones, and the warning makes it visible."""
        with TemporaryDirectory() as directory:
            buffer = _buffer(directory, max_size_mb=1)
            base = datetime.now(timezone.utc) - timedelta(hours=3)
            with sqlite3.connect(buffer.buffer_path) as conn:
                conn.execute("PRAGMA journal_mode=WAL")
                conn.executemany(
                    "INSERT INTO messages (timestamp_edge, asset_id, topic, payload, "
                    "sequence_num, priority) VALUES (?, ?, ?, ?, ?, 1)",
                    [
                        (
                            (base + timedelta(milliseconds=i)).isoformat(),
                            "press-01",
                            "telemetry",
                            buffer.cipher.encrypt(
                                json.dumps({"seq": i, "alarm": "HIGH", "pad": "x" * 512})
                            ),
                            i,
                        )
                        for i in range(4_000)
                    ],
                )
                conn.commit()

            pruned = asyncio.run(buffer.enforce_size_limit())

            assert pruned > 0, (
                "the buffer stayed over its cap rather than shed tier-1 rows. That is a "
                "deadlock, not a safeguard: the next reading cannot be stored."
            )
            assert buffer.losses["dropped"] == pruned


class TestTheProductionPathClassifies:
    """Covers the insert the bulk helper shortcuts past."""

    def test_store_writes_the_tier(self):
        with TemporaryDirectory() as directory:
            buffer = _buffer(directory)
            now = datetime.now(timezone.utc)
            for payload, expected in (
                ({"emergency_stop": True}, 1),
                ({"vibration": 1.0}, 4),
                ({"debug": "x"}, 5),
                ({"unclassified_thing": 1}, 3),
            ):
                asyncio.run(
                    buffer.store(
                        timestamp_edge=now,
                        asset_id="press-01",
                        topic="telemetry",
                        payload=payload,
                        sequence_num=0,
                    )
                )
            assert _priorities(buffer) == [1, 4, 5, 3]

    def test_store_message_writes_the_tier(self):
        with TemporaryDirectory() as directory:
            buffer = _buffer(directory)
            asyncio.run(
                buffer.store_message(
                    {
                        "asset_id": "press-01",
                        "topic": "telemetry",
                        "payload": {"alarm": "E_STOP_PRESSED"},
                        "timestamp_edge": datetime.now(timezone.utc).isoformat(),
                    }
                )
            )
            assert _priorities(buffer) == [1]

    def test_get_pending_messages_carries_the_tier_to_the_caller(self):
        with TemporaryDirectory() as directory:
            buffer = _buffer(directory)
            asyncio.run(
                buffer.store(
                    timestamp_edge=datetime.now(timezone.utc),
                    asset_id="press-01",
                    topic="telemetry",
                    payload={"vibration": 1.0},
                )
            )
            pending = asyncio.run(buffer.get_pending_messages())
            assert pending[0].priority == 4


class TestABufferWrittenBeforeThisRelease:
    """An agent in the field is routinely older than the release it is upgraded to."""

    def test_the_column_is_added_and_old_rows_become_process_data(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "buffer.db"
            # The pre-FS-754 schema, verbatim.
            with sqlite3.connect(path) as conn:
                conn.execute(
                    """
                    CREATE TABLE messages (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp_edge TEXT NOT NULL,
                        asset_id TEXT NOT NULL,
                        topic TEXT NOT NULL,
                        payload TEXT NOT NULL,
                        sequence_num INTEGER NOT NULL,
                        retry_count INTEGER DEFAULT 0,
                        created_at TEXT DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
                conn.execute(
                    "INSERT INTO messages (timestamp_edge, asset_id, topic, payload, "
                    "sequence_num) VALUES ('2026-08-01T00:00:00', 'a', 'telemetry', "
                    "'{\"vibration\": 1.0}', 1)"
                )
                conn.commit()

            buffer = StoreForwardBuffer(buffer_path=str(path))

            with sqlite3.connect(path) as conn:
                columns = {row[1] for row in conn.execute("PRAGMA table_info(messages)")}
                assert "priority" in columns, "the migration did not run"
                assert conn.execute("SELECT priority FROM messages").fetchone()[0] == 3

            # And a new row on the migrated buffer classifies normally.
            asyncio.run(
                buffer.store(
                    timestamp_edge=datetime.now(timezone.utc),
                    asset_id="a",
                    topic="telemetry",
                    payload={"emergency_stop": True},
                )
            )
            assert sorted(_priorities(buffer)) == [1, 3]


class TestTheDrainOrderIsIndexed:
    """Correct and unusably slow is the same defect wearing a different hat.

    The headline scenario buffers 400,000 rows. If `ORDER BY priority, timestamp_edge`
    falls back to sorting the whole table into a temporary b-tree on every batch fetch,
    the E-stop still comes out first — after SQLite has sorted 400,000 rows, 4,001 times
    over the course of the drain. No assertion about ordering can catch that, so the plan
    is asserted directly.
    """

    def test_the_pending_query_does_not_sort_the_whole_table(self):
        with TemporaryDirectory() as directory:
            buffer = _buffer(directory)
            _bulk(buffer, 50, metric="vibration",
                  base=datetime.now(timezone.utc) - timedelta(hours=1))

            with sqlite3.connect(buffer.buffer_path) as conn:
                plan = " ".join(
                    row[3]
                    for row in conn.execute(
                        "EXPLAIN QUERY PLAN SELECT * FROM messages WHERE retry_count < 5 "
                        "ORDER BY priority ASC, timestamp_edge ASC LIMIT 100"
                    )
                )

            assert "idx_messages_priority" in plan, (
                f"the drain order is not served by an index. Plan: {plan}"
            )
            assert "TEMP B-TREE" not in plan.upper(), (
                f"every batch fetch sorts the entire backlog. Plan: {plan}"
            )


class TestTheReportedSizeIncludesTheWriteAheadLog:
    """The surviving mutant, closed.

    `enforce_size_limit` truncates the WAL before measuring, so folding the sidecars into
    the total is belt-and-braces there — deleting that part of `_on_disk_bytes` left every
    shed scenario green. It is NOT belt-and-braces on the read-only path: `get_stats()`
    deliberately does not checkpoint (it runs on a metrics interval and should not mutate
    files), so without the sidecars it reports a buffer holding megabytes as 0.0 MB. That
    number is what an operator sizes an edge partition from, and what a dashboard alerts on.
    """

    def test_stats_do_not_report_a_full_buffer_as_empty(self):
        with TemporaryDirectory() as directory:
            buffer = _buffer(directory)
            base = datetime.now(timezone.utc) - timedelta(hours=1)
            with sqlite3.connect(buffer.buffer_path) as conn:
                conn.execute("PRAGMA journal_mode=WAL")
                conn.executemany(
                    "INSERT INTO messages (timestamp_edge, asset_id, topic, payload, "
                    "sequence_num, priority) VALUES (?, ?, ?, ?, ?, 4)",
                    [
                        (
                            (base + timedelta(milliseconds=i)).isoformat(),
                            "press-01",
                            "telemetry",
                            buffer.cipher.encrypt(
                                json.dumps({"seq": i, "vibration": 0.1, "pad": "x" * 512})
                            ),
                            i,
                        )
                        for i in range(2_000)
                    ],
                )
                conn.commit()

            main_only_mb = Path(buffer.buffer_path).stat().st_size / (1024 * 1024)
            assert main_only_mb < 0.5, (
                f"the main file is already {main_only_mb:.2f} MB, so SQLite checkpointed "
                "and this scenario is no longer measuring the un-checkpointed case"
            )

            stats = asyncio.run(buffer.get_stats())

            assert stats["total_messages"] == 2_000, stats
            assert stats["size_mb"] >= 1.0, (
                f"get_stats reported {stats['size_mb']} MB for a buffer holding 2,000 "
                "padded readings. The content is in buffer.db-wal; measuring buffer.db "
                "alone reports near-zero disk use for a device that is filling up."
            )

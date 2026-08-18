"""DDIL scenarios, each ending with the books balanced (FS-753).

Run nightly, not per-PR: `pytest -m ddil`. These are the measurements the remaining DDIL
items are graded against, so they exist before the work rather than after it — otherwise
"survives a 72-hour outage" gets settled by reading the code, which is how "the buffer
handles outages" became a belief nobody had tested.

EVERY SCENARIO ASSERTS THE SAME LAW:

    produced == sent + still_buffered + dead_lettered + dropped + expired

A message that is neither delivered, nor held, nor deliberately discarded AND counted, has
vanished. Silent loss is the failure DDIL exists to prevent, and it is invisible from any
single counter — only the balance catches it.

WHAT THESE DO NOT COVER, so a green run is not over-read: there is no TCP here. Half-open
connections, DNS failure, TLS renegotiation and kernel buffer exhaustion need toxiproxy or
`tc netem` in front of a real broker. That is a follow-on; this version is deterministic,
fast and dependency-free, which is what makes it something that gets run.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from opsgrid_agent.buffer.store_forward import StoreForwardBuffer

from .link import FakeUplink, LinkController, conservation, drain

pytestmark = pytest.mark.ddil


def _buffer(directory: str, **kwargs) -> StoreForwardBuffer:
    return StoreForwardBuffer(buffer_path=str(Path(directory) / "buffer.db"), **kwargs)


async def _produce(
    buffer,
    count: int,
    *,
    age_hours: float = 0.0,
    asset: str = "asset-1",
    payload_bytes: int = 0,
):
    """Write `count` readings, optionally stamped in the past.

    TIME IS COMPRESSED RATHER THAN WAITED. A 72-hour outage is a timestamp, not three days
    of sleeping — which is the only reason a scenario representing three days can live in
    CI at all.
    """
    base = datetime.now(timezone.utc) - timedelta(hours=age_hours)
    for index in range(count):
        await buffer.store(
            timestamp_edge=base + timedelta(milliseconds=index),
            asset_id=asset,
            topic="telemetry",
            payload=(
                {"seq": index, "value": 20.0 + index}
                if not payload_bytes
                # Padding, for scenarios about SIZE rather than count. A vibration or
                # audio frame is kilobytes, not the dozen bytes a scalar reading takes,
                # and the buffer's cap is in megabytes — so a size scenario built from
                # scalar rows needs implausible counts to reach the boundary.
                else {"seq": index, "value": 20.0 + index, "frame": "x" * payload_bytes}
            ),
            sequence_num=index,
        )


def _assert_balanced(ledger: dict, note: str = "") -> None:
    assert ledger["unaccounted"] == 0, (
        f"{ledger['unaccounted']} message(s) vanished{' — ' + note if note else ''}.\n"
        f"  produced        {ledger['produced']}\n"
        f"  sent            {ledger['sent']}\n"
        f"  still buffered  {ledger['still_buffered']}\n"
        f"  dead lettered   {ledger['dead_lettered']}\n"
        f"  dropped         {ledger['dropped']}\n"
        f"  expired         {ledger['expired']}\n"
        f"Every message must be delivered, held, or deliberately discarded AND counted."
    )


class TestDenied:
    def test_nothing_is_lost_while_the_link_is_down(self):
        with TemporaryDirectory() as directory:
            buffer = _buffer(directory)
            link = LinkController(denied=True)
            uplink = FakeUplink(link)

            asyncio.run(_produce(buffer, 500))
            asyncio.run(drain(buffer, uplink, rounds=3))

            assert uplink.sent == 0, "the link was denied and something got through"
            ledger = asyncio.run(conservation(buffer, uplink, 500))
            _assert_balanced(ledger, "a denied link must hold, not drop")
            assert ledger["still_buffered"] == 500

    def test_a_72_hour_outage_drains_completely_when_the_link_returns(self):
        """The headline DDIL scenario. Retention is 24h by default, so this deliberately
        runs with a retention long enough to hold the backlog — the point here is that the
        DRAIN is complete. Whether the default retention can outrun the drain rate is the
        separate finding recorded against S5, and is measured below."""
        with TemporaryDirectory() as directory:
            buffer = _buffer(directory, retention_hours=96)
            link = LinkController(denied=True)
            uplink = FakeUplink(link)

            asyncio.run(_produce(buffer, 2_000, age_hours=72))
            # One attempt, not five. The real backfill worker does not call send at all
            # when the producer is absent (`if self.kafka_producer:`), so a fully denied
            # link does not burn the retry budget. Draining repeatedly against a denied
            # link is a DIFFERENT scenario — broker reachable but rejecting — and it
            # strands rows, which `TestRetryExhaustion` below measures deliberately.
            asyncio.run(drain(buffer, uplink, rounds=1))
            assert uplink.sent == 0

            link.restore()
            asyncio.run(drain(buffer, uplink, batch_size=500, rounds=20))

            ledger = asyncio.run(conservation(buffer, uplink, 2_000))
            _assert_balanced(ledger, "after a 72-hour denial")
            assert ledger["still_buffered"] == 0, "the backlog did not fully drain"
            assert ledger["sent"] == 2_000


class TestIntermittent:
    def test_a_lossy_link_eventually_delivers_everything(self):
        with TemporaryDirectory() as directory:
            buffer = _buffer(directory)
            # 15%, not 40%. At 40% a meaningful share of rows exceed `max_retry` within
            # the run and drop out of `get_pending_messages` forever — which is a real
            # defect, measured on purpose in `TestRetryExhaustion` rather than smeared
            # across an unrelated delivery assertion.
            link = LinkController(loss=0.15)
            uplink = FakeUplink(link)

            asyncio.run(_produce(buffer, 300))
            asyncio.run(drain(buffer, uplink, batch_size=100, rounds=40))

            ledger = asyncio.run(conservation(buffer, uplink, 300))
            _assert_balanced(ledger, "40% packet loss")
            assert ledger["sent"] == 300, (
                f"only {ledger['sent']}/300 delivered over a lossy link; retries are not "
                f"recovering the remainder"
            )

    def test_a_flapping_link_does_not_lose_or_duplicate(self):
        with TemporaryDirectory() as directory:
            buffer = _buffer(directory)
            link = LinkController(flap_down=3, flap_up=2)
            uplink = FakeUplink(link)

            asyncio.run(_produce(buffer, 200))
            asyncio.run(drain(buffer, uplink, batch_size=50, rounds=60))

            ledger = asyncio.run(conservation(buffer, uplink, 200))
            _assert_balanced(ledger, "a link flapping 3 down / 2 up")
            ids = [m["id"] for m in uplink.delivered]
            assert len(ids) == len(set(ids)), (
                "the same buffered row was delivered twice across a flap — at-least-once "
                "is acceptable on the wire, but marking sent twice means the buffer lost "
                "track of what it had already handed over"
            )


class TestLimitedBandwidth:
    def test_a_narrow_link_makes_progress_without_loss(self):
        with TemporaryDirectory() as directory:
            buffer = _buffer(directory)
            link = LinkController(capacity_per_call=5)
            uplink = FakeUplink(link)

            asyncio.run(_produce(buffer, 100))
            asyncio.run(drain(buffer, uplink, batch_size=100, rounds=10))

            ledger = asyncio.run(conservation(buffer, uplink, 100))
            _assert_balanced(ledger, "5 messages per round")
            assert ledger["sent"] == 50, (
                f"expected exactly 5x10 = 50 delivered under the ceiling, got "
                f"{ledger['sent']} — the bandwidth limit is not being respected"
            )
            assert ledger["still_buffered"] == 50


class TestTheLedgerItselfIsTrustworthy:
    """A conservation law is only worth the counters behind it. These assert the ledger
    NOTICES loss, because otherwise every scenario above passes by construction."""

    def test_retention_expiry_is_counted_not_silent(self):
        """Note what had to be aged. The first version of this stamped `timestamp_edge` 48
        hours back and asserted retention removed the rows; it removed none, because
        `cleanup_old_messages` keys off `created_at` — WHEN THE ROW WAS BUFFERED, not when
        the reading was taken. That is the correct basis (a backfilled historical reading
        should not expire on arrival), and it means a test must age the insert time."""
        import sqlite3

        with TemporaryDirectory() as directory:
            buffer = _buffer(directory, retention_hours=1)
            uplink = FakeUplink(LinkController(denied=True))

            asyncio.run(_produce(buffer, 50))
            with sqlite3.connect(Path(directory) / "buffer.db") as conn:
                conn.execute(
                    "UPDATE messages SET created_at = datetime('now', '-48 hours')"
                )
                conn.commit()
            expired = asyncio.run(buffer.cleanup_old_messages())

            assert expired == 50, "retention did not remove the aged rows"
            ledger = asyncio.run(conservation(buffer, uplink, 50))
            _assert_balanced(ledger, "retention expiry must be counted")
            assert ledger["expired"] == 50, (
                "rows were deleted by retention and the ledger did not count them — this "
                "is the silent-loss shape the whole harness exists to catch"
            )

    def test_the_ledger_reports_an_imbalance_when_one_exists(self):
        """The negative control. Delete rows behind the buffer's back and the books must
        NOT balance — otherwise the law is satisfied by a ledger that counts nothing."""
        import sqlite3

        with TemporaryDirectory() as directory:
            buffer = _buffer(directory)
            uplink = FakeUplink(LinkController(denied=True))
            asyncio.run(_produce(buffer, 40))

            with sqlite3.connect(Path(directory) / "buffer.db") as conn:
                conn.execute("DELETE FROM messages WHERE id <= 10")
                conn.commit()

            ledger = asyncio.run(conservation(buffer, uplink, 40))
            assert ledger["unaccounted"] == 10, (
                f"ten rows were deleted outside the buffer's own paths and the ledger "
                f"reported {ledger['unaccounted']} unaccounted — the conservation law "
                f"cannot detect loss, so every other scenario here passes for free"
            )


class TestRetryExhaustion:
    """A FINDING THIS HARNESS PRODUCED ON ITS FIRST RUN, kept as a measurement.

    `get_pending_messages` filters `retry_count < max_retry` (5). A row that fails five
    delivery attempts stops appearing in any future drain — it is not sent, not dead
    lettered, and not expired. It is simply invisible, sitting in `messages` forever until
    `move_exhausted_to_dead_letter` runs and discards it.

    The conservation law still balances, which is exactly why this needed its own test: the
    rows are accounted for as `still_buffered`, so nothing looks wrong. The problem is not
    loss, it is that a buffer built to survive outages **destroys its backlog when the link
    comes back degraded rather than down** — five failed attempts against a broker that is
    reachable but rejecting is a completely ordinary reconnect.

    Recorded rather than fixed here, because the fix is a design decision belonging to S5
    (adaptive backfill): whether retry should be a count at all, or a backoff with no cap.
    """

    def test_rows_past_the_retry_cap_stop_being_offered(self):
        with TemporaryDirectory() as directory:
            buffer = _buffer(directory)
            link = LinkController(denied=True)
            uplink = FakeUplink(link)

            asyncio.run(_produce(buffer, 20))
            # Six attempts against a reachable-but-rejecting link.
            asyncio.run(drain(buffer, uplink, batch_size=20, rounds=6))

            link.restore()
            asyncio.run(drain(buffer, uplink, batch_size=20, rounds=5))

            ledger = asyncio.run(conservation(buffer, uplink, 20))
            _assert_balanced(ledger, "retry exhaustion is stranding, not loss")
            assert ledger["sent"] == 0, (
                "if this now delivers, the retry cap was changed or removed — update this "
                "test and the S5 note, because the stranding it measures is gone"
            )
            assert ledger["still_buffered"] == 20, (
                "the stranded rows left `messages` by some path other than delivery"
            )


class TestTheBufferFillsAndShedsHonestly:
    """THE "L" IN DDIL, and the gap that a mutation exposed.

    Every scenario above leaves the buffer comfortably under its size cap, so the
    ring-buffer prune never runs — and a mutation that stopped `enforce_size_limit`
    counting its own losses passed all eight of them. The conservation law was correct and
    simply never pointed at that path.

    That is the failure mode a harness is most prone to: coverage of the interesting
    scenarios, silence on the boring one where the disk fills. A bounded buffer's whole
    contract is what it does at the boundary.
    """

    def test_pruning_to_fit_is_counted_not_silent(self):
        with TemporaryDirectory() as directory:
            # 1 MB cap, then write comfortably past it while the link is denied.
            buffer = _buffer(directory, max_size_mb=1)
            uplink = FakeUplink(LinkController(denied=True))

            produced = 3_000
            asyncio.run(_produce(buffer, produced, payload_bytes=512))
            pruned = asyncio.run(buffer.enforce_size_limit())

            assert pruned > 0, (
                "the buffer never exceeded its 1 MB cap, so the prune path did not run and "
                "this scenario is not testing what it claims"
            )
            ledger = asyncio.run(conservation(buffer, uplink, produced))
            _assert_balanced(ledger, "a full buffer must SHED, and count what it shed")
            assert ledger["dropped"] == pruned, (
                f"{pruned} rows were pruned to fit and the ledger counted "
                f"{ledger['dropped']} — an uncounted prune is silent data loss, which is "
                f"exactly what a bounded buffer must never do quietly"
            )

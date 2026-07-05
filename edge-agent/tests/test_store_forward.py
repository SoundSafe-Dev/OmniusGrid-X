"""Unit tests for StoreForwardBuffer (store-and-forward integrity)."""

import asyncio
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timedelta

from opsgrid_agent.buffer.store_forward import StoreForwardBuffer


def run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def make_buffer(**kwargs):
    tmpdir = tempfile.mkdtemp()
    return StoreForwardBuffer(buffer_path=os.path.join(tmpdir, "buffer.db"), **kwargs)


class StoreForwardTest(unittest.TestCase):
    def test_store_and_pending_ordering_by_edge_time(self):
        buf = make_buffer()

        async def scenario():
            base = datetime(2026, 7, 5, 12, 0, 0)
            # Insert out of edge-time order.
            await buf.store(base + timedelta(seconds=30), "a1", "telemetry", {"v": 3})
            await buf.store(base, "a1", "telemetry", {"v": 1})
            await buf.store(base + timedelta(seconds=15), "a1", "telemetry", {"v": 2})
            pending = await buf.get_pending_messages()
            return [datetime.fromisoformat(m.timestamp_edge) for m in pending]

        order = run(scenario())
        self.assertEqual(order, sorted(order))  # ORDER BY timestamp_edge ASC

    def test_mark_sent_removes(self):
        buf = make_buffer()

        async def scenario():
            await buf.store(datetime.utcnow(), "a1", "telemetry", {"v": 1})
            pending = await buf.get_pending_messages()
            await buf.mark_sent([pending[0].id])
            return await buf.get_stats()

        stats = run(scenario())
        self.assertEqual(stats["total_messages"], 0)

    def test_retry_cap_moves_to_dead_letter(self):
        buf = make_buffer()

        async def scenario():
            await buf.store(datetime.utcnow(), "a1", "telemetry", {"v": 1})
            pending = await buf.get_pending_messages()
            mid = [pending[0].id]
            # Exhaust retries (default max_retry=5).
            for _ in range(5):
                await buf.increment_retry(mid)
            # Now excluded from pending, but still in messages until dead-lettered.
            self.assertEqual(len(await buf.get_pending_messages()), 0)
            moved = await buf.move_exhausted_to_dead_letter(max_retry=5)
            stats = await buf.get_stats()
            return moved, stats

        moved, stats = run(scenario())
        self.assertEqual(moved, 1)
        self.assertEqual(stats["total_messages"], 0)
        self.assertEqual(stats["dead_lettered"], 1)

    def test_enforce_size_limit_prunes_oldest(self):
        buf = make_buffer()

        async def scenario():
            # Write enough rows to exceed a tiny cap.
            big = {"blob": "x" * 2000}
            for i in range(500):
                await buf.store(datetime(2026, 7, 5, 12, 0, i % 60), f"a{i}", "telemetry", big)
            before = (await buf.get_stats())["total_messages"]
            # Tiny positive cap forces pruning (0/None means "no limit").
            pruned = await buf.enforce_size_limit(max_size_mb=0.05)
            after = (await buf.get_stats())["total_messages"]
            return before, pruned, after

        before, pruned, after = run(scenario())
        self.assertGreater(before, 0)
        self.assertGreater(pruned, 0)
        self.assertLess(after, before)

    def test_cleanup_old_messages_by_retention(self):
        buf = make_buffer(retention_hours=1)

        async def scenario():
            await buf.store(datetime.utcnow(), "a1", "telemetry", {"v": 1})
            # created_at is CURRENT_TIMESTAMP; force an old created_at to trigger cleanup.
            import sqlite3
            with sqlite3.connect(buf.buffer_path) as conn:
                conn.execute("UPDATE messages SET created_at = '2000-01-01T00:00:00'")
                conn.commit()
            deleted = await buf.cleanup_old_messages()
            return deleted, await buf.get_stats()

        deleted, stats = run(scenario())
        self.assertEqual(deleted, 1)
        self.assertEqual(stats["total_messages"], 0)

    def test_stats_include_lag_and_dead_letter(self):
        buf = make_buffer()

        async def scenario():
            await buf.store(datetime(2020, 1, 1, 0, 0, 0), "a1", "telemetry", {"v": 1})
            return await buf.get_stats()

        stats = run(scenario())
        self.assertIn("dead_lettered", stats)
        self.assertIn("backfill_lag_seconds", stats)
        self.assertGreater(stats["backfill_lag_seconds"], 0)  # 2020 timestamp is old


if __name__ == "__main__":
    unittest.main(verbosity=2)

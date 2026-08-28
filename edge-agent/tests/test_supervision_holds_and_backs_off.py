"""Collector supervision is retained, backed off, and durable until stop.

Two defects in the same twenty lines, both of which produce no error and no log line.

**FS-502 — the tasks were dropped.** `start_all` built its supervision tasks into a local
that went out of scope on the next statement, never awaited and with no strong reference.
asyncio holds only a weak reference to a running task, so the loop was free to collect one
mid-flight; and an exception inside a collected task surfaces nowhere. `all_collectors_started`
was logged before any collector had started.

**FS-501 — a clean return spun the loop.** The supervision loop counted restarts and slept
only in its `except` branch:

    while self._running and restart_count < max_restarts:
        try:
            await collector.start()
        except Exception:
            restart_count += 1
            ...
            await asyncio.sleep(5)

A `start()` that **returns** rather than raises therefore incremented nothing and slept for
nothing — a tight loop for the life of the process, burning a core with no counter moving and
nothing in the log. A collector that exits normally when its connection closes is the ordinary
case, not an exotic one.

FS-660 closes the later failure mode: the corrected loop still stopped permanently after ten
attempts. These tests cross that old boundary deterministically, verify the capped delays and
status, and prove stop wakes a long retry wait immediately.
"""

from __future__ import annotations

import asyncio
import os
import sys
import unittest
from unittest.mock import AsyncMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from opsgrid_agent.buffer.store_forward import StoreForwardBuffer  # noqa: E402
from opsgrid_agent.collectors.coordinator import CollectorConfig, UnifiedCollectorCoordinator  # noqa: E402


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class _ReturningCollector:
    """A collector whose `start()` returns immediately, cleanly.

    This is what a device connection closing looks like from the supervisor's side, and it is
    the input the old loop could not survive.
    """

    def __init__(self, *args, **kwargs):
        self.starts = 0

    async def start(self):
        self.starts += 1
        return  # no exception — the FS-501 case

    async def stop(self):
        pass


class _CrashingCollector(_ReturningCollector):
    async def start(self):
        self.starts += 1
        raise RuntimeError("collector crashed")


class SupervisionDoesNotHotSpin(unittest.IsolatedAsyncioTestCase):
    async def _coordinator(self, tmpdir):
        buffer = StoreForwardBuffer(buffer_path=os.path.join(tmpdir, "b.db"))
        return UnifiedCollectorCoordinator(buffer=buffer)

    async def test_a_clean_return_does_not_spin(self):
        """Measures the RATE, not the exit.

        What distinguishes the defect is how fast the loop goes round: a supervisor that
        sleeps starts a handful of times in a short window, while one that hot-spins starts
        thousands.
        """
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            coordinator = await self._coordinator(tmpdir)
            collector = _ReturningCollector()
            coordinator.collectors["a1"] = collector
            coordinator._running = True

            supervisor = asyncio.create_task(coordinator._run_collector("a1", collector))
            await asyncio.sleep(0.3)
            coordinator._running = False
            supervisor.cancel()
            try:
                await supervisor
            except asyncio.CancelledError:
                pass

            self.assertLessEqual(
                collector.starts,
                3,
                f"start() was called {collector.starts} times in 0.3 s — the supervision loop "
                f"is spinning. Before FS-501 only the `except` branch counted and slept, so a "
                f"collector returning cleanly went round as fast as the scheduler allowed, "
                f"for the life of the process, with no counter moving and nothing logged.",
            )
            self.assertGreaterEqual(
                collector.starts, 1, "the supervisor never started the collector at all"
            )


class SupervisionDoesNotExhaust(unittest.IsolatedAsyncioTestCase):
    async def _assert_attempt_eleven_remains_live(self, collector, expected_outcome):
        coordinator = UnifiedCollectorCoordinator(buffer=object())
        coordinator._running = True
        release = asyncio.Event()
        reached_attempt_eleven = asyncio.Event()
        delays: list[float] = []

        async def controlled_wait(delay):
            delays.append(delay)
            if collector.starts >= 11:
                reached_attempt_eleven.set()
                await release.wait()
            return coordinator._running

        coordinator._wait_for_supervisor_retry = controlled_wait
        coordinator.configs["a1"] = CollectorConfig(
            asset_id="a1",
            collector_type="test",
            config={},
        )
        coordinator.collectors["a1"] = collector
        supervisor = asyncio.create_task(
            coordinator._run_collector("a1", collector)
        )
        coordinator.collector_tasks["a1"] = supervisor
        try:
            await asyncio.wait_for(reached_attempt_eleven.wait(), timeout=1)

            self.assertEqual(collector.starts, 11)
            self.assertFalse(
                supervisor.done(),
                "the supervisor ended at the old ten-attempt limit",
            )
            self.assertEqual(delays[:5], [5.0, 10.0, 20.0, 40.0, 60.0])
            self.assertEqual(delays[5:], [60.0] * 6)

            status = coordinator.get_collector_status("a1")
            self.assertTrue(status["running"])
            self.assertEqual(
                status["supervision"],
                {
                    "state": "backing_off",
                    "attempts": 11,
                    "last_outcome": expected_outcome,
                    "next_retry_seconds": 60.0,
                },
            )
            self.assertEqual(coordinator.get_status()["degraded_collectors"], 1)
        finally:
            coordinator._running = False
            release.set()
            await asyncio.wait_for(supervisor, timeout=1)

    async def test_a_clean_return_is_retried_after_attempt_ten(self):
        await self._assert_attempt_eleven_remains_live(
            _ReturningCollector(),
            "returned",
        )

    async def test_a_crash_is_retried_after_attempt_ten(self):
        await self._assert_attempt_eleven_remains_live(
            _CrashingCollector(),
            "crashed",
        )

    async def test_stop_wakes_a_capped_retry_wait(self):
        coordinator = UnifiedCollectorCoordinator(buffer=object())
        coordinator._running = True
        wait_task = asyncio.create_task(
            coordinator._wait_for_supervisor_retry(3600)
        )
        await asyncio.sleep(0)

        await coordinator.stop_all()

        self.assertFalse(await asyncio.wait_for(wait_task, timeout=0.1))


class HealthMonitorDoesNotDuplicateDurableSupervision(
    unittest.IsolatedAsyncioTestCase
):
    async def test_a_backing_off_live_task_is_not_recreated(self):
        coordinator = UnifiedCollectorCoordinator(buffer=object())
        coordinator._running = True
        coordinator.configs["a1"] = CollectorConfig(
            asset_id="a1",
            collector_type="test",
            config={},
        )
        coordinator.collectors["a1"] = _CrashingCollector()
        coordinator._supervision_status["a1"] = {
            "state": "backing_off",
            "attempts": 11,
            "last_outcome": "crashed",
            "next_retry_seconds": 60.0,
        }
        live_supervisor = asyncio.create_task(asyncio.Event().wait())
        coordinator.collector_tasks["a1"] = live_supervisor

        async def one_health_tick(_delay):
            coordinator._running = False

        try:
            with patch(
                "opsgrid_agent.collectors.coordinator.asyncio.sleep",
                side_effect=one_health_tick,
            ), patch.object(
                coordinator,
                "_start_collector",
                new_callable=AsyncMock,
            ) as restart:
                await coordinator._health_monitor()

            restart.assert_not_awaited()
            self.assertFalse(live_supervisor.done())
        finally:
            live_supervisor.cancel()
            try:
                await live_supervisor
            except asyncio.CancelledError:
                pass


class StartAllRetainsItsSupervisors(unittest.IsolatedAsyncioTestCase):
    async def test_the_tasks_are_held_on_the_instance(self):
        """asyncio keeps only a weak reference to a running task."""
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            buffer = StoreForwardBuffer(buffer_path=os.path.join(tmpdir, "b.db"))
            coordinator = UnifiedCollectorCoordinator(buffer=buffer)
            coordinator.SUPPORTED_COLLECTORS = dict(coordinator.SUPPORTED_COLLECTORS)
            coordinator.SUPPORTED_COLLECTORS["returning"] = _ReturningCollector
            coordinator.register_collector(
                CollectorConfig(asset_id="a1", collector_type="returning", config={})
            )

            await coordinator.start_all()
            try:
                self.assertTrue(
                    getattr(coordinator, "_collector_tasks", []),
                    "start_all did not retain its supervision tasks. They were built into a "
                    "local that went out of scope, so the loop could collect one mid-flight "
                    "and an exception inside it would surface nowhere (FS-502).",
                )
            finally:
                await coordinator.stop_all()

    async def test_stop_all_cancels_them(self):
        """`self._running = False` is checked at the top of the loop, which a supervisor
        awaiting a socket never reaches — so stopping has to cancel, not just signal."""
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            buffer = StoreForwardBuffer(buffer_path=os.path.join(tmpdir, "b.db"))
            coordinator = UnifiedCollectorCoordinator(buffer=buffer)
            coordinator.SUPPORTED_COLLECTORS = dict(coordinator.SUPPORTED_COLLECTORS)
            coordinator.SUPPORTED_COLLECTORS["returning"] = _ReturningCollector
            coordinator.register_collector(
                CollectorConfig(asset_id="a1", collector_type="returning", config={})
            )

            await coordinator.start_all()
            tasks = list(getattr(coordinator, "_collector_tasks", []))
            await coordinator.stop_all()
            await asyncio.sleep(0)

            self.assertTrue(
                all(t.cancelled() or t.done() for t in tasks),
                "stop_all returned while supervisors were still running",
            )


if __name__ == "__main__":
    unittest.main()

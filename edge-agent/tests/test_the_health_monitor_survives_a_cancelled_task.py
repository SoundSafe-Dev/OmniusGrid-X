"""One cancelled task ended all collector supervision, permanently (FS-698).

`_health_monitor` inspects every done collector task with `task.exception()` — and for a
task that was CANCELLED, that call does not return an exception, it *raises*
`asyncio.CancelledError`. CancelledError is a `BaseException` since Python 3.8, so it sails
past the loop's `except Exception` and terminates the monitor coroutine.

THE WINDOW IS REAL, NOT THEORETICAL. `restart_collector` cancels the old task and then
`await`s it (with a 2s timeout) BEFORE popping it from `collector_tasks` — a suspension
point at which the monitor can wake, iterate the dict, and meet the cancelled entry.
`stop_collector` (config hot-reload) pops first but the monitor iterates a snapshot taken
with `list(...)`, so an entry captured before the pop is still inspected after the cancel.

WHAT DYING COSTS. The monitor is the only writer of `edge_collector_connection_state`
(frozen at its last values — the FS-694 class, inflicted by a single hot-reload), the only
caller of `refresh_collector_stats`, and the only automatic restart path for crashed
collectors. After one CancelledError the agent runs on unsupervised, and the only trace is
one unexplained traceback in the log.

Driven live before the fix: a real `_health_monitor` handed a cancelled task terminated
with CancelledError on its first iteration.
"""

from __future__ import annotations

import asyncio
import os
import tempfile

import pytest

from opsgrid_agent.buffer.store_forward import StoreForwardBuffer
from opsgrid_agent.collectors.coordinator import UnifiedCollectorCoordinator


def _coordinator() -> UnifiedCollectorCoordinator:
    buffer = StoreForwardBuffer(
        buffer_path=os.path.join(tempfile.mkdtemp(), "buffer.db"),
        retention_hours=1,
    )
    return UnifiedCollectorCoordinator(buffer=buffer, kafka_producer=None)


async def _one_iteration(coordinator: UnifiedCollectorCoordinator, monkeypatch) -> asyncio.Task:
    """Run the real monitor for exactly one iteration, deterministically.

    The 30s pacing sleep is shrunk via the module's own asyncio reference and set to
    flip `_running` off, so the loop body executes once and the coroutine returns —
    no wall-clock, no timing luck (the live drive that found this bug hung for 30s
    the moment the fix made the monitor survive).
    """
    real_sleep = asyncio.sleep

    async def one_shot_sleep(_seconds):
        coordinator._running = False
        await real_sleep(0)

    from opsgrid_agent.collectors import coordinator as coordinator_module

    monkeypatch.setattr(coordinator_module.asyncio, "sleep", one_shot_sleep)
    coordinator._running = True
    task = asyncio.get_running_loop().create_task(coordinator._health_monitor())
    await real_sleep(0.2)
    monkeypatch.setattr(coordinator_module.asyncio, "sleep", real_sleep)
    return task


class TestACancelledTaskDoesNotEndSupervision:
    @pytest.mark.asyncio
    async def test_the_monitor_survives_a_cancelled_collector_task(self, monkeypatch):
        """THE PROPERTY. Before the fix this monitor task terminated with
        CancelledError; supervision, liveness gauges and auto-restart all stopped."""
        coordinator = _coordinator()
        doomed = asyncio.get_running_loop().create_task(asyncio.Event().wait())
        doomed.cancel()
        await asyncio.sleep(0)
        coordinator.collector_tasks["press-9"] = doomed

        monitor = await _one_iteration(coordinator, monkeypatch)

        assert monitor.done(), "the single-iteration harness should have completed"
        assert not monitor.cancelled(), (
            "the monitor terminated with CancelledError: `task.exception()` on a "
            "cancelled collector task raises rather than returns, and `except "
            "Exception` cannot catch a BaseException. One hot-reload ends all "
            "supervision."
        )
        assert monitor.exception() is None

    @pytest.mark.asyncio
    async def test_a_cancelled_task_is_not_restarted(self, monkeypatch):
        """Cancellation is administrative — restart_collector or a hot-reload is about
        to replace or remove the entry. A monitor that restarts it races the very
        operation that cancelled it, with two tasks then claiming one asset_id."""
        coordinator = _coordinator()
        doomed = asyncio.get_running_loop().create_task(asyncio.Event().wait())
        doomed.cancel()
        await asyncio.sleep(0)
        coordinator.collector_tasks["press-9"] = doomed

        starts: list = []

        async def _record_start(config):
            starts.append(config)
            return True

        coordinator._start_collector = _record_start
        await _one_iteration(coordinator, monkeypatch)
        assert starts == []

    @pytest.mark.asyncio
    async def test_a_crashed_task_is_still_restarted(self, monkeypatch):
        """NEGATIVE CONTROL. The fix must not widen: a task that died of a real
        exception is exactly what the restart path exists for, and a `continue` that
        swallowed crashed tasks too would pass the two tests above while quietly
        disabling recovery."""
        from opsgrid_agent.collectors.coordinator import CollectorConfig

        coordinator = _coordinator()

        async def _boom():
            raise RuntimeError("collector crashed")

        crashed = asyncio.get_running_loop().create_task(_boom())
        await asyncio.sleep(0)
        coordinator.collector_tasks["press-10"] = crashed
        coordinator.configs["press-10"] = CollectorConfig(
            collector_type="http_rest", asset_id="press-10", config={}, enabled=True
        )

        starts: list = []

        async def _record_start(config):
            starts.append(config.asset_id)
            return True

        coordinator._start_collector = _record_start
        monitor = await _one_iteration(coordinator, monkeypatch)

        assert monitor.done() and monitor.exception() is None
        assert starts == ["press-10"], (
            "a collector that crashed with a real exception was not restarted — the "
            "cancelled-task guard is swallowing more than cancellation"
        )

"""Standalone worker entrypoint for OTA rollout orchestration."""

from __future__ import annotations

import asyncio
import os
import signal

import structlog

from app.services.command_executor import command_executor
from app.services.rollout_orchestrator import rollout_orchestrator
from app.workers.health_server import start_health_server

from app.core.tracing import setup_worker_tracing

logger = structlog.get_logger()


def _health_port():
    """WORKER_HEALTH_PORT, or None outside Kubernetes (tests/local runs)."""
    raw = os.getenv("WORKER_HEALTH_PORT")
    return int(raw) if raw else None


async def run(
    *,
    stop_event: asyncio.Event | None = None,
    command_service=None,
    rollout_service=None,
) -> None:
    stop_event = stop_event or asyncio.Event()
    command_service = command_service or command_executor
    rollout_service = rollout_service or rollout_orchestrator

    def _stop() -> None:
        stop_event.set()

    loop = asyncio.get_running_loop()
    registered_signals = []
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, _stop)
            registered_signals.append(sig)
        except NotImplementedError:
            pass

    command_start_attempted = False
    rollout_start_attempted = False
    try:
        command_start_attempted = True
        await command_service.start()
        rollout_start_attempted = True
        await rollout_service.start()
        # stale_after=0: this worker ORCHESTRATES (command executor + rollout
        # dispatcher run as their own tasks) and then idles on stop_event, so it
        # has no unit-of-work loop to heartbeat. Readiness is the honest signal —
        # claiming staleness-based liveness here would be theatre.
        health = start_health_server("ota-rollouts", port=_health_port(), stale_after_seconds=0)
        if health:
            health.ready()
        await stop_event.wait()
    finally:
        try:
            try:
                if rollout_start_attempted:
                    await rollout_service.stop()
            finally:
                if command_start_attempted:
                    await command_service.stop()
        finally:
            for sig in registered_signals:
                loop.remove_signal_handler(sig)


if __name__ == "__main__":
    logger.info("ota_rollout_worker_starting")
    # FS-791. Instrument BEFORE the event loop starts: the instrumentor patches the
    # aiokafka client CLASS, and a consumer constructed first is never traced.
    #
    # This process emitted no spans at all until now — `setup_tracing` lives in
    # app/main.py and no worker ever called it, so the consumer half of every
    # telemetry message, and every database write these workers make, were absent
    # from tracing entirely. That is the path IngestionDataLost fires on.
    setup_worker_tracing(service="omniusgrid-ota-rollout-worker")
    asyncio.run(run())

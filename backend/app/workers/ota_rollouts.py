"""Standalone worker entrypoint for OTA rollout orchestration."""

from __future__ import annotations

import asyncio
import signal

import structlog

from app.services.command_executor import command_executor
from app.services.rollout_orchestrator import rollout_orchestrator

logger = structlog.get_logger()


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
    asyncio.run(run())

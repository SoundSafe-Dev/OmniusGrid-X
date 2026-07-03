"""Standalone worker entrypoint for OTA rollout orchestration."""

from __future__ import annotations

import asyncio
import signal

import structlog

from app.services.rollout_orchestrator import rollout_orchestrator

logger = structlog.get_logger()


async def run() -> None:
    stop_event = asyncio.Event()

    def _stop() -> None:
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, _stop)
        except NotImplementedError:
            pass

    await rollout_orchestrator.start()
    try:
        await stop_event.wait()
    finally:
        await rollout_orchestrator.stop()


if __name__ == "__main__":
    logger.info("ota_rollout_worker_starting")
    asyncio.run(run())

"""Standalone worker that indexes queued RAG documents.

Unlike the other three workers this one has no Kafka consumer: the
``rag_documents`` row IS the queue, claimed with FOR UPDATE SKIP LOCKED. That
removes the singleton dispatcher a Redpanda outbox would need, so this worker
is safe to run at any replica count — see the design spec for the reasoning.

Loop shape, signal handling and injectable collaborators follow
``app/workers/ota_rollouts.py`` so the worker is testable without infrastructure.
"""

from __future__ import annotations

import asyncio
import os
import signal
from typing import Optional

import structlog

from app.core.config import settings
from app.services.rag_index_queue import (
    MAX_CLAIMS_PER_ORG_PER_PASS,
    claim_next,
    finalize,
    list_org_ids,
    recover_stale,
    requeue_or_fail,
)
from app.services.rag_ingestion import get_ingestion_pipeline
from app.services.transport_errors import TRANSPORT_ERRORS
from app.workers.health_server import RAG_INDEXING_FAILED, start_health_server

logger = structlog.get_logger()


def _health_port():
    """WORKER_HEALTH_PORT, or None outside Kubernetes (tests/local runs)."""
    raw = os.getenv("WORKER_HEALTH_PORT")
    return int(raw) if raw else None


async def _process_one(claimed, pipeline) -> None:
    """Index one claimed document and record its outcome.

    An exception here is an infrastructure fault (inference down, Qdrant
    unreachable, blob unreadable), so the row goes back to 'queued' until
    attempts run out. A returned result is a decided outcome — 'indexed' or
    'skipped' — and is written as terminal.
    """
    try:
        result = await pipeline.index_document(claimed)
    except (RuntimeError, *TRANSPORT_ERRORS) as exc:
        # NARROWED TO WHAT THE DOCSTRING ABOVE ALREADY CLAIMED. It says an exception here
        # "is an infrastructure fault", and while it caught `Exception` that was a hope
        # rather than a statement: an AttributeError in the pipeline was requeued three
        # times and then written to the row as `failed`, wearing an infrastructure
        # story. A defect on this side now reaches the loop handler instead, where it is
        # counted as `pass_errored` and logged at error level.
        #
        # `RuntimeError` stays in: the RAG services raise it for "not configured /
        # unreachable", which is exactly an infrastructure fault.
        # COUNTED, NOT ONLY LOGGED. The requeue below keeps the document moving, so a
        # store that fails every attempt drains to `failed` quietly: the worker stays
        # up, the queue stays short, and nothing says why nothing is searchable.
        RAG_INDEXING_FAILED.labels(stage="pass_failed").inc()
        logger.warning(
            "rag_indexing.pass_failed", doc_id=claimed.doc_id, error=str(exc)
        )
        await requeue_or_fail(
            org_id=claimed.org_id,
            doc_id=claimed.doc_id,
            attempts=claimed.attempts,
            started_at=claimed.started_at,
            error=str(exc),
        )
        return

    await finalize(
        org_id=claimed.org_id,
        doc_id=claimed.doc_id,
        attempts=claimed.attempts,
        started_at=claimed.started_at,
        status=result.status,
        num_blocks=result.num_blocks,
        num_chunks=result.num_chunks,
        reason=result.reason,
    )


async def run_once(pipeline=None) -> int:
    """One full pass: recover stale rows, then drain every org. Returns count."""
    pipeline = pipeline or get_ingestion_pipeline()
    await recover_stale()

    processed = 0
    for org_id in await list_org_ids():
        for _ in range(MAX_CLAIMS_PER_ORG_PER_PASS):
            claimed = await claim_next(org_id)
            if claimed is None:
                break
            await _process_one(claimed, pipeline)
            processed += 1
    return processed


async def run(
    *,
    stop_event: Optional[asyncio.Event] = None,
    poll_interval: Optional[float] = None,
    pipeline=None,
    max_passes: Optional[int] = None,
) -> None:
    """Poll until stopped. ``max_passes`` bounds the loop for tests."""
    stop_event = stop_event or asyncio.Event()
    if poll_interval is None:
        poll_interval = settings.RAG_INDEX_POLL_INTERVAL_SECONDS

    def _stop() -> None:
        stop_event.set()

    loop = asyncio.get_running_loop()
    registered_signals = []
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, _stop)
            registered_signals.append(sig)
        except NotImplementedError:  # Windows / non-main thread
            pass

    # A WEDGED WORKER MUST BE RESTARTABLE. This one shipped with no probe of any kind
    # (`tests/k8s/check_probe_ports.py` names it), so a pass that hung on an unreachable
    # Qdrant left a pod that Kubernetes considered perfectly healthy while the queue
    # backed up behind it. `stale_after_seconds` is the poll interval with generous
    # headroom: a loop that has not completed a pass in that long is not polling.
    health = start_health_server(
        "rag-indexing",
        port=_health_port(),
        stale_after_seconds=max(60.0, poll_interval * 12),
    )
    if health:
        health.ready()

    passes = 0
    try:
        while not stop_event.is_set():
            try:
                await run_once(pipeline=pipeline)
            except Exception as exc:  # noqa: BLE001 - a bad pass must not kill the loop
                # A live loop that fails every pass is indistinguishable from an idle
                # one on liveness alone, which is what this counter is for.
                RAG_INDEXING_FAILED.labels(stage="pass_errored").inc()
                logger.error("rag_indexing.pass_errored", error=str(exc))

            if health:
                health.beat()
            passes += 1
            if max_passes is not None and passes >= max_passes:
                return
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=poll_interval)
            except asyncio.TimeoutError:
                pass
    finally:
        for sig in registered_signals:
            loop.remove_signal_handler(sig)


async def _idle_until_signalled() -> None:
    """Stay alive doing nothing, until the container is stopped.

    Exiting 0 here would look like a clean shutdown to the process, but both
    supervisors read it as a completed run and start it again: compose's
    ``restart: unless-stopped`` and a k8s Deployment (whose only valid
    ``restartPolicy`` is Always) would turn the off switch into a crash-loop of
    no-ops, complete with CrashLoopBackOff once the backoff kicks in. Idling
    instead makes the disabled worker a quiet, healthy, zero-work pod. To
    actually reclaim the resources, scale the Deployment to zero or drop the
    compose service — that is the supervisor's job, not the process's.
    """
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except NotImplementedError:  # Windows / non-main thread
            pass
    await stop_event.wait()


if __name__ == "__main__":
    if not settings.RAG_INDEX_WORKER_ENABLED:
        logger.info("rag_indexing_worker_disabled")
        asyncio.run(_idle_until_signalled())
    else:
        logger.info("rag_indexing_worker_starting")
        asyncio.run(run())

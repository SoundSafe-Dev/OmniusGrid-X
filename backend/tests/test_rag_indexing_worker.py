"""One worker pass: claim -> index -> terminal status, including failure paths."""

from __future__ import annotations

import asyncio

import pytest

from app.services.rag_ingestion import IngestionResult
from app.workers import rag_indexing


class _StubPipeline:
    """Stands in for IngestionPipeline; records what it was asked to index."""

    def __init__(self, outcome=None, raises=None):
        self.outcome = outcome
        self.raises = raises
        self.seen = []

    async def index_document(self, claimed, *, extra_metadata=None):
        self.seen.append(claimed.doc_id)
        if self.raises:
            raise self.raises
        return self.outcome or IngestionResult(
            doc_id=claimed.doc_id,
            org_id=claimed.org_id,
            filename=claimed.filename,
            s3_key=claimed.s3_key,
            kind=claimed.kind,
            stored=True,
            indexed=True,
            status="indexed",
            num_blocks=2,
            num_chunks=5,
        )


@pytest.fixture
def queue_calls(monkeypatch):
    """Capture queue interactions without a database."""
    calls = {"finalize": [], "requeue": []}
    claimed_box = {}

    async def _list_org_ids():
        return ["org-1"]

    async def _recover_stale():
        return 0

    async def _claim_next(org_id):
        return claimed_box.pop("next", None)

    async def _finalize(**kwargs):
        calls["finalize"].append(kwargs)
        return True

    async def _requeue_or_fail(**kwargs):
        calls["requeue"].append(kwargs)
        return "queued"

    monkeypatch.setattr(rag_indexing, "list_org_ids", _list_org_ids)
    monkeypatch.setattr(rag_indexing, "recover_stale", _recover_stale)
    monkeypatch.setattr(rag_indexing, "claim_next", _claim_next)
    monkeypatch.setattr(rag_indexing, "finalize", _finalize)
    monkeypatch.setattr(rag_indexing, "requeue_or_fail", _requeue_or_fail)
    calls["box"] = claimed_box
    return calls


def _claimed(doc_id="doc-1", kind="text"):
    from datetime import datetime, timezone

    from app.services.rag_index_queue import ClaimedDocument

    return ClaimedDocument(
        org_id="org-1",
        doc_id=doc_id,
        s3_key=f"org-1/{doc_id}/a.txt",
        filename="a.txt",
        kind=kind,
        attempts=1,
        started_at=datetime.now(timezone.utc),
    )


async def test_pass_indexes_a_claimed_document(queue_calls):
    queue_calls["box"]["next"] = _claimed()
    pipeline = _StubPipeline()

    processed = await rag_indexing.run_once(pipeline=pipeline)

    assert processed == 1
    assert pipeline.seen == ["doc-1"]
    assert queue_calls["finalize"][0]["status"] == "indexed"
    assert queue_calls["finalize"][0]["num_chunks"] == 5


async def test_skipped_outcome_is_recorded_with_reason(queue_calls):
    queue_calls["box"]["next"] = _claimed(kind="unsupported")
    pipeline = _StubPipeline(
        outcome=IngestionResult(
            doc_id="doc-1", org_id="org-1", filename="a.bin",
            s3_key="k", kind="unsupported", stored=True, indexed=False,
            status="skipped", reason="Unsupported file type for RAG indexing: a.bin",
        )
    )

    await rag_indexing.run_once(pipeline=pipeline)

    finalized = queue_calls["finalize"][0]
    assert finalized["status"] == "skipped"
    assert "Unsupported" in finalized["reason"]
    assert queue_calls["requeue"] == []


async def test_infra_error_requeues_instead_of_finalizing(queue_calls):
    queue_calls["box"]["next"] = _claimed()
    pipeline = _StubPipeline(raises=RuntimeError("qdrant unreachable"))

    await rag_indexing.run_once(pipeline=pipeline)

    assert queue_calls["finalize"] == []
    assert queue_calls["requeue"][0]["error"] == "qdrant unreachable"
    assert queue_calls["requeue"][0]["attempts"] == 1


async def test_empty_queue_is_a_no_op(queue_calls):
    processed = await rag_indexing.run_once(pipeline=_StubPipeline())

    assert processed == 0
    assert queue_calls["finalize"] == []


async def test_run_stops_when_the_stop_event_is_set(queue_calls):
    stop_event = asyncio.Event()
    stop_event.set()

    await asyncio.wait_for(
        rag_indexing.run(
            stop_event=stop_event,
            poll_interval=0.01,
            pipeline=_StubPipeline(),
        ),
        timeout=2,
    )


async def test_run_honours_max_passes(queue_calls):
    await asyncio.wait_for(
        rag_indexing.run(
            poll_interval=0.001, pipeline=_StubPipeline(), max_passes=2
        ),
        timeout=2,
    )

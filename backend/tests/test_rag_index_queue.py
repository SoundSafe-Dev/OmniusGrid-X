"""rag_index_queue: claim/finalize semantics under concurrency and crashes."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

pytest.importorskip("testcontainers")

from sqlalchemy import text  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.services import rag_index_queue as q  # noqa: E402


async def _queue_doc(org_id, doc_id="doc-1", kind="text"):
    await q.upsert_queued(
        org_id=str(org_id),
        doc_id=doc_id,
        uploaded_by=None,
        filename=f"{doc_id}.txt",
        s3_key=f"{org_id}/{doc_id}/{doc_id}.txt",
        kind=kind,
    )


async def test_claim_returns_queued_row_and_marks_it_indexing(app, seeded_orgs):
    org_id = seeded_orgs["org_a_id"]
    await _queue_doc(org_id)

    claimed = await q.claim_next(str(org_id))

    assert claimed is not None
    assert claimed.doc_id == "doc-1"
    assert claimed.attempts == 1
    status = await q.get_status(str(org_id), "doc-1")
    assert status["status"] == "indexing"


async def test_second_claim_skips_the_locked_row(app, seeded_orgs):
    """A row already claimed is never handed to a second worker."""
    org_id = seeded_orgs["org_a_id"]
    await _queue_doc(org_id)

    first = await q.claim_next(str(org_id))
    second = await q.claim_next(str(org_id))

    assert first is not None
    assert second is None, "a claimed row must not be claimable again"


async def test_finalize_writes_terminal_state(app, seeded_orgs):
    org_id = seeded_orgs["org_a_id"]
    await _queue_doc(org_id)
    claimed = await q.claim_next(str(org_id))

    ok = await q.finalize(
        org_id=str(org_id),
        doc_id=claimed.doc_id,
        attempts=claimed.attempts,
        status="indexed",
        num_blocks=3,
        num_chunks=7,
    )

    assert ok is True
    status = await q.get_status(str(org_id), "doc-1")
    assert status["status"] == "indexed"
    assert status["num_chunks"] == 7
    assert status["completed_at"] is not None


async def test_finalize_is_discarded_when_row_was_requeued_midflight(
    app, seeded_orgs
):
    """A re-ingest during indexing must not be overwritten by the stale pass."""
    org_id = seeded_orgs["org_a_id"]
    await _queue_doc(org_id)
    claimed = await q.claim_next(str(org_id))

    # caller re-ingests the same doc_id while the first pass is still running
    await _queue_doc(org_id)

    ok = await q.finalize(
        org_id=str(org_id),
        doc_id=claimed.doc_id,
        attempts=claimed.attempts,
        status="indexed",
        num_chunks=7,
    )

    assert ok is False, "stale finalize must not win"
    status = await q.get_status(str(org_id), "doc-1")
    assert status["status"] == "queued"


async def test_requeue_or_fail_retries_then_fails(app, seeded_orgs):
    org_id = seeded_orgs["org_a_id"]
    await _queue_doc(org_id)

    for _ in range(settings.RAG_INDEX_MAX_ATTEMPTS - 1):
        claimed = await q.claim_next(str(org_id))
        outcome = await q.requeue_or_fail(
            org_id=str(org_id),
            doc_id=claimed.doc_id,
            attempts=claimed.attempts,
            error="qdrant unreachable",
        )
        assert outcome == "queued"

    claimed = await q.claim_next(str(org_id))
    outcome = await q.requeue_or_fail(
        org_id=str(org_id),
        doc_id=claimed.doc_id,
        attempts=claimed.attempts,
        error="qdrant unreachable",
    )

    assert outcome == "failed"
    status = await q.get_status(str(org_id), "doc-1")
    assert status["status"] == "failed"
    assert "qdrant" in status["error"]


async def test_recover_stale_requeues_abandoned_indexing_rows(app, seeded_orgs):
    """A worker that died mid-index leaves an 'indexing' row; it must recover."""
    org_id = seeded_orgs["org_a_id"]
    await _queue_doc(org_id)
    await q.claim_next(str(org_id))

    # Imported here rather than at module scope: the `app` fixture patches
    # app.db.database.AsyncSessionLocal to point at the test container after
    # this module is collected, and it only sweeps modules under `app.` — a
    # top-level import in a `tests.` module would bind the pre-patch
    # (placeholder) engine instead. See test_compliance_report_queue_worker.py
    # for the same pattern.
    from app.db.database import AsyncSessionLocal

    stale_at = datetime.now(timezone.utc) - timedelta(
        seconds=settings.RAG_INDEX_STALE_INDEXING_SECONDS + 60
    )
    async with AsyncSessionLocal() as session:
        await session.execute(
            text("SELECT set_config('app.current_org_id', :org, true)"),
            {"org": str(org_id)},
        )
        await session.execute(
            text(
                "UPDATE rag_documents SET updated_at = :ts "
                "WHERE doc_id = 'doc-1'"
            ),
            {"ts": stale_at},
        )
        await session.commit()

    recovered = await q.recover_stale()

    assert recovered == 1
    status = await q.get_status(str(org_id), "doc-1")
    assert status["status"] == "queued"


async def test_get_status_is_org_scoped(app, seeded_orgs):
    org_a = seeded_orgs["org_a_id"]
    org_b = seeded_orgs["org_b_id"]
    await _queue_doc(org_a, doc_id="a-doc")

    assert await q.get_status(str(org_a), "a-doc") is not None
    assert await q.get_status(str(org_b), "a-doc") is None


async def test_delete_row_removes_only_the_targeted_document(app, seeded_orgs):
    org_id = seeded_orgs["org_a_id"]
    await _queue_doc(org_id, doc_id="keep")
    await _queue_doc(org_id, doc_id="drop")

    assert await q.delete_row(str(org_id), "drop") is True
    assert await q.get_status(str(org_id), "drop") is None
    assert await q.get_status(str(org_id), "keep") is not None

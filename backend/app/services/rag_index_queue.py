"""Row lifecycle for the ``rag_documents`` registry / indexing queue.

Separate from ``rag_ingestion`` on purpose: that module owns the pipeline and
has no database awareness at all (it talks only to S3, rag-inference, and
Qdrant). This module owns persistence, tenant scoping, and claim/finalize
concurrency — the same split as ``compliance_report_queue`` beside
``compliance_report_service``.

**Postgres only.** Uses ``ON CONFLICT`` and ``FOR UPDATE SKIP LOCKED``; there
is deliberately no SQLite fallback, matching the RLS the table carries.

Every query sets ``app.current_org_id`` first: ``rag_documents`` has FORCE ROW
LEVEL SECURITY, so even the worker sees zero rows without a tenant context.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import structlog
from sqlalchemy import delete, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.core.config import settings
from app.db.database import AsyncSessionLocal
from app.db.models import Organization, RagDocument

logger = structlog.get_logger()

# Bounded work per org per pass, so one busy tenant cannot starve the others.
# Mirrors the range(100) cap in compliance_report_queue._publish_queued_for_org.
MAX_CLAIMS_PER_ORG_PER_PASS = 100

TERMINAL_STATUSES = ("indexed", "skipped", "failed")


@dataclass(frozen=True)
class ClaimedDocument:
    """A row this worker has exclusively claimed for one indexing pass."""

    org_id: str
    doc_id: str
    s3_key: str
    filename: str
    kind: str
    attempts: int
    started_at: datetime


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _set_org(session, org_id: Any) -> None:
    await session.execute(
        text("SELECT set_config('app.current_org_id', :org, true)"),
        {"org": str(org_id)},
    )


def _to_dict(row: RagDocument) -> Dict[str, Any]:
    return {
        "doc_id": row.doc_id,
        "status": row.status,
        "kind": row.kind,
        "filename": row.filename,
        "s3_key": row.s3_key,
        "num_blocks": row.num_blocks,
        "num_chunks": row.num_chunks,
        "reason": row.reason,
        "error": row.error,
        "attempts": row.attempts,
        "created_at": row.created_at,
        "started_at": row.started_at,
        "completed_at": row.completed_at,
    }


async def upsert_queued(
    *,
    org_id: str,
    doc_id: str,
    uploaded_by: Optional[str],
    filename: str,
    s3_key: str,
    kind: str,
) -> None:
    """Record a freshly stored blob as awaiting indexing.

    Re-ingesting an existing doc_id resets the SAME row back to 'queued' and
    clears prior outcome fields, so there is exactly one row per document and
    the status endpoint never has to disambiguate attempts.
    """
    now = _now()
    fresh = {
        "uploaded_by": uploaded_by,
        "filename": filename,
        "s3_key": s3_key,
        "kind": kind,
        "status": "queued",
        "attempts": 0,
        "num_blocks": 0,
        "num_chunks": 0,
        "reason": None,
        "error": None,
        "updated_at": now,
        "started_at": None,
        "completed_at": None,
    }
    async with AsyncSessionLocal() as session:
        await _set_org(session, org_id)
        await session.execute(
            pg_insert(RagDocument.__table__)
            .values(
                organization_id=str(org_id),
                doc_id=doc_id,
                created_at=now,
                **fresh,
            )
            .on_conflict_do_update(
                constraint="uq_rag_documents_org_doc",
                set_=fresh,
            )
        )
        await session.commit()


async def claim_next(org_id: str) -> Optional[ClaimedDocument]:
    """Claim the oldest queued document for this org, or return None.

    SKIP LOCKED is what makes this safe to run from several worker replicas at
    once: a row another transaction already holds is stepped over rather than
    blocking.
    """
    async with AsyncSessionLocal() as session:
        await _set_org(session, org_id)
        row = (
            await session.execute(
                select(RagDocument)
                .where(
                    RagDocument.organization_id == str(org_id),
                    RagDocument.status == "queued",
                )
                .order_by(RagDocument.created_at)
                .limit(1)
                .with_for_update(skip_locked=True)
            )
        ).scalar_one_or_none()
        if row is None:
            return None

        claimed_at = _now()
        row.status = "indexing"
        row.attempts += 1
        row.started_at = claimed_at
        row.updated_at = claimed_at
        claimed = ClaimedDocument(
            org_id=str(org_id),
            doc_id=row.doc_id,
            s3_key=row.s3_key,
            filename=row.filename,
            kind=row.kind,
            attempts=row.attempts,
            started_at=claimed_at,
        )
        await session.commit()
        logger.info(
            "rag_index_queue.claimed",
            doc_id=claimed.doc_id,
            attempts=claimed.attempts,
        )
        return claimed


async def finalize(
    *,
    org_id: str,
    doc_id: str,
    attempts: int,
    started_at: datetime,
    status: str,
    num_blocks: int = 0,
    num_chunks: int = 0,
    reason: Optional[str] = None,
    error: Optional[str] = None,
) -> bool:
    """Write a terminal status, but only if our claim is still the current one.

    The guard is ``status='indexing' AND attempts=:attempts AND
    started_at=:started_at`` — all three, not just ``attempts``. ``attempts``
    alone is not enough: ``upsert_queued`` resets it to 0 on every re-ingest,
    and the next ``claim_next`` walks it back up from 1, so the same value
    recycles across generations of the same doc_id (an ABA hazard). Two
    workers racing on successive generations can both see ``attempts == 1``.
    ``started_at`` is stamped fresh (microsecond precision) inside the locking
    transaction in ``claim_next`` and nulled by ``upsert_queued``, so it is
    the piece that actually identifies one claimed pass. If the caller
    re-uploaded this doc_id mid-pass, the row is already back to 'queued'
    with a new generation's attempts/started_at, this UPDATE matches nothing,
    and the stale result is discarded instead of overwriting the new work.
    Returns True if the write landed.
    """
    if status not in TERMINAL_STATUSES:
        raise ValueError(f"not a terminal status: {status}")
    now = _now()
    async with AsyncSessionLocal() as session:
        await _set_org(session, org_id)
        result = await session.execute(
            update(RagDocument)
            .where(
                RagDocument.organization_id == str(org_id),
                RagDocument.doc_id == doc_id,
                RagDocument.status == "indexing",
                RagDocument.attempts == attempts,
                RagDocument.started_at == started_at,
            )
            .values(
                status=status,
                num_blocks=num_blocks,
                num_chunks=num_chunks,
                reason=reason,
                error=error,
                completed_at=now,
                updated_at=now,
            )
        )
        await session.commit()
    landed = result.rowcount > 0
    if not landed:
        logger.info("rag_index_queue.finalize_discarded", doc_id=doc_id)
    return landed


async def requeue_or_fail(
    *, org_id: str, doc_id: str, attempts: int, started_at: datetime, error: str
) -> Optional[str]:
    """Return a failed pass to 'queued', or to 'failed' once attempts run out.

    Guarded on ``status='indexing' AND attempts=:attempts AND
    started_at=:started_at`` for the same ABA reason as ``finalize``:
    ``attempts`` resets to 0 on every re-ingest and recycles across
    generations of the same doc_id, so it cannot alone distinguish this pass
    from a later one. Without ``started_at`` in the guard, a worker finishing
    a stale pass could flip a *different*, currently-live claim back to
    'queued' — releasing a document a second worker is still indexing, so a
    third worker could start indexing it concurrently.

    Returns the status actually written, or ``None`` if the guard matched no
    row (our claim is stale and the write was correctly discarded) — callers
    must not treat ``None`` as "failed".
    """
    next_status = (
        "queued" if attempts < settings.RAG_INDEX_MAX_ATTEMPTS else "failed"
    )
    now = _now()
    async with AsyncSessionLocal() as session:
        await _set_org(session, org_id)
        result = await session.execute(
            update(RagDocument)
            .where(
                RagDocument.organization_id == str(org_id),
                RagDocument.doc_id == doc_id,
                RagDocument.status == "indexing",
                RagDocument.attempts == attempts,
                RagDocument.started_at == started_at,
            )
            .values(
                status=next_status,
                error=error[:2000],
                started_at=None,
                completed_at=now if next_status == "failed" else None,
                updated_at=now,
            )
        )
        await session.commit()
    if result.rowcount == 0:
        logger.info("rag_index_queue.requeue_discarded", doc_id=doc_id)
        return None
    logger.warning(
        "rag_index_queue.pass_failed",
        doc_id=doc_id,
        attempts=attempts,
        next_status=next_status,
    )
    return next_status


async def recover_stale() -> int:
    """Re-queue rows abandoned in 'indexing' by a crashed or killed worker."""
    cutoff = _now() - timedelta(
        seconds=settings.RAG_INDEX_STALE_INDEXING_SECONDS
    )
    recovered = 0
    for org_id in await list_org_ids():
        async with AsyncSessionLocal() as session:
            await _set_org(session, org_id)
            rows = (
                await session.execute(
                    select(RagDocument)
                    .where(
                        RagDocument.organization_id == str(org_id),
                        RagDocument.status == "indexing",
                        RagDocument.updated_at <= cutoff,
                    )
                    .with_for_update(skip_locked=True)
                )
            ).scalars().all()
            for row in rows:
                exhausted = row.attempts >= settings.RAG_INDEX_MAX_ATTEMPTS
                row.status = "failed" if exhausted else "queued"
                if exhausted:
                    row.error = "Indexing abandoned; worker did not finish."
                    row.completed_at = _now()
                else:
                    row.started_at = None
                row.updated_at = _now()
                recovered += 1
            if rows:
                await session.commit()
    if recovered:
        logger.warning("rag_index_queue.recovered_stale", count=recovered)
    return recovered


async def get_status(org_id: str, doc_id: str) -> Optional[Dict[str, Any]]:
    async with AsyncSessionLocal() as session:
        await _set_org(session, org_id)
        row = (
            await session.execute(
                select(RagDocument).where(
                    RagDocument.organization_id == str(org_id),
                    RagDocument.doc_id == doc_id,
                )
            )
        ).scalar_one_or_none()
        return _to_dict(row) if row else None


async def list_for_org(org_id: str) -> List[Dict[str, Any]]:
    async with AsyncSessionLocal() as session:
        await _set_org(session, org_id)
        rows = (
            await session.execute(
                select(RagDocument)
                .where(RagDocument.organization_id == str(org_id))
                .order_by(RagDocument.created_at.desc())
            )
        ).scalars().all()
        return [_to_dict(row) for row in rows]


async def delete_row(org_id: str, doc_id: str) -> bool:
    async with AsyncSessionLocal() as session:
        await _set_org(session, org_id)
        result = await session.execute(
            delete(RagDocument).where(
                RagDocument.organization_id == str(org_id),
                RagDocument.doc_id == doc_id,
            )
        )
        await session.commit()
        return result.rowcount > 0


async def list_org_ids() -> List[str]:
    """All tenant ids, so the worker can poll each with its own RLS context."""
    async with AsyncSessionLocal() as session:
        return [
            str(org_id)
            for org_id in (
                await session.execute(select(Organization.id))
            ).scalars().all()
        ]

"""Per-tenant ingest quota and rate limit.

Runs against real Postgres because the budget is measured from ``rag_documents``
itself — a stubbed count would test nothing about the query that enforces it.
Every limit is monkeypatched to a small number so the tests stay fast.
"""

from __future__ import annotations

import pytest

from tests._realdb import require_testcontainers
require_testcontainers()  # FS-808: skips on a laptop, FAILS when REQUIRE_REALDB=1

from app.core.config import settings  # noqa: E402
from app.services import rag_index_queue as q  # noqa: E402


async def _queue_doc(org_id, doc_id, size_bytes=0):
    await q.upsert_queued(
        org_id=str(org_id),
        doc_id=doc_id,
        uploaded_by=None,
        filename=f"{doc_id}.txt",
        s3_key=f"{org_id}/{doc_id}/{doc_id}.txt",
        kind="text",
        size_bytes=size_bytes,
    )


@pytest.fixture
def unlimited(monkeypatch):
    """Start from no limits so each test opts into exactly the one it checks."""
    monkeypatch.setattr(settings, "RAG_MAX_DOCUMENTS_PER_ORG", 0)
    monkeypatch.setattr(settings, "RAG_MAX_TOTAL_BYTES_PER_ORG", 0)
    monkeypatch.setattr(settings, "RAG_INGEST_RATE_LIMIT_PER_MINUTE", 0)


class _FakeDocs:
    available = True
    raw_bucket = "raw"

    async def ensure_bucket(self, bucket):
        return None

    async def put_document_stream(self, *, key, fileobj, content_type, metadata):
        fileobj.read()
        return key

    async def list_documents(self, prefix="", bucket=None):
        return []


@pytest.fixture(autouse=True)
def _stub_document_store(monkeypatch):
    """No SeaweedFS in the test env; quota is decided before the blob write."""
    import app.services.rag_ingestion as ingestion
    import app.api.rag as rag_api

    monkeypatch.setattr(ingestion.get_ingestion_pipeline(), "docs", _FakeDocs())
    monkeypatch.setattr(rag_api, "get_document_store", lambda: _FakeDocs())


async def test_usage_counts_documents_and_bytes(app, seeded_orgs, unlimited):
    org_id = seeded_orgs["org_a_id"]
    await _queue_doc(org_id, "d1", size_bytes=100)
    await _queue_doc(org_id, "d2", size_bytes=250)

    usage = await q.quota_usage(str(org_id))

    assert usage.documents == 2
    assert usage.total_bytes == 350


async def test_usage_is_scoped_to_one_org(app, seeded_orgs, unlimited):
    """Another tenant's documents must not consume this org's budget."""
    await _queue_doc(seeded_orgs["org_a_id"], "a1", size_bytes=1000)
    await _queue_doc(seeded_orgs["org_b_id"], "b1", size_bytes=9999)

    usage = await q.quota_usage(str(seeded_orgs["org_a_id"]))

    assert usage.documents == 1
    assert usage.total_bytes == 1000


async def test_zero_limits_allow_everything(app, seeded_orgs, unlimited):
    await _queue_doc(seeded_orgs["org_a_id"], "d1", size_bytes=10**9)

    rejection = await q.check_ingest_quota(
        org_id=str(seeded_orgs["org_a_id"]), doc_id="d2", size_bytes=10**9
    )

    assert rejection is None


async def test_document_count_quota_rejects_with_409(
    app, seeded_orgs, unlimited, monkeypatch
):
    org_id = seeded_orgs["org_a_id"]
    monkeypatch.setattr(settings, "RAG_MAX_DOCUMENTS_PER_ORG", 2)
    await _queue_doc(org_id, "d1")
    await _queue_doc(org_id, "d2")

    rejection = await q.check_ingest_quota(
        org_id=str(org_id), doc_id="d3", size_bytes=1
    )

    assert rejection is not None
    assert rejection.status == 409
    assert "Document quota" in rejection.detail


async def test_byte_quota_rejects_with_409(app, seeded_orgs, unlimited, monkeypatch):
    org_id = seeded_orgs["org_a_id"]
    monkeypatch.setattr(settings, "RAG_MAX_TOTAL_BYTES_PER_ORG", 1000)
    await _queue_doc(org_id, "d1", size_bytes=900)

    rejection = await q.check_ingest_quota(
        org_id=str(org_id), doc_id="d2", size_bytes=200
    )

    assert rejection is not None
    assert rejection.status == 409
    assert "Storage quota" in rejection.detail


async def test_rate_limit_rejects_with_429(app, seeded_orgs, unlimited, monkeypatch):
    org_id = seeded_orgs["org_a_id"]
    monkeypatch.setattr(settings, "RAG_INGEST_RATE_LIMIT_PER_MINUTE", 2)
    await _queue_doc(org_id, "d1")
    await _queue_doc(org_id, "d2")

    rejection = await q.check_ingest_quota(
        org_id=str(org_id), doc_id="d3", size_bytes=1
    )

    assert rejection is not None
    assert rejection.status == 429, "a rate limit is retryable, so 429 not 409"


async def test_reingest_does_not_consume_a_new_document_slot(
    app, seeded_orgs, unlimited, monkeypatch
):
    """Re-uploading an existing doc_id replaces a row; it must not be charged."""
    org_id = seeded_orgs["org_a_id"]
    monkeypatch.setattr(settings, "RAG_MAX_DOCUMENTS_PER_ORG", 2)
    await _queue_doc(org_id, "d1")
    await _queue_doc(org_id, "d2")

    rejection = await q.check_ingest_quota(
        org_id=str(org_id), doc_id="d1", size_bytes=1
    )

    assert rejection is None, "an org at its cap must still be able to correct a doc"


async def test_reingest_is_charged_only_the_size_delta(
    app, seeded_orgs, unlimited, monkeypatch
):
    org_id = seeded_orgs["org_a_id"]
    monkeypatch.setattr(settings, "RAG_MAX_TOTAL_BYTES_PER_ORG", 1000)
    await _queue_doc(org_id, "d1", size_bytes=900)

    # 950 replaces 900, so the projected total is 950 — under the cap — even
    # though 900 + 950 would be over it.
    allowed = await q.check_ingest_quota(
        org_id=str(org_id), doc_id="d1", size_bytes=950
    )
    # 1100 replacing 900 genuinely exceeds the cap.
    refused = await q.check_ingest_quota(
        org_id=str(org_id), doc_id="d1", size_bytes=1100
    )

    assert allowed is None
    assert refused is not None and refused.status == 409


async def test_size_bytes_round_trips_through_the_status_row(
    app, seeded_orgs, unlimited
):
    org_id = seeded_orgs["org_a_id"]
    await _queue_doc(org_id, "d1", size_bytes=4242)

    row = await q.get_status(str(org_id), "d1")

    assert row["size_bytes"] == 4242


async def test_ingest_endpoint_returns_429_when_rate_limited(
    app, client_a, seeded_orgs, unlimited, monkeypatch
):
    monkeypatch.setattr(settings, "RAG_INGEST_RATE_LIMIT_PER_MINUTE", 1)
    await _queue_doc(seeded_orgs["org_a_id"], "already-ingested")

    resp = await client_a.post(
        "/api/v1/rag/ingest",
        files={"file": ("a.txt", b"hello", "text/plain")},
        data={"doc_id": "over-the-limit"},
    )

    assert resp.status_code == 429, resp.text


async def test_documents_listing_reports_quota(app, client_a, seeded_orgs, unlimited):
    await _queue_doc(seeded_orgs["org_a_id"], "d1", size_bytes=123)

    resp = await client_a.get("/api/v1/rag/documents")

    assert resp.status_code == 200
    quota = resp.json()["quota"]
    assert quota["documents"] == 1
    assert quota["total_bytes"] == 123
    assert quota["max_documents"] is None, "0 must surface as unlimited, not 0"

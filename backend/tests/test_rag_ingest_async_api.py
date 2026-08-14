"""POST /rag/ingest returns 202 and the status endpoint is org-scoped."""

from __future__ import annotations

import pytest

pytest.importorskip("testcontainers")

from app.services import rag_index_queue as q  # noqa: E402


class _FakeDocs:
    available = True
    raw_bucket = "raw"

    async def ensure_bucket(self, bucket):
        return None

    async def put_document(self, *, key, data, content_type, metadata):
        return key

    async def put_document_stream(self, *, key, fileobj, content_type, metadata):
        # The API path streams the spooled upload rather than reading it, so
        # this is the method the route actually exercises. Draining it here
        # mirrors a real uploader consuming the stream.
        fileobj.read()
        return key

    async def list_documents(self, prefix="", bucket=None):
        return []


@pytest.fixture(autouse=True)
def _stub_document_store(monkeypatch):
    """No SeaweedFS in the test env; the blob write is not what we're testing."""
    import app.services.rag_ingestion as ingestion
    import app.api.rag as rag_api

    pipeline = ingestion.get_ingestion_pipeline()
    monkeypatch.setattr(pipeline, "docs", _FakeDocs())
    monkeypatch.setattr(rag_api, "get_document_store", lambda: _FakeDocs())


async def test_ingest_returns_202_and_queues_the_document(client_a, seeded_orgs):
    resp = await client_a.post(
        "/api/v1/rag/ingest",
        files={"file": ("a.txt", b"hello world", "text/plain")},
        data={"doc_id": "api-doc-1"},
    )

    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body["stored"] is True
    assert body["indexed"] is False
    assert body["status"] == "queued"
    assert body["doc_id"] == "api-doc-1"

    row = await q.get_status(str(seeded_orgs["org_a_id"]), "api-doc-1")
    assert row["status"] == "queued"


async def test_status_endpoint_round_trips(client_a):
    await client_a.post(
        "/api/v1/rag/ingest",
        files={"file": ("a.txt", b"hello", "text/plain")},
        data={"doc_id": "api-doc-2"},
    )

    resp = await client_a.get("/api/v1/rag/documents/api-doc-2/status")

    assert resp.status_code == 200
    body = resp.json()
    assert body["doc_id"] == "api-doc-2"
    assert body["status"] == "queued"
    assert body["kind"] == "text"


async def test_status_404_for_unknown_document(client_a):
    resp = await client_a.get("/api/v1/rag/documents/never-uploaded/status")
    assert resp.status_code == 404


async def test_status_is_not_readable_across_orgs(client_a, client_b):
    await client_a.post(
        "/api/v1/rag/ingest",
        files={"file": ("a.txt", b"hello", "text/plain")},
        data={"doc_id": "org-a-secret"},
    )

    resp = await client_b.get("/api/v1/rag/documents/org-a-secret/status")

    assert resp.status_code == 404, "org B must not observe org A's document"


async def test_malformed_doc_id_is_rejected(client_a):
    resp = await client_a.post(
        "/api/v1/rag/ingest",
        files={"file": ("a.txt", b"hello", "text/plain")},
        data={"doc_id": "../escape"},
    )
    assert resp.status_code == 422


async def test_documents_listing_keeps_keys_and_adds_metadata(client_a):
    await client_a.post(
        "/api/v1/rag/ingest",
        files={"file": ("a.txt", b"hello", "text/plain")},
        data={"doc_id": "listed-doc"},
    )

    resp = await client_a.get("/api/v1/rag/documents")

    assert resp.status_code == 200
    body = resp.json()
    assert "keys" in body and "count" in body, "back-compat fields must remain"
    assert any(d["doc_id"] == "listed-doc" for d in body["documents"])

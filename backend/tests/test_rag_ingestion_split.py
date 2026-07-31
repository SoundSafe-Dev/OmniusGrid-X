"""The ingest pipeline splits at the blob-durable seam.

store_document must do only the fast work (blob + queued row) and must NOT
parse, chunk, embed, or upsert — that is the whole point of the 202 contract.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.services.rag_ingestion import IngestionPipeline
from app.services.rag_index_queue import ClaimedDocument


class _FakeDocs:
    available = True
    raw_bucket = "raw"

    def __init__(self, blob: bytes = b""):
        self.blob = blob
        self.put_calls = []

    async def ensure_bucket(self, bucket):
        return None

    async def put_document(self, *, key, data, content_type, metadata):
        self.put_calls.append(key)
        self.blob = data
        return key

    async def get_document(self, key, bucket=None):
        return self.blob


class _ExplodingInference:
    available = True

    async def embed(self, *args, **kwargs):
        raise AssertionError("store_document must not embed")


class _ExplodingVectors:
    available = True

    async def ensure_collection(self):
        raise AssertionError("store_document must not touch the vector store")

    async def delete_by_doc(self, doc_id):
        raise AssertionError("store_document must not touch the vector store")

    async def upsert_chunks(self, points):
        raise AssertionError("store_document must not touch the vector store")


def _pipeline(docs, inference=None, vectors=None) -> IngestionPipeline:
    pipeline = IngestionPipeline.__new__(IngestionPipeline)
    pipeline.docs = docs
    pipeline.inference = inference or _ExplodingInference()
    pipeline.vectors = vectors or _ExplodingVectors()
    pipeline.batch = 8
    return pipeline


async def test_store_document_stores_blob_and_queues_without_indexing(
    monkeypatch,
):
    docs = _FakeDocs()
    queued = {}

    async def _fake_upsert_queued(**kwargs):
        queued.update(kwargs)

    monkeypatch.setattr(
        "app.services.rag_ingestion.upsert_queued", _fake_upsert_queued
    )

    result = await _pipeline(docs).store_document(
        content=b"hello world",
        filename="a.txt",
        org_id="org-1",
        doc_id="doc-1",
        content_type="text/plain",
    )

    assert result.stored is True
    assert result.indexed is False
    assert result.status == "queued"
    assert result.s3_key == "org-1/doc-1/a.txt"
    assert docs.put_calls == ["org-1/doc-1/a.txt"]
    assert queued["doc_id"] == "doc-1"
    assert queued["kind"] == "text"


async def test_store_document_generates_a_doc_id_when_omitted(monkeypatch):
    async def _noop(**kwargs):
        return None

    monkeypatch.setattr("app.services.rag_ingestion.upsert_queued", _noop)

    result = await _pipeline(_FakeDocs()).store_document(
        content=b"x", filename="a.txt", org_id="org-1"
    )

    assert result.doc_id
    assert result.s3_key == f"org-1/{result.doc_id}/a.txt"


async def test_store_document_rejects_unsafe_doc_id(monkeypatch):
    from app.services.document_store import InvalidDocumentId

    async def _noop(**kwargs):
        return None

    monkeypatch.setattr("app.services.rag_ingestion.upsert_queued", _noop)

    with pytest.raises(InvalidDocumentId):
        await _pipeline(_FakeDocs()).store_document(
            content=b"x", filename="a.txt", org_id="org-1", doc_id="../org-2"
        )


async def test_index_document_reports_skipped_for_unsupported_kind():
    claimed = ClaimedDocument(
        org_id="org-1",
        doc_id="doc-1",
        s3_key="org-1/doc-1/a.bin",
        filename="a.bin",
        kind="unsupported",
        attempts=1,
        started_at=datetime.now(timezone.utc),
    )

    result = await _pipeline(_FakeDocs(b"binary")).index_document(claimed)

    assert result.status == "skipped"
    assert result.indexed is False
    assert "Unsupported file type" in result.reason


async def test_index_document_reports_skipped_when_no_text_extracted():
    claimed = ClaimedDocument(
        org_id="org-1",
        doc_id="doc-1",
        s3_key="org-1/doc-1/a.txt",
        filename="a.txt",
        kind="text",
        attempts=1,
        started_at=datetime.now(timezone.utc),
    )

    result = await _pipeline(_FakeDocs(b"   ")).index_document(claimed)

    assert result.status == "skipped"
    assert result.num_blocks == 0

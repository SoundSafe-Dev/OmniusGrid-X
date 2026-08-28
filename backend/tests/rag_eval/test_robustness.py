"""Robustness / guardrails: malformed and boundary inputs must degrade
gracefully (stored-not-indexed or a clean 4xx) and never 500. Also exercises the
new upload-size cap. Each test cleans up any doc it creates."""

import os

import pytest

from client import ApiError

pytestmark = pytest.mark.robustness


def test_empty_file_rejected(rag_client, run_id, record):
    status, body = rag_client.ingest_bytes("empty.txt", "text/plain", b"", f"pytest-empty-{run_id}")
    record("robustness", "empty_rejected", status == 400, note=f"status={status}")
    assert status == 400, f"empty upload should be 400, got {status}: {body}"


def test_unsupported_type_stored_not_indexed(rag_client, run_id, record):
    doc_id = f"pytest-unsup-{run_id}"
    try:
        status, body = rag_client.ingest_bytes(
            "thing.xyz", "application/octet-stream", b"arbitrary bytes here", doc_id)
        assert status == 202, f"expected 202 (queued), got {status}: {body}"
        assert body.get("stored") is True

        # `indexed` is always False in the 202 body regardless of outcome, so
        # the real assertion is the terminal status reached after indexing.
        try:
            terminal = rag_client.await_indexed(doc_id)
        except ApiError as e:
            pytest.fail(f"doc {doc_id} never reached a terminal status: {e}")
        ok = (
            status == 202
            and body.get("stored") is True
            and terminal.get("status") == "skipped"
            and terminal.get("kind") == "unsupported"
        )
        record("robustness", "unsupported_type", ok,
               note=f"status={status} terminal={terminal.get('status')} kind={terminal.get('kind')}")
        assert terminal.get("status") == "skipped"
        assert terminal.get("kind") == "unsupported"
    finally:
        try:
            rag_client.delete_doc(doc_id)
        except ApiError:
            pass


def test_non_utf8_graceful(rag_client, run_id, record):
    doc_id = f"pytest-utf-{run_id}"
    data = b"\xff\xfe\x00 acid rinse additive at 0.5% for 8 minutes \x80\x81"
    try:
        status, body = rag_client.ingest_bytes("weird.txt", "text/plain", data, doc_id)
        assert status == 202, f"non-UTF8 must not 500, got {status}: {body}"
        assert body.get("stored") is True

        # Non-UTF8 input is designed to fall back to plain-text chunking rather
        # than error, so this may legitimately end as "indexed" -- the only
        # thing we assert is that it never lands on "failed".
        try:
            terminal = rag_client.await_indexed(doc_id)
        except ApiError as e:
            pytest.fail(f"doc {doc_id} never reached a terminal status: {e}")
        ok = status == 202 and body.get("stored") is True and terminal.get("status") != "failed"
        record("robustness", "non_utf8", ok,
               note=f"status={status} terminal={terminal.get('status')} reason={terminal.get('reason')}")
        assert terminal.get("status") != "failed", f"non-UTF8 must not fail: {terminal}"
    finally:
        try:
            rag_client.delete_doc(doc_id)
        except ApiError:
            pass


def test_corrupt_pdf_graceful(rag_client, run_id, record):
    doc_id = f"pytest-badpdf-{run_id}"
    data = b"%PDF-1.4 this is not actually a valid pdf body at all"
    try:
        status, body = rag_client.ingest_bytes("bad.pdf", "application/pdf", data, doc_id)
        assert status == 202, f"corrupt PDF must not 500, got {status}: {body}"
        assert body.get("stored") is True  # blob stored; indexing may be skipped with a reason

        # A corrupt PDF is a parse failure, which this design classifies as
        # "skipped" (a decided outcome) -- NOT "failed" (reserved for
        # retryable infra faults). Landing on "failed" would be a real bug.
        try:
            terminal = rag_client.await_indexed(doc_id)
        except ApiError as e:
            pytest.fail(f"doc {doc_id} never reached a terminal status: {e}")
        ok = status == 202 and body.get("stored") is True and terminal.get("status") != "failed"
        record("robustness", "corrupt_pdf", ok,
               note=f"status={status} terminal={terminal.get('status')} reason={terminal.get('reason')}")
        assert terminal.get("status") != "failed", f"corrupt PDF must not fail: {terminal}"
    finally:
        try:
            rag_client.delete_doc(doc_id)
        except ApiError:
            pass


@pytest.mark.skipif(
    os.environ.get("RAG_TEST_OVERSIZED") != "1",
    reason="oversized upload test sends >50MiB; set RAG_TEST_OVERSIZED=1 to run",
)
def test_oversized_rejected(rag_client, run_id, record):
    # Just over the default RAG_MAX_UPLOAD_BYTES (50 MiB).
    data = b"x" * (50 * 1024 * 1024 + 1)
    status, body = rag_client.ingest_bytes("big.txt", "text/plain", data, f"pytest-big-{run_id}", timeout=300)
    record("robustness", "oversized_413", status == 413, note=f"status={status}")
    assert status == 413, f"oversized upload should be 413, got {status}"

"""doc_id must not escape the tenant prefix or break the 3-segment key layout.

The object key is ``{org_id}/{doc_id}/{filename}`` and doc_id is caller-supplied
free text, so an unvalidated value can write outside the caller's org prefix.
"""

import pytest

from app.services.document_store import (
    InvalidDocumentId,
    build_document_key,
    validate_doc_id,
)


@pytest.mark.parametrize(
    "doc_id",
    [
        "simple",
        "eval-pdf-abc123",
        "with.dots_and-dashes",
        "0123456789abcdef0123456789abcdef",  # server-generated uuid4().hex
        "a" * 128,
    ],
)
def test_accepts_safe_doc_ids(doc_id):
    assert validate_doc_id(doc_id) == doc_id


@pytest.mark.parametrize(
    "doc_id",
    [
        "../victim-org",
        "a/b",
        "..",
        "",
        "a" * 129,
        "has space",
        "semi;colon",
        "null\x00byte",
        "foo\n",  # trailing newline (CRLF/log-injection vector)
        "a\n",
        ".\n",
        "..\n",
        "foo\r",  # trailing carriage return
        "..\r",
    ],
)
def test_rejects_unsafe_doc_ids(doc_id):
    with pytest.raises(InvalidDocumentId):
        validate_doc_id(doc_id)


def test_build_document_key_rejects_traversal():
    with pytest.raises(InvalidDocumentId):
        build_document_key("org-1", "../org-2", "secret.pdf")


def test_build_document_key_still_builds_three_segments():
    key = build_document_key("org-1", "doc-9", "report.pdf")
    assert key == "org-1/doc-9/report.pdf"
    assert len(key.split("/")) == 3

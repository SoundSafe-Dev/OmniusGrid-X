"""Lifecycle: idempotent re-ingest (no duplicate vectors) and delete actually
removes content from retrieval. These manage their own docs (not the per-format
fixture) and clean up after themselves."""

import pytest

from client import FORMATS, DOCS_DIR

pytestmark = pytest.mark.lifecycle


def test_idempotent_reingest(rag_client, run_id, record):
    fmt = "md"
    filename, ctype = FORMATS[fmt]
    doc_id = f"pytest-idem-{run_id}"
    rag_client.wipe_all()
    try:
        first = rag_client.ingest(DOCS_DIR / filename, ctype, doc_id)
        second = rag_client.ingest(DOCS_DIR / filename, ctype, doc_id)  # same doc_id
        same_count = first.get("num_chunks") == second.get("num_chunks")
        single_doc = doc_id in rag_client.list_doc_ids()
        record("lifecycle", "idempotent_reingest", same_count and single_doc,
               note=f"chunks {first.get('num_chunks')}->{second.get('num_chunks')}")
        assert same_count, (f"re-ingest changed chunk count "
                            f"{first.get('num_chunks')} -> {second.get('num_chunks')} (duplication?)")
        assert single_doc, "re-ingested doc_id not present as a single document"
    finally:
        rag_client.wipe_all()


def test_delete_removes_from_retrieval(rag_client, run_id, record):
    fmt = "txt"
    filename, ctype = FORMATS[fmt]
    doc_id = f"pytest-del-{run_id}"
    probe = "acid rinse contact time"
    rag_client.wipe_all()
    try:
        rag_client.ingest(DOCS_DIR / filename, ctype, doc_id)
        before = rag_client.query(probe, generate=False)
        assert before.get("citations"), "expected citations before delete"

        rag_client.delete_doc(doc_id)
        after = rag_client.query(probe, generate=False)
        gone = not after.get("citations")
        record("lifecycle", "delete_purges", gone,
               note=f"citations {len(before.get('citations', []))}->{len(after.get('citations', []))}")
        assert gone, "content still retrievable after delete"
    finally:
        rag_client.wipe_all()

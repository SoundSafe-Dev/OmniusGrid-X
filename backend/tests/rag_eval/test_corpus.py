"""
Multi-document retrieval discrimination.

The per-format tests index ONE document at a time, so they can't tell whether
retrieval picks the *right* document when several are present — the failure mode
that matters most once a corpus has more than one document. Here we index the
whole corpus at once (one canonical rendering per document) and assert that each
document-anchored query is answered from the document it belongs to.

Each query's expected home document is its ``doc_id``. Out-of-corpus / scope
negatives (``manual``) have no home document, so they're excluded. One selectable
cell per query:
    pytest -m corpus
    pytest -k "discrimination and W5"
"""

import pytest

from corpus import DOCS, DOC_BY_ID, doc_id_for_citation
from queries import ALL_QUERIES

pytestmark = pytest.mark.corpus

# The single format used to populate the corpus for this phase. Markdown is a
# clean, faithful rendering; discrimination is about which *document* wins, not
# which format, so one format per doc keeps the index unambiguous.
CORPUS_FORMAT = "md"

DISCRIMINATION_QUERIES = [q for q in ALL_QUERIES if not q["manual"]]


@pytest.fixture(scope="module")
def corpus_indexed(rag_client, run_id):
    """Index EVERY document (one canonical rendering each) into one org, so
    queries must discriminate between them. Wipes before and after."""
    rag_client.wipe_all()
    ingested = {}
    for doc in DOCS:
        ingest_id = f"corpus-{doc.id}-{run_id}"
        ing = rag_client.ingest(doc.path(CORPUS_FORMAT), doc.ctype(CORPUS_FORMAT), ingest_id)
        assert ing.get("indexed"), f"failed to index {doc.id}: {ing.get('reason')}"
        ingested[doc.id] = ingest_id
    yield {"client": rag_client, "ingested": ingested}
    rag_client.wipe_all()


@pytest.mark.parametrize("spec", DISCRIMINATION_QUERIES, ids=[q["id"] for q in DISCRIMINATION_QUERIES])
def test_retrieval_cites_correct_document(corpus_indexed, spec, record):
    """With all documents indexed, the top citation for a document-anchored query
    must come from that query's own document."""
    client = corpus_indexed["client"]
    expected = spec["doc_id"]
    resp = client.query(spec["query"], generate=False, top_n=5)
    citations = resp.get("citations", [])

    top_doc = doc_id_for_citation(citations[0]) if citations else ""
    cited_docs = [doc_id_for_citation(c) for c in citations]
    expected_in_topk = expected in cited_docs

    title = DOC_BY_ID[expected].title[:32]
    record("corpus", spec["id"], top_doc == expected, fmt=expected,
           note=f"top={top_doc or 'none'} expected={expected} "
                f"in_top5={expected_in_topk} ({title})")

    assert citations, f"{spec['id']}: no citations returned with full corpus indexed"
    assert top_doc == expected, (
        f"{spec['id']}: top citation is from '{top_doc or 'unknown'}', "
        f"expected '{expected}'. top-5 docs={cited_docs}")

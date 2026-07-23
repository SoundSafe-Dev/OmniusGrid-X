"""
Hybrid retrieval: prove BOTH halves of the dense+sparse fusion actually work.

The /query API is hybrid-only (dense ANN + sparse lexical, fused server-side by
RRF), with no mode toggle — so we isolate each half black-box, with queries that
only one half can satisfy:

  * SPARSE / lexical  — a bare identifier or exact number (e.g. "SOP-QA-020",
    "250 RLU"). These have almost no semantic content, so a dense-only retriever
    would flounder; retrieving the exact-token chunk proves the sparse half fires.
  * DENSE / semantic  — a natural-language paraphrase with ~zero word overlap
    with its target chunk (e.g. "which cleaning chemical is pumped through the
    line while it is hot" -> the alkaline-detergent step). A sparse-only retriever
    has nothing to match on; retrieving the target proves the dense half fires.

If a probe of one mode silently stopped contributing (a real regression risk for
exact-term compliance lookups — SOP codes, thresholds), its cell here goes red
while the ordinary retrieval tests, which most queries can satisfy either way,
would stay green.
"""

import pytest

from corpus import DOC_BY_ID, doc_id_for_citation

pytestmark = pytest.mark.hybrid

# One clean rendering is enough — this tests fusion, not format parsing.
HYBRID_FORMAT = "md"

# Each probe: the mode it isolates, the query, and substrings that prove the
# right chunk was retrieved (matched against citation snippet + source).
HYBRID_PROBES = {
    "sop-qa-014": [
        {"id": "sparse_code", "mode": "sparse", "query": "SOP-QA-020",
         "expect": ["sop-qa-020"]},
        {"id": "sparse_number", "mode": "sparse", "query": "250 RLU",
         "expect": ["250"]},
        {"id": "dense_paraphrase", "mode": "dense",
         "query": "which cleaning chemical is pumped through the line while it is hot",
         "expect": ["alkaline detergent", "detergent"]},
    ],
    "sop-wh-021": [
        {"id": "sparse_code", "mode": "sparse", "query": "SOP-SN-005",
         "expect": ["sop-sn-005"]},
        {"id": "dense_paraphrase", "mode": "dense",
         "query": "how cold must the freezer be kept",
         "expect": ["freezer f1", "-10"]},
        {"id": "dense_signoff", "mode": "dense",
         "query": "who gives final approval to release a shipment for delivery",
         "expect": ["cold-chain release", "warehouse qa"]},
    ],
}


def _cases():
    out = []
    for doc_id, probes in HYBRID_PROBES.items():
        for p in probes:
            out.append(pytest.param(doc_id, p, id=f"{doc_id}-{p['mode']}-{p['id']}"))
    return out


def _citation_text(cit) -> str:
    src = cit.get("source", {})
    src_text = " ".join(str(v) for v in src.values()) if isinstance(src, dict) else str(src)
    return f"{cit.get('snippet', '')} {src_text}".lower()


@pytest.fixture(scope="module")
def hybrid_indexed(request, rag_client, run_id):
    """Index one document (md) alone so a probe's success is attributable to the
    retriever, not to which document won."""
    doc_id = request.param
    doc = DOC_BY_ID[doc_id]
    rag_client.wipe_all()
    ing = rag_client.ingest(doc.path(HYBRID_FORMAT), doc.ctype(HYBRID_FORMAT),
                            f"hybrid-{doc_id}-{run_id}")
    assert ing.get("indexed"), f"failed to index {doc_id}: {ing.get('reason')}"
    yield {"client": rag_client, "doc_id": doc_id}
    rag_client.wipe_all()


@pytest.mark.parametrize("hybrid_indexed, probe", _cases(), indirect=["hybrid_indexed"])
def test_hybrid_mode_contributes(hybrid_indexed, probe, record):
    """A query only the given retrieval mode can satisfy must still retrieve its
    target chunk — proving that mode contributes to the fused result."""
    client, doc_id = hybrid_indexed["client"], hybrid_indexed["doc_id"]
    resp = client.query(probe["query"], generate=False, top_n=5)
    citations = resp.get("citations", [])
    texts = [_citation_text(c) for c in citations]
    hit = any(any(e.lower() in t for e in probe["expect"]) for t in texts)

    record("hybrid", f"{probe['mode']}:{probe['id']}", hit, fmt=doc_id,
           note=f"query={probe['query'][:40]!r} expect={probe['expect']} "
                f"cited_docs={[doc_id_for_citation(c) for c in citations]}")
    assert citations, f"{probe['id']}: no citations for a {probe['mode']} query"
    assert hit, (
        f"{probe['mode']} half did not surface its target for {probe['query']!r}; "
        f"expected one of {probe['expect']} in top-5 citations")

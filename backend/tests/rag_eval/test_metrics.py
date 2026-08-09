"""Model-agnostic retrieval metrics: recall@k and MRR against per-query ``gold``
relevant-chunk markers. Unlike the content tests, this doesn't judge the LLM at
all — it measures whether the retriever surfaces the relevant chunk, so it stays
meaningful when you swap the generation model. Runs per (document, format), over
that document's gold-labeled queries."""

import pytest

import conftest
from conftest import DOC_FORMAT_PARAMS
from queries import QUERY_SETS
from evaluate import rank_of_gold, mrr

pytestmark = pytest.mark.metrics


@pytest.mark.parametrize("indexed_doc_format", DOC_FORMAT_PARAMS, indirect=True)
def test_retrieval_recall(indexed_doc_format, record):
    client = indexed_doc_format["client"]
    fmt = indexed_doc_format["format"]
    doc_id = indexed_doc_format["doc_id"]
    cell = f"{doc_id}/{fmt}"
    gold_qs = [q for q in QUERY_SETS[doc_id] if q.get("gold")]

    ranks = []
    for q in gold_qs:
        resp = client.query(q["query"], generate=False, top_n=10)
        rank = rank_of_gold(resp, q["gold"])
        ranks.append(rank)
        conftest._METRICS.setdefault("per_query", []).append(
            {"query": q["id"], "format": cell, "rank": rank})

    n = len(ranks) or 1
    r1 = sum(1 for r in ranks if r and r <= 1) / n
    r3 = sum(1 for r in ranks if r and r <= 3) / n
    r5 = sum(1 for r in ranks if r and r <= 5) / n
    m = sum(mrr(r) for r in ranks) / n
    conftest.set_metric(f"recall@5[{cell}]", round(r5, 3))
    conftest.set_metric(f"mrr[{cell}]", round(m, 3))
    record("metrics", "retrieval_recall", r5 >= 0.6, fmt=cell,
           note=f"r@1={r1:.2f} r@3={r3:.2f} r@5={r5:.2f} mrr={m:.2f}")
    # Retrieval recall@5 is the model-agnostic floor we hold the pipeline to.
    assert r5 >= 0.6, f"{cell} recall@5={r5:.2f} < 0.6 (retriever missed relevant chunks)"

"""
Content correctness across documents and formats: mechanics, retrieval,
synthesis, negatives.

Each test is an individually selectable ``(document × format × query)`` cell,
built so only valid combinations are generated (a query runs only against its
own document). The module-scoped ``indexed_doc_format`` fixture is shared across
every query targeting the same cell, so each cell is ingested once:
    pytest -k "W3 and csv"
    pytest -k "sop-wh-021 and md"
    pytest -m retrieval
"""

import pytest

from conftest import DOC_FORMAT_PARAMS
from corpus import doc_format_pairs
from queries import QUERY_SETS
from evaluate import evaluate

KINDS = ("pdf", "docx", "text", "markdown", "csv")


def _cases(predicate):
    """One pytest.param per (doc, format, query) where the query targets that
    doc and matches ``predicate``. The fixture param is the (doc_id, fmt) pair;
    the spec rides alongside as a normal argument."""
    out = []
    for doc_id, fmt in doc_format_pairs():
        for spec in QUERY_SETS[doc_id]:
            if predicate(spec):
                out.append(pytest.param((doc_id, fmt), spec,
                                        id=f"{doc_id}-{fmt}-{spec['id']}"))
    return out


RETRIEVAL_CASES = _cases(lambda q: not q["generate"])
SYNTHESIS_CASES = _cases(lambda q: q["generate"] and not q["manual"])
NEGATIVE_CASES = _cases(lambda q: q["manual"])


@pytest.mark.mechanics
@pytest.mark.parametrize("indexed_doc_format", DOC_FORMAT_PARAMS, indirect=True)
def test_ingest_mechanics(indexed_doc_format, record):
    ing = indexed_doc_format["ingestion"]
    fmt = indexed_doc_format["format"]
    doc_id = indexed_doc_format["doc_id"]
    cell = f"{doc_id}/{fmt}"
    ok = bool(
        ing.get("stored") and ing.get("indexed")
        and ing.get("kind") in KINDS
        and ing.get("num_blocks", 0) >= 1 and ing.get("num_chunks", 0) >= 1
    )
    record("mechanics", "ingest", ok, fmt=cell,
           note=f"kind={ing.get('kind')} {ing.get('num_blocks')}b/{ing.get('num_chunks')}c "
                f"reason={ing.get('reason')}")
    assert ing.get("stored"), f"{cell}: not stored"
    assert ing.get("indexed"), f"{cell}: not indexed: {ing.get('reason')}"
    assert ing.get("kind") in KINDS, f"{cell}: unexpected kind={ing.get('kind')}"
    assert ing.get("num_blocks", 0) >= 1, f"{cell}: no blocks parsed"
    assert ing.get("num_chunks", 0) >= 1, f"{cell}: no chunks indexed"


@pytest.mark.retrieval
@pytest.mark.parametrize("indexed_doc_format, spec", RETRIEVAL_CASES,
                         indirect=["indexed_doc_format"])
def test_retrieval(indexed_doc_format, spec, record):
    client, fmt = indexed_doc_format["client"], indexed_doc_format["format"]
    cell = f"{spec['doc_id']}/{fmt}"
    resp = client.query(spec["query"], generate=False, top_n=spec.get("top_n"))
    passed, detail = evaluate(spec, resp)
    record("retrieval", spec["id"], passed, fmt=cell, note=f"missing={detail['missing']}")
    assert passed, (f"{spec['id']} [{cell}] missing={detail['missing']} "
                    f"forbidden={detail['forbidden_hits']}")


@pytest.mark.synthesis
@pytest.mark.parametrize("indexed_doc_format, spec", SYNTHESIS_CASES,
                         indirect=["indexed_doc_format"])
def test_synthesis(indexed_doc_format, spec, llm_available, record):
    if not llm_available:
        pytest.skip("LLM unavailable — start Ollama with the configured model")
    client, fmt = indexed_doc_format["client"], indexed_doc_format["format"]
    cell = f"{spec['doc_id']}/{fmt}"
    resp = client.query(spec["query"], generate=True, top_n=spec.get("top_n"))
    passed, detail = evaluate(spec, resp)
    record("synthesis", spec["id"], passed, fmt=cell,
           note=f"missing={detail['missing']} bonus_missing={detail['bonus_missing']}")
    assert not detail["forbidden_hits"], f"{spec['id']} [{cell}] stated a forbidden fact: {detail['forbidden_hits']}"
    assert passed, f"{spec['id']} [{cell}] missing required concepts={detail['missing']}"


@pytest.mark.negative
@pytest.mark.parametrize("indexed_doc_format, spec", NEGATIVE_CASES,
                         indirect=["indexed_doc_format"])
def test_negative_no_fabrication(indexed_doc_format, spec, llm_available, record):
    """The compliance-critical property: for out-of-corpus / out-of-scope
    questions the model must NOT fabricate. A forbidden (invented) fact is a hard
    fail; failing to phrase a clean refusal is a softer signal."""
    if not llm_available:
        pytest.skip("LLM unavailable")
    client, fmt = indexed_doc_format["client"], indexed_doc_format["format"]
    cell = f"{spec['doc_id']}/{fmt}"
    resp = client.query(spec["query"], generate=True, top_n=spec.get("top_n"))
    passed, detail = evaluate(spec, resp)
    record("negative", spec["id"], passed and not detail["forbidden_hits"], fmt=cell,
           note=f"forbidden={detail['forbidden_hits']} declined={not detail['missing']}")
    # Hard: never fabricate.
    assert not detail["forbidden_hits"], (
        f"{spec['id']} [{cell}] appears to fabricate: {detail['forbidden_hits']} :: {resp.get('answer')}")
    # Soft-but-asserted: a safe deferral phrasing was detected.
    assert not detail["missing"], (
        f"{spec['id']} [{cell}] did not clearly decline/defer :: {resp.get('answer')}")

"""
Content correctness across formats: mechanics, retrieval, synthesis, negatives.

Each test is parametrized over (format x query) via the module-scoped
``indexed_format`` fixture, so every cell is an individually selectable test:
    pytest -k "Q3 and csv"
    pytest -m retrieval
"""

import pytest

from queries import QUERIES
from evaluate import evaluate

KINDS = ("pdf", "docx", "text", "markdown", "csv")
RETRIEVAL = [q for q in QUERIES if not q["generate"]]
SYNTHESIS = [q for q in QUERIES if q["generate"] and not q["manual"]]
NEGATIVE = [q for q in QUERIES if q["manual"]]


@pytest.mark.mechanics
def test_ingest_mechanics(indexed_format, record):
    ing = indexed_format["ingestion"]
    fmt = indexed_format["format"]
    ok = bool(
        ing.get("stored") and ing.get("indexed")
        and ing.get("kind") in KINDS
        and ing.get("num_blocks", 0) >= 1 and ing.get("num_chunks", 0) >= 1
    )
    record("mechanics", "ingest", ok, fmt=fmt,
           note=f"kind={ing.get('kind')} {ing.get('num_blocks')}b/{ing.get('num_chunks')}c "
                f"reason={ing.get('reason')}")
    assert ing.get("stored"), "not stored"
    assert ing.get("indexed"), f"not indexed: {ing.get('reason')}"
    assert ing.get("kind") in KINDS, f"unexpected kind={ing.get('kind')}"
    assert ing.get("num_blocks", 0) >= 1, "no blocks parsed"
    assert ing.get("num_chunks", 0) >= 1, "no chunks indexed"


@pytest.mark.retrieval
@pytest.mark.parametrize("spec", RETRIEVAL, ids=[q["id"] for q in RETRIEVAL])
def test_retrieval(indexed_format, spec, record):
    client, fmt = indexed_format["client"], indexed_format["format"]
    resp = client.query(spec["query"], generate=False, top_n=spec.get("top_n"))
    passed, detail = evaluate(spec, resp)
    record("retrieval", spec["id"], passed, fmt=fmt, note=f"missing={detail['missing']}")
    assert passed, (f"{spec['id']} [{fmt}] missing={detail['missing']} "
                    f"forbidden={detail['forbidden_hits']}")


@pytest.mark.synthesis
@pytest.mark.parametrize("spec", SYNTHESIS, ids=[q["id"] for q in SYNTHESIS])
def test_synthesis(indexed_format, spec, llm_available, record):
    if not llm_available:
        pytest.skip("LLM unavailable — start Ollama with the configured model")
    client, fmt = indexed_format["client"], indexed_format["format"]
    resp = client.query(spec["query"], generate=True, top_n=spec.get("top_n"))
    passed, detail = evaluate(spec, resp)
    record("synthesis", spec["id"], passed, fmt=fmt,
           note=f"missing={detail['missing']} bonus_missing={detail['bonus_missing']}")
    assert not detail["forbidden_hits"], f"{spec['id']} [{fmt}] stated a forbidden fact: {detail['forbidden_hits']}"
    assert passed, f"{spec['id']} [{fmt}] missing required concepts={detail['missing']}"


@pytest.mark.negative
@pytest.mark.parametrize("spec", NEGATIVE, ids=[q["id"] for q in NEGATIVE])
def test_negative_no_fabrication(indexed_format, spec, llm_available, record):
    """The compliance-critical property: for out-of-corpus / out-of-scope
    questions the model must NOT fabricate. A forbidden (invented) fact is a hard
    fail; failing to phrase a clean refusal is a softer signal."""
    if not llm_available:
        pytest.skip("LLM unavailable")
    client, fmt = indexed_format["client"], indexed_format["format"]
    resp = client.query(spec["query"], generate=True, top_n=spec.get("top_n"))
    passed, detail = evaluate(spec, resp)
    record("negative", spec["id"], passed and not detail["forbidden_hits"], fmt=fmt,
           note=f"forbidden={detail['forbidden_hits']} declined={not detail['missing']}")
    # Hard: never fabricate.
    assert not detail["forbidden_hits"], (
        f"{spec['id']} [{fmt}] appears to fabricate: {detail['forbidden_hits']} :: {resp.get('answer')}")
    # Soft-but-asserted: a safe deferral phrasing was detected.
    assert not detail["missing"], (
        f"{spec['id']} [{fmt}] did not clearly decline/defer :: {resp.get('answer')}")

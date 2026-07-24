# RAG evaluation suite

Live integration tests + a human-readable matrix runner for the RAG document
pipeline. It runs against a small **corpus of documents**, each exercised in
**5 formats** (pdf, docx, md, txt, csv) end-to-end through the running API, and
is **model-swappable** — every report is tagged with the active
LLM/embedder/reranker read from `/rag/health`.

Every test is one `(document × format × query)` cell, so a failure points at an
exact document, format, and question. A dedicated **corpus-discrimination** phase
indexes *all* documents at once and checks that retrieval cites the *right*
document.

## The corpus

| id | document | domain |
|----|----------|--------|
| `sop-qa-014` | Allergen Control & Sanitation | food-safety sanitation |
| `sop-wh-021` | Cold-Chain Temperature Control (DC-2) | warehouse cold chain |

Each document carries the same **trap archetypes** — near-duplicate numbers,
table-row integrity, definition-vs-usage, revision-diff lookups, an out-of-corpus
negative, and a scope-boundary negative — so retrieval/synthesis is tested for
*generalization*, not memorization of one document. The registry lives in
`corpus.py`; each document's ground-truth query specs live in `queries.py` under
`QUERY_SETS[<doc_id>]`.

### Adding / regenerating a document
The five renderings of `sop-wh-021` are generated from **one** source model so
they can never drift apart. Regenerate them with the maintainer tool (its deps —
`reportlab`, `python-docx` — are already backend deps; the *runner* needs
nothing):
```bash
.venv-rageval/bin/pip install reportlab python-docx
.venv-rageval/bin/python backend/tests/docs/make_corpus.py
```
To add a document: model it in `make_corpus.py`, regenerate, register it in
`corpus.py`, and add its query specs + gold markers in `queries.py`.
(`sop-qa-014`'s files predate the generator and are intentionally left as-is.)

## Prerequisites
- The stack up: `docker compose --profile rag up -d`
- For synthesis tests, an LLM reachable by the backend (Ollama on the host with
  the configured model, e.g. `ollama serve` + `gemma2:2b`). Retrieval, mechanics,
  lifecycle, robustness, isolation, and metrics run **without** an LLM.
- pytest (pinned `9.1.1` in `requirements-dev.txt`) needs **Python ≥3.10**. The
  repo's main `.venv` is 3.9, so the suite has its own 3.11 venv:
  ```bash
  python3.11 -m venv .venv-rageval && .venv-rageval/bin/pip install pytest==9.1.1
  ```
  Use `.venv-rageval/bin/python` to run it (commands below).

Auth defaults to the `dev-token` bypass (`ALLOW_DEV_TOKEN`), which self-provisions
the dev org+user. Override with `--rag-token` / `--rag-email` / `--rag-password`
or `RAG_TEST_*` env.

## Two entry points

### 1. pytest — individual, selectable tests (the "parent command")
```bash
.venv-rageval/bin/python -m pytest backend/tests/rag_eval                 # everything + a model-tagged report
.venv-rageval/bin/python -m pytest backend/tests/rag_eval -m retrieval    # one category
.venv-rageval/bin/python -m pytest backend/tests/rag_eval -m "synthesis or metrics"
.venv-rageval/bin/python -m pytest backend/tests/rag_eval -m corpus          # cites the right document
.venv-rageval/bin/python -m pytest backend/tests/rag_eval -k "W3 and csv"    # one cell
.venv-rageval/bin/python -m pytest backend/tests/rag_eval -k "sop-wh-021"    # one document
```
Categories (markers): `mechanics`, `retrieval`, `synthesis`, `negative`,
`hybrid`, `corpus`, `isolation`, `lifecycle`, `robustness`, `metrics`.

Each `(document × format × query)` is its own test (id like
`sop-wh-021-csv-W3_core_check_interval`), so failures point at an exact cell.
A model-tagged report lands in `reports/pytest_<model>_<ts>.md` + `.json`.

### 2. run_rag_eval.py — the human matrix report
```bash
.venv-rageval/bin/python backend/tests/rag_eval/run_rag_eval.py                    # primary doc, per-format matrix
.venv-rageval/bin/python backend/tests/rag_eval/run_rag_eval.py --doc sop-wh-021   # a specific document
.venv-rageval/bin/python backend/tests/rag_eval/run_rag_eval.py --combined         # + all-formats-at-once phase
```
Writes the format×query matrix + per-query answers to `reports/`. `--doc` selects
which corpus document to report on (default `sop-qa-014`).

## Swapping the generation model (A/B across models)
The suite never hardcodes the model — it reads it from `/rag/health` and tags the
report. To compare models:
```bash
# 1. point the backend at a different model (compose env), then restart it
#    LLM_MODEL=<model>  (and LLM_BASE_URL if the endpoint changes)
docker compose up -d backend
ollama pull <model>          # if using Ollama and it isn't present
# 2. re-run; the report is written under the new model's name
.venv-rageval/bin/python -m pytest backend/tests/rag_eval -m "synthesis or negative or metrics"
```
`reports/pytest_<model>_*.md` files are directly comparable. The **metrics**
category (recall@k / MRR) is model-agnostic — it measures retrieval only, so it's
the stable floor to hold the pipeline to as generation models change.

## Hybrid retrieval (dense + sparse)
`test_hybrid.py` proves **both halves** of the dense+sparse fusion contribute,
black-box (the API is hybrid-only). It probes each mode with a query only that
mode can satisfy: a **bare identifier / exact number** ("SOP-QA-020", "250 RLU")
that only the **sparse/lexical** half can match, and a **zero-word-overlap
paraphrase** that only the **dense/semantic** half can bridge. If one half
silently stopped contributing — the real regression risk for exact-term
compliance lookups — its cell goes red while ordinary retrieval (satisfiable
either way) would stay green.

## Tenant isolation
`test_isolation.py` runs two scenarios with the two corpus documents:
- **Same org** (`test_same_org_sees_both_documents`) — both docs under one org;
  asserts both are retrievable, each anchored query hits the right doc, and
  deleting one leaves the other. **Always runs.**
- **Cross org** (`test_cross_org_document_isolation`) — doc A under org A, doc B
  under org B; asserts neither org can read or delete the other's document. This
  needs a genuine second org, which the stack **can't self-provision**
  (`organization_id` is FK-enforced, no create-org endpoint), so it **skips
  loudly** unless you seed one org+user and set `RAG_TEST_ORG_B_TOKEN` (or
  `RAG_TEST_ORG_B_EMAIL` / `RAG_TEST_ORG_B_PASSWORD`).

## Layout
```
corpus.py      document registry (docs × formats) — the source of truth
queries.py     per-document ground-truth query specs + gold relevant-chunk labels
client.py      stdlib API client (auth, ingest, query, health, model tag)
evaluate.py    concept/forbid grading + recall@k / MRR
report.py      model-tagged markdown/json writer
conftest.py    fixtures (per (doc,format) isolation, second-org, model tag, report hook)
test_content.py     mechanics / retrieval / synthesis / negative  (doc × format × query)
test_hybrid.py      dense+sparse fusion — each half contributes
test_corpus.py      multi-document retrieval discrimination
test_lifecycle.py   idempotent re-ingest, delete purges
test_robustness.py  empty / unsupported / non-UTF8 / corrupt / oversized(413)
test_isolation.py   tenant isolation (same-org co-tenancy + cross-org)
test_metrics.py     recall@k / MRR  (per doc × format)
run_rag_eval.py     standalone matrix report (--doc selects the document)
../docs/make_corpus.py   maintainer tool: render a doc model to all 5 formats
```

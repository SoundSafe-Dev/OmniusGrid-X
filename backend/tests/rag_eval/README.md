# RAG evaluation suite (SOP-QA-014)

Live integration tests + a human-readable matrix runner for the RAG document
pipeline. Exercises the **same source document in 5 formats** (pdf, docx, md,
txt, csv) end-to-end through the running API, and is **model-swappable** — every
report is tagged with the active LLM/embedder/reranker read from `/rag/health`.

## Prerequisites
- The stack up: `docker compose --profile rag up -d`
- For synthesis tests, an LLM reachable by the backend (Ollama on the host with
  the configured model, e.g. `ollama serve` + `gemma2:2b`). Retrieval, mechanics,
  lifecycle, robustness, isolation, and metrics run **without** an LLM.
- `pip install "pytest>=7,<9"` (host venv).

Auth defaults to the `dev-token` bypass (`ALLOW_DEV_TOKEN`), which self-provisions
the dev org+user. Override with `--rag-token` / `--rag-email` / `--rag-password`
or `RAG_TEST_*` env.

## Two entry points

### 1. pytest — individual, selectable tests (the "parent command")
```bash
python -m pytest backend/tests/rag_eval                 # everything + a model-tagged report
python -m pytest backend/tests/rag_eval -m retrieval    # one category
python -m pytest backend/tests/rag_eval -m "synthesis or metrics"
python -m pytest backend/tests/rag_eval -k "Q3 and csv" # one cell
```
Categories (markers): `mechanics`, `retrieval`, `synthesis`, `negative`,
`isolation`, `lifecycle`, `robustness`, `metrics`.

Each `(format × query)` is its own test, so failures point at an exact cell.
A model-tagged report lands in `reports/pytest_<model>_<ts>.md` + `.json`.

### 2. run_rag_eval.py — the human matrix report
```bash
python backend/tests/rag_eval/run_rag_eval.py            # per-format isolation matrix
python backend/tests/rag_eval/run_rag_eval.py --combined # + all-formats-at-once phase
```
Writes the format×query matrix + per-query answers to `reports/`.

## Swapping the generation model (A/B across models)
The suite never hardcodes the model — it reads it from `/rag/health` and tags the
report. To compare models:
```bash
# 1. point the backend at a different model (compose env), then restart it
#    LLM_MODEL=<model>  (and LLM_BASE_URL if the endpoint changes)
docker compose up -d backend
ollama pull <model>          # if using Ollama and it isn't present
# 2. re-run; the report is written under the new model's name
python -m pytest backend/tests/rag_eval -m "synthesis or negative or metrics"
```
`reports/pytest_<model>_*.md` files are directly comparable. The **metrics**
category (recall@k / MRR) is model-agnostic — it measures retrieval only, so it's
the stable floor to hold the pipeline to as generation models change.

## Tenant isolation
`test_isolation.py` needs a **second org**. The dev-token bypass maps to one
fixed org, so the fixture tries to provision a second org+user; if the
environment can't, those tests **skip loudly** (not a silent pass). Seed a second
org+user to enable them.

## Layout
```
queries.py     ground-truth query specs + gold relevant-chunk labels
client.py      stdlib API client (auth, ingest, query, health, model tag)
evaluate.py    concept/forbid grading + recall@k / MRR
report.py      model-tagged markdown/json writer
conftest.py    fixtures (per-format isolation, second-org, model tag, report hook)
test_content.py     mechanics / retrieval / synthesis / negative
test_lifecycle.py   idempotent re-ingest, delete purges
test_robustness.py  empty / unsupported / non-UTF8 / corrupt / oversized(413)
test_isolation.py   tenant isolation
test_metrics.py     recall@k / MRR
run_rag_eval.py     standalone matrix report
```

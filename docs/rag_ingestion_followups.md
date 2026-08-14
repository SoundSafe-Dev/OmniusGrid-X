# RAG ingestion — deferred durability / scaling follow-ups

The structure-aware chunking pass (markdown/CSV block splitting, table-row
blocks, per-doc chunk cap, upload-size cap) landed on
`feature/RAG-Compliance-Doc-Pipeline`. These items were **consciously deferred**
from that change because they are architecture/ops level. Captured here so they
aren't lost.

> **All items are now resolved** — see below. What is *not* done is running any
> of it against live infrastructure: every fix here is covered by unit/API tests
> only. `docs/rag_async_ingestion_next_steps.md` holds the verification plan.

## Open

None. The residual work is verification, not design.

---

### Resolved: inline ingestion in the HTTP request (was #1)
`POST /rag/ingest` no longer parses/embeds inside the request, so a large
document can't outlive the ingress read timeout. It stores the blob, writes a
`rag_documents` row and returns `202 {status: "queued"}`; the `rag-indexing`
worker claims the row (`FOR UPDATE SKIP LOCKED`) and indexes it, and callers
poll `GET /rag/documents/{doc_id}/status` for the outcome. Design and rationale
— including why the row is the queue rather than a Redpanda topic — are in
`docs/superpowers/specs/2026-07-30-rag-async-ingestion-design.md`.

### Resolved: `delete_by_doc` → re-upsert not atomic (was #3, partial-index window)
Re-ingest used to delete a document's existing vectors, then re-embed/upsert
batch by batch — a failure mid-way (embed timeout, Qdrant blip) left the doc
partially indexed while `indexed` never flipped true. The retry half landed
first with async ingestion (`rag_documents.status` + worker requeue up to
`RAG_INDEX_MAX_ATTEMPTS`), and the remaining atomicity gap is now closed too:
`index_document` tags each pass with a fresh `generation`, upserts the new
generation in full, then calls `vector_store.delete_by_doc_excluding_generation`
to drop the old one (which also sweeps up any orphan left by a prior failed
run). A mid-loop failure now leaves the previous generation's vectors fully
intact and queryable instead of landing in a partial state, at the cost of a
brief duplicate-hit window between the new generation landing and the old one
being swept — strictly preferable to missing content.

### Resolved: whole file read into memory (was #1)
`POST /rag/ingest` no longer calls `file.read()`. Starlette has already spooled
the multipart body to a temp file by the time the handler runs, so the size is
now a `seek`/`tell` (`document_store.stream_size`) and the spooled file object
is handed to `put_document_stream` → `upload_fileobj`, which uploads in bounded
parts. Peak memory is one part rather than the whole document.
`UploadLimitMiddleware` additionally rejects on `Content-Length` before routing,
which is the only place a size check can run *before* the body is buffered — a
check inside the handler is necessarily too late, because FastAPI parses the
multipart body to resolve the `UploadFile` parameter in the first place.

Not covered: the **worker** still reads the whole blob back
(`get_document` → bytes) and pdfplumber/python-docx expand it further. That is
bounded by `RAG_MAX_UPLOAD_BYTES` and one document at a time per worker pass,
so it is a sizing question rather than an unbounded risk — but streaming
parsers would be the next step if worker memory ever becomes the constraint.

### Resolved: rag-inference shared by ingest and query (was #2)
`RAG_INFERENCE_INGEST_URL` gives batch ingest its own inference endpoint;
`get_ingest_inference()` returns the shared client when it is empty, so the
default single-box topology is unchanged. The async pass had already moved
ingest embedding onto its own process, so this is now a one-env-var deployment
choice rather than a code change. The compose file plumbs the variable through;
no second `rag-inference` replica is *defined* there yet — that is a deployment
decision (~5 GB of weights per replica), not a missing capability.

### Resolved: no per-tenant ingest quota (was #3)
`RAG_MAX_DOCUMENTS_PER_ORG`, `RAG_MAX_TOTAL_BYTES_PER_ORG` and
`RAG_INGEST_RATE_LIMIT_PER_MINUTE` are enforced in the ingest route before the
blob is stored, so a rejected upload costs no object storage: 429 for the rate
limit (retrying works), 409 for the quotas (retrying does not). Usage is
measured directly from `rag_documents` — exact per org, restart-safe, no second
store to keep consistent — which needed a new `size_bytes` column
(migration 044). Re-ingesting an existing `doc_id` is charged as a delta, not a
new document, so an org at its cap can still correct a document. Current usage
is surfaced in the `quota` block of `GET /rag/documents`.

### Already handled in the structure-aware pass (for reference)
- `RAG_MAX_UPLOAD_BYTES` — consistent 413 in app (local + prod), mirrors ingress.
- `RAG_MAX_CHUNKS_PER_DOC` — truncate + flag so one doc can't explode embeddings.
- Structure-aware markdown/CSV block splitting + per-row table blocks (kept the
  chunker pure; structure lives in the block builders).
- Graceful fallbacks: no-heading markdown, non-tabular/unparseable CSV, and
  non-UTF8 all fall back to plain-text chunking rather than failing.

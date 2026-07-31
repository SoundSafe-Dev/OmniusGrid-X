# RAG ingestion — deferred durability / scaling follow-ups

The structure-aware chunking pass (markdown/CSV block splitting, table-row
blocks, per-doc chunk cap, upload-size cap) landed on
`feature/RAG-Compliance-Doc-Pipeline`. These items were **consciously deferred**
from that change because they are architecture/ops level. Captured here so they
aren't lost. Ordered by impact.

## 1. Ingestion is inline in the HTTP request (large-doc blocker)

`POST /api/v1/rag/ingest` parses → chunks → embeds (32/req, up to
`RAG_INFERENCE_TIMEOUT=60s` each) → upserts, all **inside the request**. A large
document produces hundreds/thousands of chunks and many sequential embed calls,
so the request can run for minutes and **exceed the nginx
`proxy-read-timeout`/client timeout** (the ingress caps body at 50 MiB but not
duration). The blob is stored, but the caller sees a 504 and can't tell whether
indexing finished.

**Fix:** make ingestion asynchronous. Store the blob synchronously, enqueue an
`index_document` job (Redpanda + the existing `ingestion-worker`), return `202`
with a `doc_id` + status. Add `GET /rag/documents/{doc_id}/status`
(pending / indexing / indexed / failed, chunk counts). The worker already exists;
this is mostly wiring + a status field on the document record.

## 2. Whole file read into memory + parser expansion (OOM risk)

`content = await file.read()` loads the entire upload into memory, then
pdfplumber/python-docx expand it further. Concurrent large uploads can OOM the
backend container. The new `RAG_MAX_UPLOAD_BYTES` (50 MiB) caps the worst case,
but the check happens **after** the full read.

**Fix:** stream to the object store and enforce the size cap from the
`Content-Length` header before buffering; parse from a temp file / stream where
the parser supports it.

## 3. rag-inference is shared by ingest AND live queries (uptime coupling)

The same `rag-inference` service serves ingest embeddings *and* live query
embeddings + reranking. A heavy ingest pegs CPU and **degrades query latency**
for everyone — an availability coupling, not just slowness.

**Fix (any of):** a bounded ingest concurrency / worker pool separate from the
query path; a priority lane for query embeddings; or a dedicated
inference replica for batch ingest. Pairs naturally with async ingestion (#1).

## 4. `delete_by_doc` → re-upsert is not atomic (partial-index window)

Re-ingest deletes the doc's existing vectors, then re-embeds/upserts batch by
batch. A failure mid-way (embed timeout, Qdrant blip) leaves the doc **partially
indexed** while the blob is stored and `indexed` never flips true. Re-running
fixes it (idempotent), but there is a silent inconsistent window.

**Fix:** write the new generation under a version tag, then delete the old
generation once all batches succeed (swap, don't delete-then-write); or record a
per-doc `index_status` so a partial index is visible and auto-retried by the
worker (#1).

## 5. No per-tenant ingest quota / rate limit (DoS surface)

Nothing bounds how many/large documents an org can push. Combined with #3, a
single tenant can saturate embedding CPU and degrade everyone's queries.

**Fix:** per-org ingest rate limit + a max-documents / max-total-bytes quota,
enforced at the API and surfaced in the status endpoint.

## 6. No document metadata record, so document *type* cannot be known

Everything about a document lives in the Qdrant point payload and the S3 object
metadata. There is no row anywhere saying "this is a form", "this is a policy",
"this is an SOP" — the classification a reader most wants to act on.

This surfaced building the Compliance Assistant. Its **Forms you may need** panel
has to decide whether a source document is something you *fill in and return* or
something you *read*, and with no metadata to consult it does so with a filename
regex (`_FORM_PATTERN` in `rag_retriever.py`). That is guesswork: it reads
`fmla-request-form.pdf` correctly and would read a badly-named form not at all.

**Fix:** the document record from #1 is the natural home. A `doc_type`
(`policy | sop | form | standard | agreement`) set at ingest — declared by the
uploader, defaulted by the current heuristic — replaces the regex with a fact.
`SourceDoc.is_form` then reads one field, and the panel can grow the other types
for free.

---

### Already handled in the structure-aware pass (for reference)
- `RAG_MAX_UPLOAD_BYTES` — consistent 413 in app (local + prod), mirrors ingress.
- `RAG_MAX_CHUNKS_PER_DOC` — truncate + flag so one doc can't explode embeddings.
- Structure-aware markdown/CSV block splitting + per-row table blocks (kept the
  chunker pure; structure lives in the block builders).
- Graceful fallbacks: no-heading markdown, non-tabular/unparseable CSV, and
  non-UTF8 all fall back to plain-text chunking rather than failing.

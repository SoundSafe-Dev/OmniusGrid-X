# RAG ingestion — deferred durability / scaling follow-ups

The structure-aware chunking pass (markdown/CSV block splitting, table-row
blocks, per-doc chunk cap, upload-size cap) landed on
`feature/RAG-Compliance-Doc-Pipeline`. These items were **consciously deferred**
from that change because they are architecture/ops level. Captured here so they
aren't lost. Ordered by impact.

## 1. Whole file read into memory + parser expansion (OOM risk)

`content = await file.read()` loads the entire upload into memory, then
pdfplumber/python-docx expand it further. Concurrent large uploads can OOM the
backend container. The new `RAG_MAX_UPLOAD_BYTES` (50 MiB) caps the worst case,
but the check happens **after** the full read.

**Fix:** stream to the object store and enforce the size cap from the
`Content-Length` header before buffering; parse from a temp file / stream where
the parser supports it.

## 2. rag-inference is shared by ingest AND live queries (uptime coupling)

The same `rag-inference` service serves ingest embeddings *and* live query
embeddings + reranking. A heavy ingest pegs CPU and **degrades query latency**
for everyone — an availability coupling, not just slowness.

**Fix (any of):** a bounded ingest concurrency / worker pool separate from the
query path; a priority lane for query embeddings; or a dedicated
inference replica for batch ingest. The async pass moved ingest embedding onto
its own worker, so the ingest side is now separable without touching the API.

## 3. `delete_by_doc` → re-upsert is not atomic (partial-index window)

Re-ingest deletes the doc's existing vectors, then re-embeds/upserts batch by
batch. A failure mid-way (embed timeout, Qdrant blip) leaves the doc **partially
indexed** while the blob is stored and `indexed` never flips true. Re-running
fixes it (idempotent), but there is a silent inconsistent window.

The retry half of this landed with async ingestion: `rag_documents.status`
makes a partial index visible, and the worker requeues the document until
`RAG_INDEX_MAX_ATTEMPTS`. The inconsistent window itself is still there — a
document sits partially indexed and queryable until a retry finishes it.

**Fix:** write the new generation under a version tag, then delete the old
generation once all batches succeed (swap, don't delete-then-write).

## 4. No per-tenant ingest quota / rate limit (DoS surface)

Nothing bounds how many/large documents an org can push. Combined with #2, a
single tenant can saturate embedding CPU and degrade everyone's queries.

**Fix:** per-org ingest rate limit + a max-documents / max-total-bytes quota,
enforced at the API and surfaced in the status endpoint.

---

### Resolved: inline ingestion in the HTTP request (was #1)
`POST /rag/ingest` no longer parses/embeds inside the request, so a large
document can't outlive the ingress read timeout. It stores the blob, writes a
`rag_documents` row and returns `202 {status: "queued"}`; the `rag-indexing`
worker claims the row (`FOR UPDATE SKIP LOCKED`) and indexes it, and callers
poll `GET /rag/documents/{doc_id}/status` for the outcome. Design and rationale
— including why the row is the queue rather than a Redpanda topic — are in
`docs/superpowers/specs/2026-07-30-rag-async-ingestion-design.md`.

### Already handled in the structure-aware pass (for reference)
- `RAG_MAX_UPLOAD_BYTES` — consistent 413 in app (local + prod), mirrors ingress.
- `RAG_MAX_CHUNKS_PER_DOC` — truncate + flag so one doc can't explode embeddings.
- Structure-aware markdown/CSV block splitting + per-row table blocks (kept the
  chunker pure; structure lives in the block builders).
- Graceful fallbacks: no-heading markdown, non-tabular/unparseable CSV, and
  non-UTF8 all fall back to plain-text chunking rather than failing.

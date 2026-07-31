# Compliance Assistant

Grounded Q&A over the organization's policy corpus — SOPs, OSHA standards,
collective agreements, corporate policy. Sidebar tab → `/compliance`.

It is the first consumer of the RAG pipeline
(`feature/RAG-Compliance-Doc-Pipeline`, Hudson Treinen): SeaweedFS blobs →
BGE-M3 dense+sparse embeddings → Qdrant hybrid search with server-side RRF →
BGE-reranker cross-encoder → an OpenAI-compatible generator. That pipeline is
unchanged by this feature; what follows is what was added around it.

**It is not a Correlation AI session.** No message history, no data-source
attach, no upload. Documents enter the corpus through the Correlation AI intake
flow; this page reads the corpus. One question, one grounded answer, its sources.

---

## Two retrieval legs

| | Documents | Operational records |
|---|---|---|
| Store | Qdrant + SeaweedFS | Postgres (`erp_entities`) |
| Read at | query time (hybrid search + rerank) | query time (recency window + keyword ranking) |
| In the prompt | numbered `[1]`, `[2]`, … | unnumbered, under `Operational records:` |
| In the response | `citations` + `sources` | **nothing** |
| Cited | yes | never |

The document leg answers *what the policy says*. The ERP leg tells the generator
*what is currently true*, so the answer can be specific — "the agreement requires
X; three of your open work orders show Y" — rather than a paraphrase of the
policy the reader could have found themselves.

### Why ERP is not a second corpus

The obvious alternative is to push `ERPEntity` rows through `rag_ingestion` into
Qdrant. It was rejected, and the reasons are worth keeping because the idea will
come back:

- **The blobs would not exist.** SeaweedFS keys are `{org_id}/{doc_id}/{filename}`
  and citations presume a real file. A citation you cannot open is worse than no
  citation.
- **Every ERP sync would need a re-index.** `run_erp_sync` writes raw vendor
  records continuously; the vector copy would be stale by construction.
- **ERP chunks would compete for the rerank slots.** `RAG_RERANK_TOP_N` is 5, and
  those five belong to policy text.
- **The citations would then have to be filtered back out**, which is a
  post-hoc correction of a problem that a separate leg does not create.

Both legs are scoped by the same key from the same JWT — `org_id` in the Qdrant
filter, `organization_id` plus Postgres RLS on `erp_entities` — so they are
tenant-consistent by construction rather than by coordination.

### The ERP leg's selection, briefly

`app/services/rag_erp_context.py`:

1. Read the most recent `RAG_ERP_CANDIDATE_ROWS` (300) active rows for the org.
2. **Rank, don't filter.** A routed entity type or a query-token hit promotes a
   row; nothing is excluded outright. Recency already carries real signal, and an
   over-eager relevance filter empties the block on any question the keywords
   miss — which fails silently, in the direction that looks fine.
3. Render each row as `EntityType | entity_id | key: value | …`, the same shape
   `rag_ingestion._table_rows_to_blocks` produces for table rows, so the
   generator reads a format the corpus already trained it on.
4. Cap at `RAG_ERP_CONTEXT_ROWS` (40) / `RAG_ERP_CONTEXT_CHARS` (3000), never
   truncating mid-row.

Filtering happens in Python, not SQL: `entity_data` is `JSON`, not `JSONB`, so an
ILIKE needs a dialect-specific cast and the SQLite dev path would then match
differently from Postgres. `platform_correlation.erp_provider` reads the same
table the same way, and `flatten_erp_entity` is shared with it rather than
duplicated.

---

## The operational block is not in the response

By design: the answer reads as one grounded response, not as two data sources
stitched together. `RagAnswer` carries `answer`, `citations`, `used_context`,
`generated`, `sources` — and nothing else. A test pins that field list
(`test_the_response_model_carries_no_operational_field`) precisely so a later
"just for debugging" field cannot quietly publish the block.

**The audit trail is the log line.** `rag_retriever.answered` carries
`erp_rows`, `erp_entity_types`, `erp_chars`. That is the only record that
operational data shaped a given answer. If an answer is ever challenged — and for
a compliance tool, one eventually will be — this is what explains it. Do not drop
those fields to tidy the log.

Set `RAG_ERP_CONTEXT_ENABLED=false` to disable the leg entirely. Asking the same
question with it on and off is also the fastest way to see whether the routing
keywords are earning their place.

---

## Document links

`POST /api/v1/rag/documents/link` — `{s3_key}` → `{url, expires_in}`.

`DocumentStore.generate_presigned_url` already existed and was unreachable over
HTTP; this exposes it, because a citation is only useful if the reader can open
the document behind it.

Two things about it are deliberate:

- **POST, not GET.** The key travels in a body rather than in a URL that lands in
  every access log and proxy trace between the browser and the backend. The key
  is not a secret, but "this person opened the disciplinary policy" should not
  leak into log aggregation as a side effect.
- **The `{org_id}/` prefix check is load-bearing.** The key arrives from the
  client. Without it, any authenticated user presigns any tenant's document by
  editing one UUID — a direct IDOR that hands back a URL which keeps working for
  an hour after the check would have failed. `..` is rejected rather than
  normalized: a key needing normalization is not one this API produced.

---

## Verification

Hermetic, no stack:

```bash
cd backend && venv/bin/python -m pytest tests/test_rag_erp_context.py -q
cd frontend && npx vitest run src/pages/compliance src/api/rag.realmode.test.ts
```

Against live services (`docker compose --profile rag up -d qdrant seaweedfs`):
the presign path was verified end to end — store a document, presign it through
the handler, fetch the URL, confirm the bytes match, confirm a cross-org key and
a traversing key are both refused with 403 and logged.

The ERP leg was verified against a real Postgres: tenant isolation in both
directions, `is_active` filtering, and routing reordering the *same* corpus by
question (WorkOrder first for a lockout question, Employee first for a
certification question).

**Not yet verified end to end:** the full query path through embeddings,
reranking, and generation. `rag-inference` builds locally and pulls ~5 GB of
weights, and the Docker VM had 2.7 GB free. Standing that up is the remaining
gap — run the A/B with `RAG_ERP_CONTEXT_ENABLED` on and off when you do.

---

## Files

| Path | Role |
|---|---|
| `backend/app/services/rag_erp_context.py` | the operational leg |
| `backend/app/services/rag_retriever.py` | prompt assembly, `SourceDoc` roll-up, audit log |
| `backend/app/api/rag.py` | `/query` wiring, `/documents/link` |
| `backend/tests/test_rag_erp_context.py` | tenancy, routing, concealment, degradation |
| `frontend/src/api/rag.ts` | typed client |
| `frontend/src/pages/compliance/ComplianceAssistant.tsx` | the page |

# RAG greenlight — FS-665 re-scope and current state

**FS-665** asks that every RAG item be verified against the current tree before
work starts, to avoid redundant effort and orphaned debt. This file is that
verification, plus the two workstreams that sit alongside it.

Verified **2026-08-14** against branch `rag-async-ingest` (tip `a8941edd`) and a
live run on Thunder instance 0 (`nomb0b28`, A6000). Every claim below is backed
by something observed in the tree or in a run; unverified things say so.

## FS-665 verdict

| Ticket | Ticket's premise | Actual state | Action |
|---|---|---|---|
| **FS-666** streaming answers | `stream_generate()` exists, no route | **Accurate** | Still to do |
| **FS-667** async ingest (202 + status) | Request blocked on large uploads | **Already landed** | Close — verify on merge |
| **FS-668** document metadata record | Hard blocker for the other three | **Already landed** | Close — no longer blocking |
| **FS-669** delete lacks org filter | Deletion missing org scoping | **Accurate, and wider than stated** | Do first — see below |

Two of four are already done, so the dependency chain the tasking assumed no
longer holds: FS-668 was named a hard blocker for the rest, and it is complete,
which unblocks FS-666 and FS-669 immediately.

### FS-666 — streaming answers · still valid

`stream_generate()` is at `backend/app/services/llm_client.py:130`. Nothing in
`backend/app/api/` exposes it: the only `StreamingResponse` in the API layer is
in `exports.py:726`, unrelated. The ticket is accurate as written.

### FS-667 — async ingestion · done

Landed on `rag-async-ingest`. `POST /rag/ingest` returns **202** with a status
endpoint; `rag_documents` is the durable queue, drained by the `rag_indexing`
worker using `FOR UPDATE SKIP LOCKED`. The blocking request-response cycle the
ticket describes no longer exists.

Verified: `scripts/verify_rag_e2e.py` **passes in 47 s** against real
Qdrant + SeaweedFS + Postgres + BGE-M3.

Caveat: this is true on the branch, not on `main` — see workstream A.

### FS-668 — document metadata record · done

`rag_documents` (migration 043) plus `size_bytes` (migration 044). All 47
migrations apply clean on real Postgres. The row carries `doc_id`, `org_id`,
`filename`, `s3_key`, `kind`, `size_bytes`, `status`, `attempts`, chunk counts,
and timestamps — and doubles as the ingestion queue.

### FS-669 — delete lacks org filter · confirmed, and worse than stated

The ticket says the deletion handler lacks organizational filters for vector
deletion. Confirmed, and the blast radius is larger than the ticket implies.

The route is *not* the problem. `api/rag.py:209` validates the path segment and
passes `org_id` through. Inside `IngestionPipeline.delete_document`, two of the
three deletions are correctly scoped:

```python
await self.vectors.delete_by_doc(doc_id)          # ← no org_id
prefix = f"{org_id}/{doc_id}/"                    # blobs: org-scoped
row_deleted = await delete_row(org_id, doc_id)    # row:   org-scoped
```

`VectorStore.delete_by_doc` (`vector_store.py:183`) filters on `doc_id` alone.
The points **do** carry `org_id` in their payload, and there is a payload index
on it created specifically for tenant isolation — the read path uses it
correctly (`vector_store.py:148`, `rag_retriever.py:121`). Only the delete paths
omit it.

Because `doc_id` is caller-suppliable at ingest, org A can choose a `doc_id`
that collides with org B's and delete **org B's vectors**. A's own row and blobs
are removed correctly, B's are untouched — so B is left with rows reading
`indexed` and no vectors behind them. Silent cross-tenant data loss, no error
raised on either side.

**Second instance, introduced 2026-08-14 in commit `76c72cbc`:**
`delete_by_doc_excluding_generation(doc_id, generation)` has the identical gap.
It is reached on every **re-ingest**, not just delete — org A re-ingesting a
colliding `doc_id` wipes org B's vectors for it. That is a far more routine
operation than deletion, so this instance is the more likely one to fire.

Fix: thread `org_id` into both signatures and add it to the `must` clause. Both
call sites already have it in scope. The regression test belongs next to
`rag_eval/test_isolation.py`.

---

## Workstream A — land it on `main`, then k8s

**Not done.** `rag-async-ingest` is 643 commits behind `main`. A direct merge
conflicts in **457 files**, mostly `add/add` artifacts of repeated history
rewrites rather than real disagreements. Replaying the 22 commits onto current
`origin/main` instead puts **50 files** in play, of which `main` has also
touched **18** — the tractable route.

Five of those 18 are k8s base manifests `main` changed independently:
`backend-deployment`, `ingress`, `kustomization`, `redpanda-statefulset`,
`timescaledb-statefulset`. That is where the merge needs judgement rather than
mechanical conflict resolution.

**The k8s manifests have never been applied.** A Thunder instance cannot build
images, so nothing so far validates the Dockerfiles, the compose service wiring,
or the manifests. Relative to "wire RAG into k8s", this is the largest gap —
and it is not closeable on this hardware.

**Risk.** The remote is force-rewritten repeatedly; every branch including
`main` took a forced update during a single session. Re-fetch and re-verify
ancestry immediately before integrating. Do not push to
`feature/RAG-Compliance-Doc-Pipeline` — a stale pre-rewrite branch, 853 commits
behind `main`, whose only unique commit is a July notice to move off it.

---

## Workstream B — CI pipeline

Three workflows, identical on `main` and the branch:

| Workflow | Trigger | Services |
|---|---|---|
| `ci-cd.yml` | push/PR to `main`, tags | postgres, redpanda |
| `quality-gates.yml` | push/PR to `main` | postgres, redis |
| `nightly-e2e.yml` | schedule + dispatch | compose: timescaledb, redpanda, redis |

**No workflow has a Qdrant, SeaweedFS, or rag-inference service**, so RAG
integration coverage is zero. `nightly-e2e.yml` does not mention RAG at all,
and `ci-cd.yml`'s broad `pytest --cov=app` reaches the RAG tests without their
dependencies, so they fail or skip rather than gate. `verify_rag_e2e.py` — the
one piece of real infrastructure proof — runs nowhere automatically.

Secondary: `backend/tests/conftest.py:198` hard-codes `PostgresContainer` with
no environment escape hatch, so the fixture cannot target an already-running
Postgres. This is what makes 31 tests unrunnable on Thunder, and it makes the
suite brittle anywhere docker-in-docker is unavailable.

Proposed order:

1. `TEST_DATABASE_URL` escape hatch on the `pg_container` fixture, falling back
   to testcontainers when unset. Unblocks 31 tests and decouples CI from
   docker-in-docker. `test_backup_restore_drill.py` consumes the container
   object itself and must skip when there is none.
2. Qdrant + SeaweedFS service containers in a RAG job; run the RAG unit and
   queue tests there.
3. Decide where rag-inference runs. Weights are ~5 GB, ~36 s to load on the
   A6000 but minutes on CPU — likely `nightly-e2e.yml` with a cache, not
   every PR.
4. Gate 043/044 through the real migration runner, as `nightly-e2e.yml` already
   does for the core schema.

---

## Workstream C — full suite + performance metrics

### Results — 2026-08-14, instance 0

| Stage | Result | Elapsed |
|---|---|---|
| `verify_rag_e2e.py` | **PASS** | 47 s |
| RAG unit tests | 25 passed, **20 errors** | 20 s |
| `test_rag_ingest_quota.py` | 0 run, **11 errors** | 4 s |
| `backend/tests/rag_eval/` (127 tests) | in flight | — |

### The 31 errors are one infrastructure fault, not code

```
ConnectionError: Port mapping for container ... and port 8080 is not available
```

Testcontainers publishes ports, which needs bridge networking; this box has only
`host` and `none`. Same Thunder sandbox limitation as the `/dev/fd` entrypoint
problem, in a new place. **No genuine test failure has been observed.**
Affected: `test_rag_index_queue.py`, `test_rag_ingest_async_api.py`,
`test_rag_documents_migration.py`, `test_rag_ingest_quota.py`. Fixed by item 1
of workstream B.

### Performance metrics — not yet measured

No numbers exist yet. `verify_rag_e2e.py` proves correctness, not throughput, so
this needs a driver script. What the greenlight needs:

- **Ingest throughput** — documents/min and MB/min end to end, plus the
  queued→indexed latency the worker actually achieves.
- **Query latency** — p50/p95 for embed, Qdrant search, and rerank separately.
  Rerank is the likeliest tail-latency source.
- **Worker drain rate** under backlog, and behaviour at >1 replica — the reason
  `FOR UPDATE SKIP LOCKED` is there, and what `test_isolation.py` covers.
- **Quota-check overhead** — one aggregate query per upload, on the request
  path, currently unmeasured.
- **GPU vs CPU embedding** — compose budgets a 600 s CPU start period against
  ~36 s on the A6000. Determines what CI can afford.

---

## Recommended order

1. **FS-669 first.** It is a live cross-tenant data-loss path, the fix is small,
   and the re-ingest instance fires on a routine operation.
2. **Escape hatch** (workstream B item 1) — unblocks 31 tests, needed before any
   run can be called complete.
3. **Perf driver + full green run** on instance 0 while it is warm.
4. **FS-666** streaming route.
5. **Replay onto `main`**, with attention to the five k8s manifests.
6. **CI RAG job**, once the suite runs without docker-in-docker.

FS-667 and FS-668 need no work beyond confirming they survive the merge.

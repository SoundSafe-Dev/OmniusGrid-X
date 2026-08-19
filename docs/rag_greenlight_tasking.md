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

## Workstream B — CI pipeline · closed 2026-08-19

**Done.** `.github/workflows/nightly-e2e.yml` gained a `rag-eval-nightly` job:
`./scripts/rag.sh up` (builds + boots qdrant/seaweedfs/rag-inference/backend/
rag-indexing-worker via compose, which pulls in `migrate`/timescaledb/redpanda/
redis as transitive dependencies), then `scripts/verify_rag_e2e.py` and
`pytest backend/tests/rag_eval` for real. `synthesis`/`negative` self-skip
without a live LLM (no Ollama in CI) via their own `llm_available` fixture
check, matching the earlier decision to scrap a hard synthesis gate (small-CPU-
model failures there are a real capability ceiling, not a regression — see
memory). Everything else in the suite (mechanics/retrieval/hybrid/isolation/
lifecycle/metrics/corpus/robustness) runs and gates for real, where before it
silently skipped every single run because no workflow ever started a live
stack — `rag_client`'s fixture skips (not fails) when the stack is unreachable,
by design, so this coverage gap produced no red anywhere.

Re-verified rather than assumed: `backend/tests/test_rag_*.py` (unit/queue
tests) turned out to need only a real Postgres — they fake out
`document_store`/`vector_store` entirely (`test_rag_vector_delete_scoping.py`'s
own docstring: "assert on the filter handed to the client rather than on a
live Qdrant, so they stay fast and run anywhere"). `qdrant-client` and
`testcontainers` are both already installed in `ci-cd.yml`'s `lint-and-test`
job and none of these tests are in its ignore list, so — contrary to this
doc's original claim that they "fail or skip rather than gate" — they were
very likely already running and gating there; the real, confirmed-zero
coverage was specifically the live-stack `rag_eval` suite. Left untouched:
no new job was added for the unit/queue tests, since one already covers them.

Migrations 043/044 needed no separate gating: `scripts/migrate.py` is a
generic runner over every file in `database/migrations/`, already invoked by
the compose `migrate` service that `rag-eval-nightly` inherits — confirmed by
reading the runner, not assumed.

**Update, same day:** `rag-inference` has since been added to `ci-cd.yml`'s
`build-images` matrix (alongside `backend`/`frontend`/`edge-agent`), so there
is now a built image for any future k8s deploy step to reference. Also added:
a `rag-unit` job in `quality-gates.yml` running the 11 `backend/tests/test_rag_*.py`
files against `postgres` + `qdrant` services (via the `TEST_DATABASE_URL`
escape hatch). This is **not redundant** with `ci-cd.yml`'s `lint-and-test` —
that workflow only triggers on push/PR to `main`, so a feature branch with no
open PR got zero RAG-unit coverage until now; `quality-gates.yml` triggers on
`feature/**` pushes directly. No Docker layer / model-weight caching was added
for `rag-eval-nightly`, so each nightly run pays the ~5GB BGE weight download
fresh; flagged as a known cost, not solved (weights live in a named Docker
volume, not a bind mount, so `actions/cache` can't target them directly
without a fragile tar/docker-cp round trip — needs either a bind mount or
baking the weights into the image at build time).

Three workflows previously, identical on `main` and the branch (now four, with
`rag-eval-nightly` added to `nightly-e2e.yml`):

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
   and the re-ingest instance fires on a routine operation. **Done.**
2. **Escape hatch** (workstream B item 1) — unblocks 31 tests, needed before any
   run can be called complete. **Done.**
3. **Perf driver + full green run** on instance 0 while it is warm. **Done**
   (driver + ablation knobs landed; numbers are point-in-time, not frozen here).
4. **FS-666** streaming route. **Done, 2026-08-19** (`POST /query/stream`,
   SSE citations→delta*→done, commit `d8bf6ede`).
5. **Replay onto `main`**, with attention to the five k8s manifests. **Not
   done — scoped, not executed.** See the corrected note above the k8s table:
   the raw divergence (644 commits main-only / 101 HEAD-only, 978-file diff)
   overstates the real work. Only ~34–40 commits under this branch's 101 are
   RAG-specific; the rest duplicate tickets main already re-implemented
   independently. The actual RAG-scoped diff is 32 files, +5,108/−1,912. One
   real conflict: this branch's migrations `043_rag_documents.sql` /
   `044_rag_document_size_bytes.sql` collide with main's own (different)
   `043`/`044` — needs renumbering to `068`/`069` (main's highest is `067`).
   The 5 k8s manifests are additive on both sides (different fields), not a
   logic conflict — mechanical merge. Recommended mechanism: cherry-pick the
   RAG-tagged commits onto a fresh branch off current `origin/main`, not a
   merge/rebase of the whole branch.
6. **CI RAG job**, once the suite runs without docker-in-docker. **Done,
   2026-08-19** — `rag-unit` (per-PR, `quality-gates.yml`) + `rag-eval-nightly`
   (`nightly-e2e.yml`) + `rag-inference` in the build matrix.

FS-667 and FS-668 need no work beyond confirming they survive the merge.

Remaining before "wire k8s": re-verify `verify_rag_e2e.py` against a cluster
that includes the `rag-indexing-worker` (the existing kind-cluster validation
predates async ingestion and doesn't exercise it), fix the mTLS env-var
mismatch, decide the `omniusgrid-rag` namespace-topology question, and wire
`QDRANT_API_KEY`/`RAG_INFERENCE_API_KEY` + NetworkPolicy scoping. See
`docs/RAG_DEVELOPMENT.md` §8.

---

## Update — 2026-08-14, retrieval ablation knobs + first perf run

Picking up at "Recommended order" step 3. FS-669 was independently re-verified
against this branch's own tip (it was already fixed here) and confirmed still
fixed. Two things landed since:

### 1. `scripts/rag_perf.py` — run for the first time

Previously present but never executed against live services (see workstream
C). Now has a real run behind it on instance 0's stack (Qdrant + SeaweedFS +
Postgres + BGE-M3, GPU). Ingest, queued→indexed latency, query latency, and
worker-drain-under-backlog all measured; quota-check overhead recorded as a
best-effort proxy per the driver's own caveat. Numbers are not reproduced
here — they're a point-in-time snapshot, not a fixed target, and belong next
to whatever run they're being compared against, not frozen into this doc.

### 2. Retrieval ablation knobs (`RAG_SEARCH_MODE`, `RAG_RERANK_ENABLED`)

Ported from a parallel branch (`feature/RAG-Compliance-Doc-Pipeline`, which
built these independently) onto this branch:

- `app/core/config.py` — `RAG_SEARCH_MODE` (`hybrid`\|`dense`\|`sparse`,
  default `hybrid`) and `RAG_RERANK_ENABLED` (default `true`). Not exposed on
  the public `/query` API — settings-only, read once at process startup.
- `app/services/vector_store.py` — `VectorStore.hybrid_search(..., mode=...)`.
  `dense`/`sparse` run just that half as a plain ANN/lexical search instead of
  the RRF-fused default. **FS-669's org-scoping was left untouched** — this
  branch's `delete_by_doc`/`delete_by_doc_excluding_generation` already
  required `org_id`; the port only added the `mode` param to `hybrid_search`.
- `app/services/rag_retriever.py` — `Retriever.retrieve(..., rerank=,
  search_mode=)`, defaulting to the settings above. With rerank disabled, the
  fused/raw candidates are taken top-N as-is instead of going through the
  cross-encoder.
- `backend/tests/rag_eval/test_metrics.py` — now also records `recall@1` and
  `recall@3` per cell (previously only `recall@5`/`mrr`), since the ablation
  aggregation wants all four.
- `scripts/thunder_bootstrap.sh` — added a `restart-backend <mode> <rerank>`
  subcommand: kills and relaunches just the bare backend process with the
  override env vars (worker and datastores untouched, since only the query
  path reads these settings). Two footguns documented inline: `pkill -f`
  self-matching its own argv when the same pattern text appears later in the
  same non-interactive SSH invocation, and a background job needing explicit
  `disown` to fully detach a one-shot `ssh host "cmd &"` session (interactive
  `tnr connect` sessions don't show this).
- `scripts/thunder_run_ablation.py` — new. Same four configs and aggregation
  as `backend/tests/rag_eval/run_ablation.py`, but drives
  `thunder_bootstrap.sh restart-backend` instead of `docker compose up -d
  backend`, since Thunder's Docker daemon can't build images or create
  networks (see `thunder_bootstrap.sh`'s header). Run it on-box after
  `thunder_bootstrap.sh start`.

**Known ceiling, not a bug:** dense-only and sparse-only converge to the same
result as hybrid whenever a document/format cell's chunk count is below
`RAG_RETRIEVE_LIMIT` (default 20) — every mode then returns the same complete
candidate set to the reranker, which decides the final order regardless of
retrieval mode. The current eval corpus runs small enough per cell that this
triggers. The no-rerank config is unaffected and is the only one of the four
that isolates the reranker's own contribution. Growing the corpus (more
chunks per document, or lowering `RAG_RETRIEVE_LIMIT` for the ablation run
specifically) would be needed to make the dense-vs-sparse comparison
meaningful — not done here.

### State for further integration

- **FS-666 (streaming route) is still the only unfixed item from the original
  four.** Not started this session.
- The ablation knobs are additive and default to today's only prior behavior
  (`hybrid` + rerank on), so they carry no behavior change for existing
  callers.
- Workstream A (replay onto `main`, k8s manifests) and workstream B (CI RAG
  job) are unchanged from the original verdict above — still not done, still
  the largest gaps before a genuine greenlight.
- tnr-0 was briefly cross-contaminated with files from
  `feature/RAG-Compliance-Doc-Pipeline` while spot-checking FS-669 against
  that branch's independent fix; restored to this branch's own files before
  any further work. Worth a clean `thunder_bootstrap.sh` re-run from a fresh
  snapshot before anything load-bearing, rather than trusting the live box's
  file state.

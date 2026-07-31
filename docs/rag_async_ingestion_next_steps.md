# RAG async ingestion — where it stands and what's next

The plan in `docs/superpowers/plans/2026-07-30-rag-async-ingestion.md` is fully
implemented on `feature/RAG-Compliance-Doc-Pipeline` (18 commits ahead of
`origin/feature/RAG-Compliance-Doc-Pipeline`, unpushed, not merged). This file
records what is actually proven versus what is only written, so the next
session doesn't have to re-derive it.

## What landed

| Commit | What |
|---|---|
| `baec3d8c` | `rag_documents` table + ORM model |
| `419dee20`, `531a6823` | `doc_id` validation (path escape, CRLF/log injection) |
| `acb9e8d2`, `7bb3211a` | `rag_index_queue`: claim / finalize / requeue, ABA-safe guard |
| `4b5d8e8c` | pipeline split into `store_document` + `index_document` |
| `49fa5714` | `app/workers/rag_indexing.py` — the queue-draining worker |
| `b98b3cbe` | `POST /rag/ingest` → 202; `GET /rag/documents/{doc_id}/status` |
| `9dd108b9` | compose service + k8s Deployment |
| `902c7945` | eval client + `verify_rag_e2e.py` poll for terminal status |
| `7ac4bf29` | followups doc: inline-ingestion item moved to Resolved |
| `8c7efab1` | NetworkPolicy egress + compose `rag-inference` readiness gate |
| `5c2e2f1e` | `rag_eval/test_robustness.py` migrated to the 202 contract |

## Verification state — read this before trusting anything

**Proven:**
- 51 tests green across the RAG suites, the topology suites and
  `test_route_auth_walk.py`.
- The API tests run against a **real Postgres** (testcontainers), including RLS
  — cross-org status reads 404, malformed `doc_id` 422s.
- `kubectl kustomize infrastructure/k8s/base` renders.
- Full backend suite shows **no new failures**: 23 failures + 3 collection
  errors (`test_*_scenario_builder.py`, stale `image_scenario_builder` import)
  reproduce identically at `4b5d8e8c`, verified in a throwaway worktree.

**Not proven — the whole async path has never run against live infrastructure:**
- No `docker compose --profile rag up` boot. Qdrant, SeaweedFS and
  rag-inference have never seen the new worker.
- `scripts/verify_rag_e2e.py` has not been run since it was migrated to polling.
- `backend/tests/rag_eval/` has not been run since `client.ingest()` became
  upload-then-poll.
- Nothing has been applied to a kind cluster.

Everything below item 1 is gated on item 1.

## Next steps, in order

### 1. Exercise it end to end in compose
```bash
docker compose --profile rag up -d   # qdrant, seaweedfs, rag-inference, rag-indexing-worker
python scripts/verify_rag_e2e.py
```
First boot downloads several GB of BGE-M3 weights; rag-inference's healthcheck
allows a 600s `start_period` and the worker now waits on it. The script polls
for up to 300s after the 202.

This is the first real test of: worker claims the row → `index_document`
against live Qdrant → `finalize` flips status → the status endpoint reports it.

### 2. Run the eval suite
```bash
cd backend/tests/rag_eval && python run_rag_eval.py      # or: pytest tests/rag_eval
```
`client.ingest()` returns the same dict shape it always did, so `run_rag_eval`
and the assertions were left unchanged — but that equivalence has only been
checked by reading, not by running. Watch `test_lifecycle.py` (re-ingests the
same `doc_id` twice; `upsert_queued` resets the row to `queued`, so a poll that
lands too early should see `queued`, not the previous run's `indexed`) and
`test_isolation.py` (two orgs ingesting concurrently — the first real test of
`FOR UPDATE SKIP LOCKED` under contention).

### 3. Fix the disabled-worker restart loop
`app/workers/rag_indexing.py:129-134` — when `RAG_INDEX_WORKER_ENABLED=false`
the module logs `rag_indexing_worker_disabled` and the process exits 0.
Under compose's `restart: unless-stopped` and under a k8s Deployment that is a
restart loop of no-ops, not a clean off switch. Either block forever after
logging, or drop the flag and turn the worker off by scaling to zero.

### 4. Kubernetes
- Apply `infrastructure/k8s/base/rag/` on kind and complete the isolated
  component verification from
  `docs/superpowers/specs/2026-07-27-rag-k8s-isolated-design.md` — **still
  untracked**; commit or delete it.
- Then apply the worker Deployment and confirm the NetworkPolicies from
  `8c7efab1` actually let it reach Postgres, Qdrant, SeaweedFS and
  rag-inference. Default-deny-all is in effect, so a missing egress rule
  blackholes it silently, including DNS.
- Folding `base/rag/` into `overlays/{staging,production}` is still deferred.

### 5. Remaining ingestion followups
`docs/rag_ingestion_followups.md` items 1–4 are untouched by this pass: whole
file read into memory, shared rag-inference between ingest and query, the
non-atomic `delete_by_doc` → re-upsert window (the status/retry half landed,
the generation swap did not), and per-tenant ingest quotas.

### 6. Housekeeping
- 18 commits unpushed; branch not merged to `main`.
- The 3 scenario-builder collection errors are unrelated to RAG but will break
  any `pytest tests/` run that doesn't ignore them.

# RAG greenlight — current state

Branch `feature/RAG-Compliance-Doc-Pipeline` @ `b0f2ebd4` (local, not pushed).
Replaces the earlier FS-665 re-scope doc, which had grown into a long running
log; this is a snapshot instead. History is in git — see `git log` on this
branch for the full trail, or `docs/rag_thunder_restore.md` /
`docs/RAG_DEVELOPMENT.md` §8 for verification detail.

## Done

- **FS-669** — cross-tenant vector-deletion scoping fixed
  (`vector_store.py`'s `delete_by_doc`/`delete_by_doc_excluding_generation`
  both require `org_id`).
- **FS-666** — `POST /query/stream` SSE streaming route (`d8bf6ede`, fixed in
  `14e16b2f`). Live-verified on Thunder against real GPU generation:
  citations → token deltas → done, correct grounded answer. Fixed one real
  bug found in the process: `httpx`'s `*Timeout` exceptions stringify to
  `""`, so a mid-stream LLM timeout was surfacing as an empty SSE error
  detail — now falls back to the exception's type name.
- **RAG CI coverage** (`17ca54d3`, deduped in `294db26d`) — `rag-unit` job
  (11 test files against real Postgres+Qdrant, gates on every `feature/**`
  push) and `rag-eval-nightly` (full live-stack eval suite). The job body
  lives in a reusable workflow, `.github/workflows/rag-ci.yml`, so wiring
  the same coverage into `ci-cd.yml` later is a one-line `uses:` addition.
  `rag-inference` is also in `ci-cd.yml`'s image build matrix.
- **Full Thunder verification, 2026-08-27** (`b0f2ebd4`) — `verify_rag_e2e.py`
  PASS with the real async `rag-indexing-worker` in the loop for the first
  time; RAG unit/queue tests 61/62 (1 confirmed scratch-DB pollution
  artifact, not code); `rag_eval` 121/127, matching the known baseline
  content-quality gaps (`_twice_fail_flow` queries) plus one new, unrelated
  `LLM_TIMEOUT=120s` tail-latency finding on the non-streaming `/query`
  route. Verified state snapshotted as Thunder snapshot
  `omniusgrid-rag-dev-20260827`.

## Not done

1. **k8s-cluster verification** — everything above proves the compose/
   native-process path. Nothing has verified the async worker as an actual
   k8s Deployment: NetworkPolicy egress, cross-namespace DNS, and the
   manifest wiring itself are all still unverified (Thunder can't run real
   k8s — no image builds).
2. **mTLS env-var mismatch** — `base/backend-deployment.yaml` sets
   `CA_CERT_PATH`/etc., code reads `MTLS_CA_CERT_PATH`/etc. Needs a fix and
   a decision on `backend-tls`'s fate. See `RAG_DEVELOPMENT.md` §8.1.
3. **Namespace-topology decision** — keep `omniusgrid-rag` standalone vs.
   fold into `overlays/{staging,production}`. Blocks #4 and #5 below.
4. **Wire `rag-inference`'s built image tag** into whichever kustomization
   ends up owning `base/rag/` — blocked on #3.
5. **`QDRANT_API_KEY`/`RAG_INFERENCE_API_KEY` + NetworkPolicies** — blocked
   on #3.
6. **Qdrant PVC storage class** — pin a real `storageClassName` per
   environment (mirrors how `timescaledb`/`redpanda` already do it).
7. **Replay onto `main`** — not gating #1–6, but needed before this ships.
   This branch is diverged from `origin/main`; the RAG-specific diff is
   ~32 files. One real conflict: this branch's migrations
   `043_rag_documents.sql`/`044_rag_document_size_bytes.sql` collide with
   main's own different `043`/`044` — needs renumbering to `068`/`069`
   (main's current highest). The 5 diverged k8s base manifests are additive
   on both sides, not a logic conflict — mechanical merge. Recommended
   mechanism: cherry-pick the RAG-tagged commits onto a fresh branch off
   current `origin/main`, not a merge/rebase of the whole branch.

## Next step

Items 1–6 are the k8s-wiring phase. Start at #1 (a real cluster, not
Thunder) — everything else assumes the worker actually works as a
Deployment before it's worth tuning storage classes or wiring secrets
around it.

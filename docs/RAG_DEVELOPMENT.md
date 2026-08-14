# RAG Pipeline — Development & Deployment Guide

This is the map to read **before** wiring the RAG stack into Docker Compose / k8s.
The application code is deployment-agnostic on purpose: every dependency is a URL
+ config, so the same images run across multiple topologies. This doc records the
services, how they connect, and how they compose into each deployment shape.

> Status: application layer is code-complete (document store, embeddings/reranker
> service + clients, vector store) and ingestion is **asynchronous** — the API
> queues, a dedicated `rag-indexing-worker` indexes. Read
> [§1.1](#11-ingestion-is-asynchronous--where-the-seam-actually-is) before
> deploying anything: a stack without that worker accepts uploads and silently
> never indexes them. Compose is wired for the full set (`qdrant`, `seaweedfs`,
> `rag-inference`, `rag-indexing-worker` under the `rag` profile). To bring it up
> locally, jump to [§7](#7-running--testing-the-rag-backend-locally).
> Kubernetes manifests exist for everything but have **only been verified
> pre-async** — see [§8](#8-kubernetes-deployment--status-known-issues--next-steps).

---

## 1. Service inventory

Two tiers, split by resource profile. This split is the core design decision: the
stateful tier needs persistent disk and is CPU-only; the GPU tier is stateless and
can live on a different host (RunPod) entirely.

### Stateful / CPU tier
| Service | Image / build | Port(s) | Persistence | Notes |
|---|---|---|---|---|
| backend (FastAPI) | `./backend` | 8000 | none | thin orchestrator; **no ML deps, no GPU**. Stores the blob and queues a row; does not index |
| `rag-indexing-worker` | `./backend`, `python -m app.workers.rag_indexing` | — | none | claims queued `rag_documents` rows → parse→chunk→embed→upsert |
| SeaweedFS | `chrislusf/seaweedfs` | 9333, 8888, 8333, 8080 | **yes** (`/data`) | doc blob store (S3 API on 8333) |
| Qdrant | `qdrant/qdrant` | 6333 (http), 6334 (grpc) | **yes** (`/qdrant/storage`) | vector store |
| Postgres/TimescaleDB | `timescale/timescaledb` | 5432 | **yes** | app + RAG metadata; **also the ingest queue** (`rag_documents`) |
| Redis | `redis:7-alpine` | 6379 | optional | cache |

> The RAG index worker is **not** the `ingestion-worker` service, and does not
> use `WORKER_MODE`. `ingestion-worker` (`WORKER_MODE=ingestion`) is the Kafka
> telemetry consumer and has nothing to do with documents. RAG indexing is a
> separate service running its own module, switched by
> `RAG_INDEX_WORKER_ENABLED`, with **no Redpanda dependency at all** — see §1.1.

### GPU / stateless tier
| Service | Image / build | Port | GPU | Notes |
|---|---|---|---|---|
| rag-inference | `./rag-inference` | 8000 | optional | BGE-M3 + reranker; CPU-first, ~5 GB VRAM on GPU |
| gemma (LLM) | vLLM / Ollama | 8000 (`/v1`) or 11434 | **yes** | OpenAI-compatible; ~24 GB fp16 or ~8-10 GB Q4 |

> Port note: `backend`, `rag-inference`, and a vLLM `gemma` all default to
> container port 8000. That's fine — they're separate containers. Only remap if
> you publish more than one to the host.

### 1.1 Ingestion is asynchronous — where the seam actually is

Upload and indexing are two separate processes joined by a Postgres row, not one
request. This is the single most important thing to know before deploying:
**`POST /rag/ingest` returns `202` and indexes nothing.**

```
POST /rag/ingest ──► backend ──► SeaweedFS (blob)          ] inside the request:
                        └─────► rag_documents (status=queued)]  two writes, no ML

                                      │  (row IS the queue)
                                      ▼
                        rag-indexing-worker  ── claims with FOR UPDATE SKIP LOCKED
                              │
                              ├──► SeaweedFS   read blob back
                              ├──► rag-inference  embed chunks
                              └──► Qdrant      upsert new generation, drop old

GET /rag/documents/{doc_id}/status ──► queued | indexing | indexed | skipped | failed
```

Consequences for deployment:

- **The worker is required.** Without `rag-indexing-worker` running, uploads
  succeed and are never indexed — they sit at `queued` forever and nothing
  errors. A backend-only deployment is silently non-functional for RAG.
- **No Redpanda in this path.** The queue is the `rag_documents` row claimed
  with `FOR UPDATE SKIP LOCKED`, so there is no outbox dispatcher to run and the
  worker is safe at **any replica count**. Do not add a Kafka dependency to it.
- **Callers must poll.** Any client that treated the old synchronous 200 as
  "indexed and queryable" is wrong now. `scripts/verify_rag_e2e.py` and
  `backend/tests/rag_eval/client.py` both poll the status endpoint.
- **Postgres is on the RAG critical path**, not just a metadata sidecar. The
  worker needs it, and `rag_documents` carries FORCE ROW LEVEL SECURITY — every
  query sets `app.current_org_id` first, including the worker's.

Design rationale, including why the row is the queue rather than a Redpanda
topic, is in `docs/superpowers/specs/2026-07-30-rag-async-ingestion-design.md`.

---

## 2. How the services connect

```
                         ┌──────────────┐
  client ─────────────►  │   backend    │  (thin, GPU-free orchestrator)
                         └──────┬───────┘
        ┌───────────────┬───────┼────────────────┬───────────────┐
        ▼               ▼       ▼                ▼               ▼
  SeaweedFS(S3)     Qdrant   rag-inference    gemma(LLM)     Postgres
  DocumentStore   VectorStore  Inference-      LLMClient      metadata
                               Client
```

The backend reaches each dependency **only by URL** (below). Nothing assumes
co-location, so any dependency can move to another host by changing one env var.

| Backend setting | Points at | Self-hosted default | Cloud/remote example |
|---|---|---|---|
| `S3_ENDPOINT_URL` | doc store | `http://seaweedfs:8333` | `https://s3.amazonaws.com` |
| `QDRANT_URL` (+`QDRANT_API_KEY`) | vector store | `http://qdrant:6333` | `https://xyz.qdrant.cloud` |
| `RAG_INFERENCE_URL` (+`RAG_INFERENCE_API_KEY`) | embed/rerank | `http://rag-inference:8000` | `https://xxx.runpod.net` |
| `RAG_INFERENCE_INGEST_URL` | batch ingest embed | *empty* (shares the above) | `http://rag-inference-ingest:8000` |
| `LLM_BASE_URL` (+`LLM_MODEL`,`LLM_API_KEY`) | LLM | `http://gemma:8000/v1` | `https://yyy.runpod.net/v1` |
| `DATABASE_URL` | metadata **+ ingest queue** | `postgresql://…@timescaledb:5432/…` | managed Postgres |

**`RAG_INFERENCE_INGEST_URL` is the ingest/query isolation lever.** Left empty,
bulk indexing and live query embeddings share one rag-inference, so a large
upload pegs the CPU that queries need and shows up as latency for every tenant.
Pointing it at a second replica gives batch embedding its own lane with no code
change. Worth setting as soon as ingest volume is nontrivial; the cost is
another ~5 GB of weights resident in that replica.

---

## 3. Deployment topologies

Same images, same code — topology lives entirely in env + which services each host
runs. Mirrors the existing `infrastructure/k8s/overlays/*` overlay-per-env pattern.

### A) All-in-one node (dev / single box with GPU)
Everything on one docker network; internal DNS names; no auth needed.
```
S3_ENDPOINT_URL=http://seaweedfs:8333
QDRANT_URL=http://qdrant:6333
RAG_INFERENCE_URL=http://rag-inference:8000
LLM_BASE_URL=http://gemma:8000/v1
```

### B) On-prem (self-hosted stores, local GPU, internal TLS)
Same as A but external hostnames + TLS + bearer tokens on inference.
```
S3_ENDPOINT_URL=https://minio.internal:9000
QDRANT_URL=https://qdrant.internal:6333
RAG_INFERENCE_URL=https://infer.internal:8443
RAG_INFERENCE_API_KEY=<token>
LLM_BASE_URL=https://llm.internal:8443/v1
LLM_API_KEY=<token>
```

### C) RunPod-split (GPU tier remote, stores in cloud)
Stateful tier stays put / on managed cloud; **GPU tier on RunPod**.
```
S3_ENDPOINT_URL=https://s3.amazonaws.com          # or self-hosted SeaweedFS
QDRANT_URL=https://xyz.qdrant.cloud
QDRANT_API_KEY=<key>
RAG_INFERENCE_URL=https://abc.proxy.runpod.net    # TLS + token REQUIRED
RAG_INFERENCE_API_KEY=<token>
LLM_BASE_URL=https://def.proxy.runpod.net/v1
LLM_API_KEY=<token>
```
Compose-wise, C uses a base compose file **without** the GPU services (they run
remotely) — e.g. `docker compose -f docker-compose.yml -f compose.no-gpu.yml up`.

---

## 4. Cross-cutting requirements

**Persistence (non-negotiable).** SeaweedFS `/data`, Qdrant `/qdrant/storage`, and
Postgres data must be on durable volumes. On a custom node = named volumes. On
RunPod = **Network Volumes** (pod disk is ephemeral — data is lost on restart).

**GPU access.** `rag-inference` (optional) and `gemma` (required) need
`nvidia-container-toolkit` on the host and device reservations:
```yaml
deploy:
  resources:
    reservations:
      devices: [{driver: nvidia, count: 1, capabilities: [gpu]}]
```
`rag-inference` auto-detects CUDA (fp16 on GPU, CPU fallback otherwise) — no code
change. Gemma 12B: 24 GB fp16 needs a 40-48 GB card alongside others, or quantize
to Q4 (~8-10 GB) to fit a single 24 GB card.

**Auth across hosts.** On one docker network, plain HTTP is fine. The moment the
GPU tier is remote (topology C), set `RAG_INFERENCE_API_KEY` / `LLM_API_KEY` and
use `https://`. The clients already send bearer tokens when set; the
`rag-inference` service enforces `INFERENCE_API_KEY` when present.

**Model weight cache.** Mount a volume at `rag-inference`'s `HF_HOME=/models` so
the ~5 GB of BGE weights aren't re-downloaded on every container recreate.

**Embedding model is a data contract.** `EMBEDDING_MODEL` (BGE-M3, dim 1024) must
match what indexed the Qdrant collection. Never vary it per-deployment; changing it
means re-indexing everything.

---

## 5. What each service exposes (health/readiness)

| Service | Endpoint | Use |
|---|---|---|
| backend | `/health` (aggregates below) | overall readiness |
| rag-inference | `GET /health` | model load + device/fp16 |
| Qdrant | `GET /healthz`, `/readyz` | vector store |
| SeaweedFS | `GET :9333/cluster/status` | master alive |
| gemma (OpenAI-compat) | `GET /v1/models` | LLM up |

The backend clients (`DocumentStore`, `VectorStore`, `RagInferenceClient`,
`LLMClient`) each have a `health_check()` returning `{available, ...}` — wire these
into `backend/app/api/health.py` so the backend reports a capability matrix.

---

## 6. Wiring checklist

Local Compose wiring is **done** (see `docker-compose.yml`, `rag` profile):

- [x] `seaweedfs` service + `seaweedfs-data` volume (config + `s3config.json` exist)
- [x] `qdrant` service + `qdrant-data` volume
- [x] `rag-inference` service (build `./rag-inference`) + `rag-models` model volume; CPU-first, GPU optional
- [x] backend: RAG env vars wired (`QDRANT_URL`, `S3_ENDPOINT_URL`, `RAG_INFERENCE_URL`, `LLM_BASE_URL`)
- [x] `rag-indexing-worker` service: backend image, `command: python -m app.workers.rag_indexing`, in the `rag` profile. Waits on `rag-inference` being **healthy** (not merely started) — its healthcheck allows a 600 s `start_period` for the first-boot weight download, and a worker that starts sooner would burn `RAG_INDEX_MAX_ATTEMPTS` against a service that isn't up yet and mark documents permanently `failed`.
- [x] `GET /api/v1/rag/health` capability matrix (`backend/app/api/rag.py`)

Still open (deployment, separate tasks):

- [ ] `gemma` service (vLLM/Ollama) as a **container** + GPU reservation — locally the LLM runs *natively* on the host (Ollama) and the backend reaches it via `host.docker.internal`
- [ ] `compose.no-gpu.yml` override for topology C (omits GPU services)
- [ ] Fold the four `health_check()`s into the backend `/health` aggregate too
- [ ] A second `rag-inference` replica wired to `RAG_INFERENCE_INGEST_URL` (the code path exists and is one env var; no compose service defines the replica yet)

### 6.1 RAG worker / ingest settings

| Setting | Default | What it does |
|---|---|---|
| `RAG_INDEX_WORKER_ENABLED` | `true` | `false` makes the worker idle instead of indexing. It stays running: exiting would read as a completed run to compose's `restart: unless-stopped` and to a k8s Deployment, turning the off switch into a restart loop. To actually reclaim resources, scale to zero. |
| `RAG_INDEX_POLL_INTERVAL_SECONDS` | `5` | How often the worker looks for queued rows. |
| `RAG_INDEX_MAX_ATTEMPTS` | `3` | Retries before a document is marked `failed`. |
| `RAG_INDEX_STALE_INDEXING_SECONDS` | `900` | When a row abandoned in `indexing` (killed worker) is re-queued. Must exceed worst-case indexing time — compose allows `RAG_INFERENCE_TIMEOUT` 180 s *per embed batch*. |
| `RAG_MAX_UPLOAD_BYTES` | 50 MiB | Rejected at the edge from `Content-Length` before the body is buffered, and again against the real size. Mirror this in the ingress `proxy-body-size`. |
| `RAG_MAX_CHUNKS_PER_DOC` | `2000` | Oversized documents are truncated and flagged rather than exploding the embed path. |
| `RAG_MAX_DOCUMENTS_PER_ORG` | `10000` | Per-tenant document quota; `409` when full. `0` = unlimited. |
| `RAG_MAX_TOTAL_BYTES_PER_ORG` | 50 GiB | Per-tenant storage quota; `409` when full. `0` = unlimited. |
| `RAG_INGEST_RATE_LIMIT_PER_MINUTE` | `60` | Per-tenant upload rate; `429` when exceeded. `0` = unlimited. Counted from `rag_documents`, so it is exact per org and survives restarts. |

Quotas are enforced **before** the blob is stored, so a rejected upload costs no
object storage. Current usage against each limit is reported in the `quota`
block of `GET /rag/documents`.

---

## 7. Running & testing the RAG backend locally

Goal: bring up the RAG data plane on one machine and **prove data actually lands**
in SeaweedFS, Qdrant, and comes back through retrieval. Everything below is driven
by two helpers so you don't hand-type `curl`:

- `scripts/rag.sh` — up/down/ingest/query/verify/doctor wrapper around Compose
- `scripts/verify_rag_e2e.py` — full data-plane E2E check (inspects each store directly)

### 7.1 Prerequisites

- Docker Desktop with **≥ 8 GB** allocated to the engine (12 GB+ for the full stack).
  BGE-M3 + reranker weights are ~5 GB and load into CPU RAM.
- ~10 GB free disk (container images + the ~5 GB weight cache).
- Python 3 on the host with `httpx` and `boto3` (only for `verify`): `pip install httpx boto3`.
- *(optional, for answer generation)* Ollama running **natively** on the host:
  `ollama serve` + `ollama pull gemma2:2b`. Retrieval works without it; only
  `generate=true` needs it.

Run the preflight first — it checks all of the above and the ports:

```bash
./scripts/rag.sh doctor
```

### 7.2 Bring the stack up

The RAG services are behind the `rag` Compose profile, so they are **opt-in** and
never start with a plain `docker compose up`.

```bash
./scripts/rag.sh up        # LEAN: qdrant + seaweedfs + rag-inference + backend
                           #       + rag-indexing-worker
# or
./scripts/rag.sh up-full   # everything (observability, redpanda, all workers) + rag profile
```

`rag-indexing-worker` is part of the lean set on purpose — it is what turns a
`queued` upload into a queryable document, so a stack without it looks healthy
and indexes nothing.

`up` blocks while `rag-inference` downloads BGE weights on **first boot** (~5 GB;
can take several minutes — cached in the `rag-models` volume afterward). Watch it:

```bash
./scripts/rag.sh logs      # follows rag-inference until "models_loaded":true
```

Host ports once up: backend `:8000`, rag-inference `:8001`, Qdrant `:6333`,
SeaweedFS S3 `:8333`. (Inside the network the backend still talks to
`rag-inference:8000` — only the published host port is remapped to 8001 to avoid
clashing with the backend.)

### 7.3 Smoke test by hand

```bash
# ingest a document (any .txt/.pdf/.docx the parsers support)
./scripts/rag.sh ingest ./path/to/policy.pdf

# retrieval only (no LLM) — returns citations
./scripts/rag.sh query "What is the emergency shutdown procedure?"

# full RAG with a generated answer (needs Ollama running natively)
./scripts/rag.sh query "What is the emergency shutdown procedure?" true
```

All calls authenticate with the `dev-token` bearer, which `backend/app/api/auth.py`
maps to a seeded dev org/user. The endpoints (prefix `/api/v1/rag`):

| Method | Path | Purpose |
|---|---|---|
| POST | `/ingest` | multipart upload → store blob + queue row. Returns **202 `{status: "queued"}`**; does not index. `413` too large, `429` rate limited, `409` over quota |
| GET | `/documents/{doc_id}/status` | poll until terminal: `indexed` / `skipped` (see `reason`) / `failed` (see `error`) |
| POST | `/query` | retrieve (`generate=false`) or retrieve+answer (`generate=true`) |
| GET | `/documents` | list this org's stored docs, plus a `quota` usage block |
| DELETE | `/documents/{doc_id}` | remove from **both** SeaweedFS and Qdrant |
| GET | `/health` | RAG capability matrix (each dependency's `health_check()`) |

A document is only queryable once its status reaches `indexed`. Ingesting and
immediately querying will find nothing — that is the async contract, not a bug.

### 7.4 Automated end-to-end verification

The `/health` endpoint only proves services are *reachable*. The E2E script proves
**data correctness** by inspecting each store directly (boto3 into SeaweedFS, REST
scroll into Qdrant), not just trusting the API response:

```bash
./scripts/rag.sh verify        # == python3 scripts/verify_rag_e2e.py
```

It runs 8 stages and exits non-zero on any failure:

1. **Preflight** — backend, rag-inference (models loaded), Qdrant, SeaweedFS all up
2. **BGE** — `POST /embed` direct; asserts a non-zero 1024-d dense vector + aligned sparse
3. **Ingest** — uploads a sentinel document through the backend API, then **polls
   `/documents/{doc_id}/status` until terminal** (up to 300 s). This stage now
   also proves the worker is alive: a stack with no `rag-indexing-worker` hangs
   here at `queued` rather than passing
4. **SeaweedFS** — HEAD+GET the blob at `{org}/{doc}/{filename}`; bytes match exactly
5. **Qdrant** — scroll by `doc_id`; point count == chunks, real named dense+sparse vectors, full payload
6. **Retrieval** — `generate=false`; asserts our doc is the **top citation**
7. **Generation** — `generate=true` *if Ollama is up* (skipped otherwise)
8. **Cleanup** — DELETE; asserts the doc is gone from **both** planes

Override endpoints via env if you remapped ports:
`BACKEND_URL`, `QDRANT_URL`, `S3_ENDPOINT`, `INFER_URL`, `OLLAMA_URL`.

### 7.4a Performance measurement

`verify_rag_e2e.py` proves correctness; `scripts/rag_perf.py` measures speed.
It drives the async ingestion contract the same way — POST, get 202, poll
`/documents/{doc_id}/status` — but times it instead of asserting on it, and
reports percentiles rather than a single "it worked" pass/fail:

```bash
python3 scripts/rag_perf.py                        # defaults: 20 docs / 64 KiB, 30 queries, concurrency 4
python3 scripts/rag_perf.py --num-docs 50 --doc-size-kb 256 --concurrency 8
python3 scripts/rag_perf.py --json --output run1.json    # machine-readable, for comparing across runs
python3 scripts/rag_perf.py --skip-drain --skip-query    # ingest-only pass
```

It measures, in order:

1. **Ingest throughput** — docs/min and MB/min for a configurable batch of
   synthetic documents, submitted at `--concurrency`
2. **Queued → indexed latency** — wall time from each document's `202` to its
   status row reaching a terminal state, reported as p50/p95 (nearest-rank,
   not a mean)
3. **Query latency** — p50/p95 over repeated `POST /query` calls against the
   `backend/tests/rag_eval` corpus (falls back to a synthetic doc + query if
   that harness isn't importable). Retrieval-only (`generate=false`) by
   default — pass `--query-generate` to fold LLM generation into the timing.
   The API exposes no per-stage (embed / Qdrant search / rerank) timings, so
   this driver does not fake a breakdown; it separately times direct
   `rag-inference /embed` calls as an auxiliary probe and labels that clearly
   as *not* a decomposition of the query latency above
4. **Worker drain rate** — submits a backlog of `--drain-docs` documents up
   front, then times how fast `rag-indexing-worker` clears it once the whole
   backlog is queued (isolated from client-side submission time)
5. **Quota-check overhead** — `check_ingest_quota()` runs one aggregate query
   before every upload, but nothing over HTTP separates that query's cost
   from the blob PUT and row upsert in the same request. The driver says so
   explicitly and reports the closest available proxies instead of inventing
   an isolated number

Every document the run creates (perf docs + the corpus doc used for query
timing) is deleted at the end; deletion failures are printed, not swallowed —
run with `--no-cleanup` only when you intend to inspect leftovers by hand.

Output is a human-readable table by default; `--json` emits a record
(timestamp, host, git SHA, `RAG_EMBED_BATCH`, embedding/reranker model +
device from `/rag/health`) meant to be diffed against a previous run's
`--json` output when comparing before/after a change. Same endpoint env vars
as `verify_rag_e2e.py` (`BACKEND_URL`, `INFER_URL`); see `--help` for the
full flag list (per-phase `--skip-*` flags, timeouts, poll interval).

**Do not run a perf pass against a shared/remote box while anything else is
using it** — concurrent ingestion contends for the same embedding GPU and
Postgres connections as whatever else is running, and will produce numbers
that reflect the contention, not the pipeline.

### 7.5 Tear down

```bash
./scripts/rag.sh down          # stops the RAG services (volumes/data preserved)
```

Add `docker compose down -v` only if you want to wipe the `qdrant-data`,
`seaweedfs-data`, and `rag-models` volumes (forces a full re-download next time).

### 7.6 Troubleshooting

- **`rag-inference` never reports `models_loaded:true`** — almost always still
  downloading weights on first boot, or the engine is starved of RAM. Check
  `./scripts/rag.sh logs` and confirm Docker has ≥ 8 GB.
- **Backend won't start / exits on boot** — RESOLVED on the convergence branch.
  Two cross-cutting backend issues used to block the whole app (and therefore the
  RAG endpoints) even though RAG code touches neither; both are now fixed
  properly in the committed `docker-compose.yml`, so no local workarounds are
  needed on a clean checkout:
  - *Schema `uuid` vs `varchar(36)` conflict on a fresh DB* — root cause was two
    competing schema sources of truth: the compose initdb mount ran the raw SQL
    chain via psql (which can't apply the TimescaleDB files that need
    `migrate.py`'s per-statement autocommit, and never recorded
    `schema_migrations`), then the backend's `create_all` built ORM-shaped
    tables on top. Combined with the pre-consolidation uuid/varchar drift
    (since repaired by migrations 032/039/040 + a CI schema-parity guard), a
    fresh boot could conflict. Fix: the initdb mount is gone; a one-shot
    `migrate` service (the SAME runner prod uses) is now the only schema
    builder, and the backend + all DB-writing workers wait on
    `service_completed_successfully`.
  - *Backend→Redpanda startup gate* — the API gated on `rpk cluster health`,
    which can lag minutes on cold boots, yet with `SCHEDULERS_IN_API=false`
    (the compose default) the API touches no Kafka at startup — dispatch and
    ingest live in the dedicated workers. Fix: the backend's Redpanda condition
    is `service_started`; the ingestion/OTA workers, which genuinely talk to
    Kafka at boot, keep `service_healthy`.
- **A document is stuck at `queued` and never indexes** — the
  `rag-indexing-worker` is not running, or cannot reach a dependency. This is
  the characteristic failure of the async design: the upload succeeded, so the
  API reports nothing wrong. Check `docker compose ps rag-indexing-worker` and
  its logs. If `RAG_INDEX_WORKER_ENABLED=false` the container runs but
  deliberately idles (logging `rag_indexing_worker_disabled` once at startup).
- **A document reaches `failed`** — infrastructure fault after
  `RAG_INDEX_MAX_ATTEMPTS` passes; the row's `error` says which. Most often
  rag-inference was not ready yet. Re-uploading the same `doc_id` resets the row
  to `queued` and starts over.
- **A document reaches `skipped`** — not an error: nothing indexable was found
  (unsupported type, empty extraction). The row's `reason` explains it.
- **`generate=true` returns no answer** — Ollama isn't reachable on the host.
  `ollama serve` + `ollama pull gemma2:2b`; the backend reaches it at
  `host.docker.internal:11434`. Retrieval (`generate=false`) is unaffected.

Application code for the document store, embeddings/reranker, and vector store is
in place and verified end-to-end by the flow above.

---

## 8. Kubernetes deployment — status, known issues & next steps

RAG on Kubernetes is split across **two** kustomize trees, which is easy to miss:

| What | Where | Namespace |
|---|---|---|
| Qdrant StatefulSet, SeaweedFS Deployment, rag-inference Deployment | `infrastructure/k8s/base/rag/` — standalone, applied **separately** | `omniusgrid-rag` |
| `rag-indexing-worker` Deployment | `infrastructure/k8s/base/rag-indexing-worker-deployment.yaml` — part of the **main** base | `omniusgrid` |

The stores live in their own namespace so `gemma-correlation-ai` can reuse them
later without coupling; the worker runs the backend image and needs the app's
Postgres and Secrets, so it belongs with the app. The backend's
`base/backend-deployment.yaml` carries `QDRANT_URL` / `S3_ENDPOINT_URL` /
`RAG_INFERENCE_URL` pointed at `*.omniusgrid-rag.svc.cluster.local`, and the
worker crosses the same namespace boundary.

**Applying `base/rag/` alone does not give you a working RAG deployment** —
uploads will queue and never index. The worker Deployment comes from the main
base, and its NetworkPolicy egress must reach Postgres (in-namespace) plus
Qdrant, SeaweedFS and rag-inference (cross-namespace) **and DNS**; the namespace
is default-deny, so a missing egress rule blackholes the worker silently.

**Verified — but against the pre-async code.** A full ingest → embed → store →
index → retrieve → cleanup pass via `scripts/verify_rag_e2e.py` passed on a local
`kind` cluster (port-forwarded from the host); every stage except LLM generation,
which needs Ollama on the host and is unrelated to the RAG stack.

That run predates async ingestion. It exercised a backend that indexed inline,
so it proves nothing about the `rag-indexing-worker` Deployment, its
NetworkPolicy egress, or the claim/finalize path — none of which existed then.
**Treat the k8s RAG deployment as unverified until `verify_rag_e2e.py` is re-run
against a cluster that includes the worker.** The compose path is the gate for
that: prove it there first (§7.4), then k8s.

### 8.1 Known issues (unfixed)

- **mTLS config env vars don't match their settings fields.**
  `base/backend-deployment.yaml` sets `CA_CERT_PATH` / `SERVER_CERT_PATH` /
  `SERVER_KEY_PATH`, but `backend/app/core/config.py` actually reads
  `MTLS_CA_CERT_PATH` / `MTLS_SERVER_CERT_PATH` / `MTLS_SERVER_KEY_PATH`. The one
  live consumer of the CA path (`cloud_gateway.py`'s outbound mTLS to the cloud
  gateway) silently falls back to its hardcoded default (`/certs/ca.crt`, not
  mounted anywhere) instead of the `ca-certificate` Secret the manifest actually
  mounts. `MTLS_SERVER_CERT_PATH` / `MTLS_SERVER_KEY_PATH` are defined in
  `config.py` but **never read anywhere in the codebase** — the `backend-tls`
  Secret/volume mount currently serves no code path. Needs a real fix: rename the
  manifest's env vars to match, and either wire `backend-tls` to something real or
  drop it.
- **Namespace topology is still an open decision.** Keep `omniusgrid-rag`
  standalone (current state — reusable later by `gemma-correlation-ai` without
  coupling) vs. fold `base/rag/` into `overlays/{staging,production}`. Affects
  every hostname if it changes; decide before wiring staging/production traffic
  through it.
- **Auth is deliberately not wired.** No `QDRANT_API_KEY` / `RAG_INFERENCE_API_KEY`,
  no NetworkPolicies scoping ingress to `omniusgrid-rag` from only the app
  namespaces. Fine for an isolated single-network kind test; not fine once this
  shares a real cluster with other traffic.
- **CI/CD doesn't build or deploy `rag-inference` at all.** `.github/workflows/ci-cd.yml`'s
  `build-images` matrix is `[backend, frontend, edge-agent]` only; neither
  overlay's `kustomize edit set image` references a `rag-inference` tag.
  `base/rag/` has never been applied outside a local kind cluster.

### 8.2 Not a bug, but a real hazard if you apply manually

`app/main.py`'s startup (`init_db()`) unconditionally runs
`Base.metadata.create_all()` on every backend boot, regardless of `ENVIRONMENT`.
If the backend starts **before** the `db-migrate` Job has run against a fresh
database, `create_all()` builds the ORM's version of the schema first, and
`migrate.py` then refuses with *"schema exists but no schema_migrations
records"* — recoverable via `migrate.py --baseline` (see
`infrastructure/k8s/README.md`), but avoidable entirely by following the
documented apply order (Job first, wait for completion, then the rest). CI
already sequences it this way; this only bites on manual/concurrent applies.

### 8.3 Local kind-cluster test recipe (workarounds, not committed)

None of the following are in the committed manifests — they're specific to a
throwaway local cluster and were applied live with `kubectl patch` / piped `sed`:

- `timescaledb`'s PVC pins `storageClassName: fast-ssd`, which doesn't exist on
  kind — swap to kind's default (`standard`) for local testing.
- `backend` / `db-migrate` use `imagePullPolicy: Always`, which ignores an image
  loaded locally via `kind load docker-image` — override to `IfNotPresent` (or
  `Never`, as `rag-inference-deployment.yaml` already does) for local builds.
- `ca-certificate` / `backend-tls` Secrets are required volume mounts regardless
  of `MTLS_ENABLED` (Kubernetes can't conditionally skip a volume mount) — a
  throwaway self-signed cert via `openssl` satisfies the mount.
- `timescaledb`'s `exec`-based `pg_isready` liveness/readiness probes are
  expensive (spawn a process via containerd per check) and flake under the CPU
  contention of running the whole stack + image builds on one kind node — a
  `tcpSocket` probe on 5432 is a cheap, reliable substitute for local testing.
- The backend's `/health/ready` correctly reports `not_ready` without Redpanda
  deployed (it's a critical dependency by design) — if you skip Redpanda/workers
  for a scoped-down RAG-only test, port-forward to the backend **pod** directly
  rather than its Service (Services only route to Ready pods).

### 8.4 Next steps

0. **Re-verify end to end with the worker in the loop** — compose first
   (`./scripts/rag.sh verify`), then kind. Everything below is downstream of
   knowing the async path actually works against live infrastructure.
1. Fix the mTLS env var mismatch (§8.1) and decide `backend-tls`'s fate.
2. Decide the namespace-topology question (§8.1) before any staging/production wiring.
3. Pin a real `storageClassName` for `base/rag/`'s Qdrant PVC per environment
   (mirroring how `timescaledb`/`redpanda` already do it with `fast-ssd`), and
   revisit resource requests/limits once there's a sense of real load.
4. Add `rag-inference` to the CI build matrix and wire its image tag into
   whichever kustomization ends up owning `base/rag/`.
5. Wire `QDRANT_API_KEY` / `RAG_INFERENCE_API_KEY` and NetworkPolicies once the
   namespace-topology decision lands.

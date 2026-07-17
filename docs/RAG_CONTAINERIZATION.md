# RAG Pipeline — Containerization & Deployment Guide

This is the map to read **before** wiring the RAG stack into Docker Compose / k8s.
The application code is deployment-agnostic on purpose: every dependency is a URL
+ config, so the same images run across multiple topologies. This doc records the
services, how they connect, and how they compose into each deployment shape.

> Status: application layer is code-complete (document store, embeddings/reranker
> service + clients, vector store) **and** the local Docker Compose stack is wired
> (`qdrant`, `seaweedfs`, `rag-inference` under the `rag` profile). To bring it up
> and prove it end-to-end on your machine, jump to
> [§7 Running & testing the RAG backend locally](#7-running--testing-the-rag-backend-locally).

---

## 1. Service inventory

Two tiers, split by resource profile. This split is the core design decision: the
stateful tier needs persistent disk and is CPU-only; the GPU tier is stateless and
can live on a different host (RunPod) entirely.

### Stateful / CPU tier
| Service | Image / build | Port(s) | Persistence | Notes |
|---|---|---|---|---|
| backend (FastAPI) | `./backend` | 8000 | none | thin orchestrator; **no ML deps, no GPU** |
| ingestion/index worker | `./backend` (WORKER_MODE) | — | none | parse→chunk→embed→upsert |
| SeaweedFS | `chrislusf/seaweedfs` | 9333, 8888, 8333, 8080 | **yes** (`/data`) | doc blob store (S3 API on 8333) |
| Qdrant | `qdrant/qdrant` | 6333 (http), 6334 (grpc) | **yes** (`/qdrant/storage`) | vector store |
| Postgres/TimescaleDB | `timescale/timescaledb` | 5432 | **yes** | app + RAG metadata |
| Redis | `redis:7-alpine` | 6379 | optional | cache |
| Redpanda | `redpandadata/redpanda` | 9092, 29092 | yes | ingestion triggering |

### GPU / stateless tier
| Service | Image / build | Port | GPU | Notes |
|---|---|---|---|---|
| rag-inference | `./rag-inference` | 8000 | optional | BGE-M3 + reranker; CPU-first, ~5 GB VRAM on GPU |
| gemma (LLM) | vLLM / Ollama | 8000 (`/v1`) or 11434 | **yes** | OpenAI-compatible; ~24 GB fp16 or ~8-10 GB Q4 |

> Port note: `backend`, `rag-inference`, and a vLLM `gemma` all default to
> container port 8000. That's fine — they're separate containers. Only remap if
> you publish more than one to the host.

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
| `LLM_BASE_URL` (+`LLM_MODEL`,`LLM_API_KEY`) | LLM | `http://gemma:8000/v1` | `https://yyy.runpod.net/v1` |

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
- [x] index worker: reuse backend image with `WORKER_MODE`
- [x] `GET /api/v1/rag/health` capability matrix (`backend/app/api/rag.py`)

Still open (deployment, separate tasks):

- [ ] `gemma` service (vLLM/Ollama) as a **container** + GPU reservation — locally the LLM runs *natively* on the host (Ollama) and the backend reaches it via `host.docker.internal`
- [ ] `compose.no-gpu.yml` override for topology C (omits GPU services)
- [ ] Fold the four `health_check()`s into the backend `/health` aggregate too

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
# or
./scripts/rag.sh up-full   # everything (observability, redpanda, worker) + rag profile
```

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
| POST | `/ingest` | multipart upload → parse → chunk → embed → store + index |
| POST | `/query` | retrieve (`generate=false`) or retrieve+answer (`generate=true`) |
| GET | `/documents` | list this org's stored docs |
| DELETE | `/documents/{doc_id}` | remove from **both** SeaweedFS and Qdrant |
| GET | `/health` | RAG capability matrix (each dependency's `health_check()`) |

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
3. **Ingest** — uploads a sentinel document through the backend API
4. **SeaweedFS** — HEAD+GET the blob at `{org}/{doc}/{filename}`; bytes match exactly
5. **Qdrant** — scroll by `doc_id`; point count == chunks, real named dense+sparse vectors, full payload
6. **Retrieval** — `generate=false`; asserts our doc is the **top citation**
7. **Generation** — `generate=true` *if Ollama is up* (skipped otherwise)
8. **Cleanup** — DELETE; asserts the doc is gone from **both** planes

Override endpoints via env if you remapped ports:
`BACKEND_URL`, `QDRANT_URL`, `S3_ENDPOINT`, `INFER_URL`, `OLLAMA_URL`.

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
- **Backend won't start / exits on boot** — two known cross-cutting backend issues
  (a schema `uuid` vs `varchar(36)` conflict on a *fresh* DB, and the
  backend→Redpanda startup gate) can block the whole app, and therefore the RAG
  endpoints, even though RAG code doesn't touch either. The local `docker-compose.yml`
  carries **uncommitted** workarounds (Redpanda gate relaxed to `service_started`;
  SQL-migration initdb mount left off) so the stack comes up. A clean checkout won't
  have those — if the backend crashes at startup, that's why. These are tracked for a
  dedicated fix session.
- **`generate=true` returns no answer** — Ollama isn't reachable on the host.
  `ollama serve` + `ollama pull gemma2:2b`; the backend reaches it at
  `host.docker.internal:11434`. Retrieval (`generate=false`) is unaffected.

Application code for the document store, embeddings/reranker, and vector store is
in place and verified end-to-end by the flow above.

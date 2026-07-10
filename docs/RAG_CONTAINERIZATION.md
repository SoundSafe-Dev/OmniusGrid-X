# RAG Pipeline — Containerization & Deployment Guide

This is the map to read **before** wiring the RAG stack into Docker Compose / k8s.
The application code is deployment-agnostic on purpose: every dependency is a URL
+ config, so the same images run across multiple topologies. This doc records the
services, how they connect, and how they compose into each deployment shape.

> Status: application layer is code-complete (document store, embeddings/reranker
> service + clients, vector store). Compose wiring for the new services is **not
> yet added** — see the checklist at the end.

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

## 6. Wiring checklist (compose services still to add)

- [ ] `seaweedfs` service + `seaweedfs-data` volume (config + `s3config.json` exist)
- [ ] `qdrant` service + `qdrant-storage` volume
- [ ] `rag-inference` service (build `./rag-inference`) + `HF_HOME` model volume; GPU reservation optional
- [ ] `gemma` service (vLLM/Ollama) + GPU reservation  *(separate task)*
- [ ] backend: add the RAG env vars (already have sensible in-cluster defaults)
- [ ] index worker: reuse backend image with a RAG `WORKER_MODE`
- [ ] `compose.no-gpu.yml` override for topology C (omits GPU services)
- [ ] wire the four `health_check()`s into `backend/app/api/health.py`

Application code for the document store, embeddings/reranker, and vector store is
in place and verified; the above is packaging/wiring only.

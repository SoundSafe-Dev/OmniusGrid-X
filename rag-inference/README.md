# rag-inference

Standalone model server for the RAG pipeline's **embeddings** and **reranking**
steps. It is deliberately separate from the backend so model compute can live
wherever a deployment needs it (own node / on-prem / RunPod) while the backend
stays a thin, GPU-free orchestrator that only knows the service URL.

## Models

| Purpose | Model | Notes |
|---|---|---|
| Embeddings (dual-mode) | `BAAI/bge-m3` | dense (1024-d) **+** sparse lexical, one pass |
| Reranker | `BAAI/bge-reranker-v2-m3` | cross-encoder, 0-1 scores |

The embedding model is a **data contract** with the vector store. Do not change
`EMBEDDING_MODEL` without re-indexing — vectors from a different model are not
comparable.

## API

```
POST /embed    {"texts": [...], "is_query": false}
               -> {"model", "dense": [[...]], "sparse": [{"indices","values"}]}
POST /rerank   {"query": "...", "passages": [...]}
               -> {"model", "scores": [0-1, ...]}   # aligned to passages order
GET  /health   -> readiness + device/fp16 info
```

Sparse vectors are returned in Qdrant-native `{indices, values}` form. Set
`is_query=true` when embedding a search query (BGE-M3 encodes queries and
documents asymmetrically).

## Configuration (env)

| Var | Default | Meaning |
|---|---|---|
| `EMBEDDING_MODEL` | `BAAI/bge-m3` | embedding model id |
| `RERANKER_MODEL` | `BAAI/bge-reranker-v2-m3` | reranker model id |
| `USE_FP16` | `true` | fp16 on GPU; auto-disabled on CPU |
| `INFERENCE_API_KEY` | _(empty)_ | if set, requires `Authorization: Bearer <key>` |
| `HF_HOME` | `/models` | weight cache dir (mount a volume) |

## CPU vs GPU

CPU-first: with no GPU, fp16 is auto-disabled and it runs on CPU (fine for dev
and low volume — the whole embed+rerank stack is ~5 GB). To use a GPU, run the
container with GPU access (`--gpus all` or compose device reservations); CUDA is
picked up automatically. No code change.

## Run locally (without Docker)

```bash
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
# first start downloads ~5 GB of weights to $HF_HOME
```

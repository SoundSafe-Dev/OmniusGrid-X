"""
rag-inference service

Standalone FastAPI service exposing BGE-M3 embeddings (dual-mode: dense + sparse)
and BGE-Reranker-v2-m3 reranking. The backend reaches it over HTTP via
``RagInferenceClient``, so this can run on the same node, on-prem, or on RunPod
- the backend only knows the URL.

Endpoints:
    POST /embed   -> dense + sparse vectors (Qdrant-native sparse form)
    POST /rerank  -> cross-encoder relevance scores (0-1)
    GET  /health  -> readiness + capability info

Heavy inference runs in a threadpool so concurrent requests don't block the
event loop. Optional bearer auth (INFERENCE_API_KEY) for remote deployments.
"""

import os
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Depends, Header, HTTPException, status
from starlette.concurrency import run_in_threadpool

from app.model_manager import ModelManager
from app.schemas import (
    EmbedRequest,
    EmbedResponse,
    RerankRequest,
    RerankResponse,
    HealthResponse,
)

logger = structlog.get_logger()

manager = ModelManager()
API_KEY = os.getenv("INFERENCE_API_KEY", "")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Load weights once at startup (first run downloads them from HF Hub).
    manager.load()
    yield


app = FastAPI(title="OmniusGrid RAG Inference", version="0.1.0", lifespan=lifespan)


async def require_auth(authorization: str = Header(default="")) -> None:
    """Bearer-token auth, enforced only when INFERENCE_API_KEY is set."""
    if API_KEY and authorization != f"Bearer {API_KEY}":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="unauthorized"
        )


@app.post("/embed", response_model=EmbedResponse, dependencies=[Depends(require_auth)])
async def embed(req: EmbedRequest) -> EmbedResponse:
    dense, sparse = await run_in_threadpool(manager.embed, req.texts, req.is_query)
    return EmbedResponse(
        model=manager.embedding_model_name, dense=dense, sparse=sparse
    )


@app.post("/rerank", response_model=RerankResponse, dependencies=[Depends(require_auth)])
async def rerank(req: RerankRequest) -> RerankResponse:
    scores = await run_in_threadpool(manager.rerank, req.query, req.passages)
    return RerankResponse(model=manager.reranker_model_name, scores=scores)


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(
        status="ok" if manager.loaded else "loading",
        embedding_model=manager.embedding_model_name,
        reranker_model=manager.reranker_model_name,
        device=manager.device_str,
        fp16=manager.use_fp16,
        models_loaded=manager.loaded,
    )

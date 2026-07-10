"""
RAG Inference Client

Thin async HTTP client for the embeddings + reranker service (``rag-inference``).

Design:
- Embeddings and reranker are FIXED to BGE - they are a data contract with the
  vector store, so only the *endpoint* varies per deployment (own node / on-prem
  / RunPod). See ``settings.EMBEDDING_MODEL``.
- Remote-first: every call carries an optional bearer token and assumes the
  service may live on another host/network. TLS is just an ``https://`` URL.
- Graceful degradation: if ``RAG_INFERENCE_URL`` is unset the client reports
  itself unavailable instead of crashing, so storage-only deployments still run.

The service returns sparse vectors already in Qdrant's ``{indices, values}``
shape, so BGE-M3's token-id/weight dict never leaks into the backend.
"""

from typing import List, Dict, Any, Optional, Sequence, Tuple
from functools import lru_cache

import httpx
import structlog
from pydantic import BaseModel

from app.core.config import settings

logger = structlog.get_logger()


class SparseVector(BaseModel):
    """Sparse embedding in Qdrant-native form (maps to models.SparseVector)."""

    indices: List[int]
    values: List[float]


class Embedding(BaseModel):
    """One text's dual-mode embedding: dense vector + sparse lexical vector."""

    dense: List[float]
    sparse: SparseVector


class RagInferenceClient:
    """Async client for the BGE embeddings + reranker service."""

    def __init__(self) -> None:
        self.base_url: str = settings.RAG_INFERENCE_URL.rstrip("/")
        self.api_key: str = settings.RAG_INFERENCE_API_KEY
        self.timeout: float = settings.RAG_INFERENCE_TIMEOUT

    @property
    def available(self) -> bool:
        """True if an endpoint is configured for this deployment."""
        return bool(self.base_url)

    def _headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    async def _post(self, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        if not self.available:
            raise RuntimeError(
                "RAG inference service not configured (RAG_INFERENCE_URL is empty)."
            )
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(
                f"{self.base_url}{path}", json=payload, headers=self._headers()
            )
            resp.raise_for_status()
            return resp.json()

    async def embed(
        self, texts: Sequence[str], is_query: bool = False
    ) -> List[Embedding]:
        """Embed texts into dual-mode (dense + sparse) vectors.

        Use ``is_query=True`` for search queries and ``False`` for documents -
        BGE-M3 encodes them asymmetrically for better retrieval.
        """
        if not texts:
            return []
        data = await self._post(
            "/embed", {"texts": list(texts), "is_query": is_query}
        )
        return [
            Embedding(dense=dense, sparse=SparseVector(**sparse))
            for dense, sparse in zip(data["dense"], data["sparse"])
        ]

    async def embed_query(self, text: str) -> Embedding:
        """Convenience: embed a single search query."""
        result = await self.embed([text], is_query=True)
        return result[0]

    async def rerank(self, query: str, passages: Sequence[str]) -> List[float]:
        """Cross-encoder relevance scores (0-1) aligned to ``passages`` order."""
        passages = list(passages)
        if not passages:
            return []
        data = await self._post("/rerank", {"query": query, "passages": passages})
        return data["scores"]

    async def rerank_top_n(
        self, query: str, passages: Sequence[str], top_n: int
    ) -> List[Tuple[int, float]]:
        """Rerank and return the top-N as ``(original_index, score)``, sorted desc.

        The caller maps ``original_index`` back onto its candidate list.
        """
        scores = await self.rerank(query, passages)
        ranked = sorted(enumerate(scores), key=lambda pair: pair[1], reverse=True)
        return ranked[:top_n]

    async def health_check(self) -> Dict[str, Any]:
        """Connectivity + capability probe for the /health endpoint."""
        if not self.available:
            return {"available": False, "reason": "RAG_INFERENCE_URL not set"}
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(
                    f"{self.base_url}/health", headers=self._headers()
                )
                resp.raise_for_status()
                return {"available": True, "endpoint": self.base_url, **resp.json()}
        except Exception as exc:  # unhealthy, but never crash the probe
            logger.warning("rag_inference.health_failed", error=str(exc))
            return {"available": False, "reason": str(exc)}


@lru_cache()
def get_rag_inference() -> RagInferenceClient:
    """Cached singleton accessor, mirroring ``get_settings()``."""
    return RagInferenceClient()

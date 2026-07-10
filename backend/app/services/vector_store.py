"""
Vector Store Service

Async client for Qdrant - the RAG vector store. Holds one collection with named
vectors: a **dense** vector (BGE-M3, cosine) and a **sparse** vector (BGE-M3
lexical). Retrieval is Qdrant-native hybrid: dense ANN + sparse search fused
server-side with Reciprocal Rank Fusion (RRF) in a single round trip.

Deployment-modular like the rest of the pipeline: self-hosted Qdrant and Qdrant
Cloud differ only by ``QDRANT_URL`` (+ ``QDRANT_API_KEY``). Graceful degradation
if ``qdrant-client`` is absent or the URL is unset.

The dense dimension is pinned to ``settings.EMBEDDING_DIM`` - it is a data
contract with BGE-M3. Points carry ``{doc_id, chunk_id, s3_key, text, ...}`` in
the payload: ``text`` so the reranker/LLM need no round trip, ``s3_key`` so
citations can pull the original from the document store.
"""

from typing import List, Dict, Any, Optional, Sequence
from functools import lru_cache

import structlog
from pydantic import BaseModel

from app.core.config import settings

try:
    from qdrant_client import AsyncQdrantClient, models
except ImportError:  # qdrant-client not installed - service disabled until used
    AsyncQdrantClient = None
    models = None

logger = structlog.get_logger()


class ChunkPoint(BaseModel):
    """A chunk to index: dual-mode vectors + payload."""

    id: str  # point id (uuid string recommended)
    dense: List[float]
    sparse_indices: List[int]
    sparse_values: List[float]
    payload: Dict[str, Any]


class SearchResult(BaseModel):
    id: str
    score: float
    payload: Dict[str, Any]


class VectorStore:
    """Async Qdrant client for hybrid (dense + sparse) retrieval."""

    def __init__(self) -> None:
        self.url: str = settings.QDRANT_URL
        self.api_key: Optional[str] = settings.QDRANT_API_KEY or None
        self.collection: str = settings.QDRANT_COLLECTION
        self.dim: int = settings.EMBEDDING_DIM
        self.prefetch_limit: int = settings.QDRANT_PREFETCH_LIMIT
        self._client: Optional["AsyncQdrantClient"] = None

    @property
    def available(self) -> bool:
        """True if the client dependency is installed and an endpoint is set."""
        return AsyncQdrantClient is not None and bool(self.url)

    def _get_client(self) -> "AsyncQdrantClient":
        if AsyncQdrantClient is None:
            raise RuntimeError(
                "qdrant-client is not installed - cannot reach the vector store."
            )
        if not self.url:
            raise RuntimeError("Vector store not configured (QDRANT_URL is empty).")
        if self._client is None:
            self._client = AsyncQdrantClient(url=self.url, api_key=self.api_key)
        return self._client

    async def ensure_collection(self) -> None:
        """Create the hybrid collection if it does not exist (idempotent)."""
        client = self._get_client()
        if await client.collection_exists(self.collection):
            return
        await client.create_collection(
            collection_name=self.collection,
            vectors_config={
                "dense": models.VectorParams(
                    size=self.dim, distance=models.Distance.COSINE
                )
            },
            sparse_vectors_config={"sparse": models.SparseVectorParams()},
        )
        logger.info(
            "vector_store.collection_created",
            collection=self.collection,
            dim=self.dim,
        )

    async def upsert_chunks(self, points: Sequence[ChunkPoint]) -> int:
        """Insert/overwrite chunk points. Returns the number written."""
        if not points:
            return 0
        client = self._get_client()
        qdrant_points = [
            models.PointStruct(
                id=p.id,
                vector={
                    "dense": p.dense,
                    "sparse": models.SparseVector(
                        indices=p.sparse_indices, values=p.sparse_values
                    ),
                },
                payload=p.payload,
            )
            for p in points
        ]
        await client.upsert(
            collection_name=self.collection, points=qdrant_points, wait=True
        )
        logger.info("vector_store.upserted", count=len(qdrant_points))
        return len(qdrant_points)

    async def hybrid_search(
        self,
        dense: List[float],
        sparse_indices: List[int],
        sparse_values: List[float],
        limit: int = 10,
        query_filter: Optional["models.Filter"] = None,
    ) -> List[SearchResult]:
        """Dense + sparse retrieval fused with RRF, server-side.

        ``limit`` is the fused result size (feed these to the reranker). The
        per-mode candidate pool is ``QDRANT_PREFETCH_LIMIT``.
        """
        client = self._get_client()
        response = await client.query_points(
            collection_name=self.collection,
            prefetch=[
                models.Prefetch(
                    query=dense,
                    using="dense",
                    limit=self.prefetch_limit,
                    filter=query_filter,
                ),
                models.Prefetch(
                    query=models.SparseVector(
                        indices=sparse_indices, values=sparse_values
                    ),
                    using="sparse",
                    limit=self.prefetch_limit,
                    filter=query_filter,
                ),
            ],
            query=models.FusionQuery(fusion=models.Fusion.RRF),
            limit=limit,
            with_payload=True,
        )
        return [
            SearchResult(id=str(p.id), score=p.score, payload=p.payload or {})
            for p in response.points
        ]

    async def delete_by_doc(self, doc_id: str) -> None:
        """Delete all chunks belonging to a document (by ``doc_id`` payload)."""
        client = self._get_client()
        await client.delete(
            collection_name=self.collection,
            points_selector=models.FilterSelector(
                filter=models.Filter(
                    must=[
                        models.FieldCondition(
                            key="doc_id", match=models.MatchValue(value=doc_id)
                        )
                    ]
                )
            ),
        )
        logger.info("vector_store.deleted_doc", doc_id=doc_id)

    async def health_check(self) -> Dict[str, Any]:
        """Connectivity + capability probe for the /health endpoint."""
        if not self.available:
            reason = (
                "qdrant-client not installed"
                if AsyncQdrantClient is None
                else "QDRANT_URL not set"
            )
            return {"available": False, "reason": reason}
        try:
            client = self._get_client()
            exists = await client.collection_exists(self.collection)
            return {
                "available": True,
                "endpoint": self.url,
                "collection": self.collection,
                "collection_ready": exists,
            }
        except Exception as exc:  # unhealthy, but never crash the probe
            logger.warning("vector_store.health_failed", error=str(exc))
            return {"available": False, "reason": str(exc)}

    async def close(self) -> None:
        if self._client is not None:
            await self._client.close()
            self._client = None


@lru_cache()
def get_vector_store() -> VectorStore:
    """Cached singleton accessor, mirroring ``get_settings()``."""
    return VectorStore()

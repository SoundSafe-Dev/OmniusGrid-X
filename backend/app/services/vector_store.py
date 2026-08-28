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
        # Payload indexes for the fields we filter on: org_id (tenant isolation)
        # and doc_id (delete-by-doc). Keyword indexes keep filtered search fast.
        for field in ("org_id", "doc_id"):
            await client.create_payload_index(
                collection_name=self.collection,
                field_name=field,
                field_schema=models.PayloadSchemaType.KEYWORD,
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
        org_id: Optional[str] = None,
        mode: str = "hybrid",
    ) -> List[SearchResult]:
        """Dense and/or sparse retrieval, depending on ``mode``.

        ``limit`` is the result size (feed these to the reranker). Pass
        ``org_id`` for tenant isolation - it builds an ``org_id`` payload
        filter unless an explicit ``query_filter`` is given.

        ``mode`` (default ``"hybrid"``, the only behavior before this knob
        existed): both halves fused server-side with RRF, each drawing from a
        ``QDRANT_PREFETCH_LIMIT`` candidate pool. ``"dense"``/``"sparse"`` run
        just that one half as a plain ANN/lexical search - an ablation knob to
        isolate each mode's contribution to retrieval quality, not used by
        normal query traffic.
        """
        client = self._get_client()
        if query_filter is None and org_id is not None:
            query_filter = models.Filter(
                must=[
                    models.FieldCondition(
                        key="org_id", match=models.MatchValue(value=org_id)
                    )
                ]
            )
        if mode == "dense":
            response = await client.query_points(
                collection_name=self.collection,
                query=dense,
                using="dense",
                query_filter=query_filter,
                limit=limit,
                with_payload=True,
            )
        elif mode == "sparse":
            response = await client.query_points(
                collection_name=self.collection,
                query=models.SparseVector(
                    indices=sparse_indices, values=sparse_values
                ),
                using="sparse",
                query_filter=query_filter,
                limit=limit,
                with_payload=True,
            )
        elif mode == "hybrid":
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
        else:
            raise ValueError(f"Unknown search mode: {mode!r} (expected hybrid/dense/sparse)")
        return [
            SearchResult(id=str(p.id), score=p.score, payload=p.payload or {})
            for p in response.points
        ]

    @staticmethod
    def _doc_scope(doc_id: str, org_id: str) -> List["models.FieldCondition"]:
        """The conditions identifying one org's copy of one document.

        Both are mandatory, and ``org_id`` is not optional here the way it is on
        the search path. ``doc_id`` is caller-suppliable at ingest, so two
        tenants can legitimately hold the same one; a delete filtered on
        ``doc_id`` alone matches both copies and destroys the other tenant's
        vectors while leaving their ``rag_documents`` row reading ``indexed``.
        """
        return [
            models.FieldCondition(
                key="doc_id", match=models.MatchValue(value=doc_id)
            ),
            models.FieldCondition(
                key="org_id", match=models.MatchValue(value=org_id)
            ),
        ]

    async def delete_by_doc(self, doc_id: str, org_id: str) -> None:
        """Delete all chunks belonging to one org's copy of a document."""
        client = self._get_client()
        await client.delete(
            collection_name=self.collection,
            points_selector=models.FilterSelector(
                filter=models.Filter(must=self._doc_scope(doc_id, org_id))
            ),
        )
        logger.info("vector_store.deleted_doc", doc_id=doc_id, org_id=org_id)

    async def delete_by_doc_excluding_generation(
        self, doc_id: str, org_id: str, generation: str
    ) -> None:
        """Delete a document's chunks from every generation except ``generation``.

        Used for the ingest swap: the new generation is upserted in full first,
        then this drops the old one (plus any orphan left by a prior failed
        ingest) in a single call. Keeps re-ingest from ever leaving the doc
        with zero or partial vectors mid-write.

        Org-scoped for the same reason as ``delete_by_doc``, and it matters more
        here: this runs on every re-ingest, not only on an explicit delete, so
        an unscoped filter would let routine indexing wipe another tenant.
        """
        client = self._get_client()
        await client.delete(
            collection_name=self.collection,
            points_selector=models.FilterSelector(
                filter=models.Filter(
                    must=self._doc_scope(doc_id, org_id),
                    must_not=[
                        models.FieldCondition(
                            key="generation", match=models.MatchValue(value=generation)
                        )
                    ],
                )
            ),
        )
        logger.info(
            "vector_store.deleted_doc_old_generation",
            doc_id=doc_id,
            org_id=org_id,
            generation=generation,
        )

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

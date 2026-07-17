"""Request/response contracts for the rag-inference service.

These are the wire contract the backend's ``RagInferenceClient`` depends on.
Sparse vectors are returned in Qdrant-native ``{indices, values}`` form so the
backend never has to know about BGE-M3's token-id/weight dicts.
"""

from typing import List
from pydantic import BaseModel, Field


class EmbedRequest(BaseModel):
    texts: List[str] = Field(..., min_length=1)
    # BGE-M3 encodes queries and documents asymmetrically; set True for queries.
    is_query: bool = False


class SparseVector(BaseModel):
    indices: List[int]
    values: List[float]


class EmbedResponse(BaseModel):
    model: str
    dense: List[List[float]]
    sparse: List[SparseVector]


class RerankRequest(BaseModel):
    query: str
    passages: List[str] = Field(default_factory=list)


class RerankResponse(BaseModel):
    model: str
    # Relevance scores in 0-1, aligned to the input ``passages`` order.
    scores: List[float]


class HealthResponse(BaseModel):
    status: str
    embedding_model: str
    reranker_model: str
    device: str
    fp16: bool
    models_loaded: bool

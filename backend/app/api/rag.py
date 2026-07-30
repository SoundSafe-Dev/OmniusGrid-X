"""
RAG API

Exposes the retrieval-augmented pipeline over HTTP:

    POST   /ingest              multipart upload -> store + index a document
    POST   /query               ask a question, get a grounded, cited answer
    GET    /documents           list this org's stored documents
    DELETE /documents/{doc_id}  remove a document's vectors + blobs
    GET    /health              status of the RAG services

All endpoints are authenticated and scoped to the caller's organization: the
``org_id`` used for storage keys, vector payloads, and search filters comes from
the JWT-bound user, so tenants can never read or delete each other's documents.
"""

from typing import Optional, List, Dict, Any

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from pydantic import BaseModel, Field

from app.core.config import settings
from app.api.auth import get_current_active_user
from app.db.models import User
from app.services.rag_ingestion import get_ingestion_pipeline, IngestionResult
from app.services.rag_retriever import get_retriever, RagAnswer
from app.services.document_store import get_document_store

router = APIRouter()


def _org_id(user: User) -> str:
    if not getattr(user, "organization_id", None):
        raise HTTPException(status_code=403, detail="User has no organization.")
    return str(user.organization_id)


class QueryRequest(BaseModel):
    query: str = Field(..., min_length=1)
    top_n: Optional[int] = Field(None, ge=1, le=50)
    generate: bool = True  # False -> return ranked citations without an LLM call


@router.post("/ingest", response_model=IngestionResult, summary="Ingest a document")
async def ingest(
    file: UploadFile = File(...),
    doc_id: Optional[str] = Form(None),
    current_user: User = Depends(get_current_active_user),
) -> IngestionResult:
    """Store a file in the document store and index it for retrieval.

    Supports PDF, DOCX, images (with vision enabled), and plain text. The blob
    is always stored; ``indexed=false`` with a ``reason`` means it was stored
    but not vector-indexed (unsupported type, no extractable text, or the
    inference/vector service was unavailable).
    """
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Empty file.")
    if len(content) > settings.RAG_MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=(
                f"File too large ({len(content)} bytes); the limit is "
                f"{settings.RAG_MAX_UPLOAD_BYTES} bytes."
            ),
        )
    try:
        return await get_ingestion_pipeline().ingest_document(
            content=content,
            filename=file.filename or "upload",
            org_id=_org_id(current_user),
            doc_id=doc_id,
            content_type=file.content_type,
        )
    except RuntimeError as exc:  # document store not configured
        raise HTTPException(status_code=503, detail=str(exc))


@router.post("/query", response_model=RagAnswer, summary="Ask a question")
async def query(
    body: QueryRequest,
    current_user: User = Depends(get_current_active_user),
) -> RagAnswer:
    """Answer a question from this org's indexed documents, with citations."""
    try:
        return await get_retriever().retrieve(
            body.query,
            org_id=_org_id(current_user),
            top_n=body.top_n,
            generate=body.generate,
        )
    except RuntimeError as exc:  # inference/vector store unavailable
        raise HTTPException(status_code=503, detail=str(exc))


@router.get("/documents", summary="List this org's documents")
async def list_documents(
    current_user: User = Depends(get_current_active_user),
) -> Dict[str, Any]:
    docs = get_document_store()
    if not docs.available:
        raise HTTPException(status_code=503, detail="Document store unavailable.")
    try:
        keys = await docs.list_documents(prefix=f"{_org_id(current_user)}/")
    except RuntimeError as exc:  # object store unreachable (e.g. SeaweedFS down)
        raise HTTPException(status_code=503, detail=str(exc))
    return {"count": len(keys), "keys": keys}


@router.delete("/documents/{doc_id}", summary="Delete a document")
async def delete_document(
    doc_id: str,
    current_user: User = Depends(get_current_active_user),
) -> Dict[str, Any]:
    return await get_ingestion_pipeline().delete_document(
        doc_id=doc_id, org_id=_org_id(current_user)
    )


@router.get("/health", summary="RAG services health")
async def health(
    current_user: User = Depends(get_current_active_user),
) -> Dict[str, Any]:
    retriever = get_retriever()
    status = await retriever.health_check()
    status["document_store"] = await get_document_store().health_check()
    return status

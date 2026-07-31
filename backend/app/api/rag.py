"""
RAG API

Exposes the retrieval-augmented pipeline over HTTP:

    POST   /ingest                     multipart upload -> store + queue a document
    POST   /query                       ask a question, get a grounded, cited answer
    GET    /documents                   list this org's stored documents
    GET    /documents/{doc_id}/status   where a queued document got to
    DELETE /documents/{doc_id}          remove a document's vectors + blobs
    GET    /health                      status of the RAG services

All endpoints are authenticated and scoped to the caller's organization: the
``org_id`` used for storage keys, vector payloads, and search filters comes from
the JWT-bound user, so tenants can never read or delete each other's documents.
"""

from typing import Optional, List, Dict, Any

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    UploadFile,
    File,
    Form,
    status as http_status,
)
from pydantic import BaseModel, Field

from app.core.config import settings
from app.api.auth import get_current_active_user
from app.db.models import User
from app.services.rag_ingestion import get_ingestion_pipeline, IngestionResult
from app.services.rag_retriever import get_retriever, RagAnswer
from app.services.document_store import (
    get_document_store,
    InvalidDocumentId,
    validate_doc_id,
)
from app.services.rag_index_queue import get_status, list_for_org

router = APIRouter()


def _org_id(user: User) -> str:
    if not getattr(user, "organization_id", None):
        raise HTTPException(status_code=403, detail="User has no organization.")
    return str(user.organization_id)


def _validated_doc_id(doc_id: str) -> str:
    """Translate an unsafe doc_id into a 422 rather than a 500."""
    try:
        return validate_doc_id(doc_id)
    except InvalidDocumentId as exc:
        raise HTTPException(status_code=422, detail=str(exc))


class QueryRequest(BaseModel):
    query: str = Field(..., min_length=1)
    top_n: Optional[int] = Field(None, ge=1, le=50)
    generate: bool = True  # False -> return ranked citations without an LLM call


@router.post(
    "/ingest",
    response_model=IngestionResult,
    status_code=http_status.HTTP_202_ACCEPTED,
    summary="Queue a document for ingestion",
)
async def ingest(
    file: UploadFile = File(...),
    doc_id: Optional[str] = Form(None),
    current_user: User = Depends(get_current_active_user),
) -> IngestionResult:
    """Store a file and queue it for indexing.

    Returns ``202`` as soon as the blob is durable, with ``status="queued"``.
    Indexing happens on the rag-indexing worker; poll
    ``GET /rag/documents/{doc_id}/status`` for the outcome. Previously this
    endpoint indexed inline and could outlive the ingress read timeout on large
    documents.
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
    if doc_id is not None:
        doc_id = _validated_doc_id(doc_id)
    try:
        return await get_ingestion_pipeline().store_document(
            content=content,
            filename=file.filename or "upload",
            org_id=_org_id(current_user),
            doc_id=doc_id,
            content_type=file.content_type,
            uploaded_by=str(current_user.id),
        )
    except RuntimeError as exc:  # document store not configured/reachable
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
    """List stored documents.

    ``count``/``keys`` keep their original meaning and S3 source for backward
    compatibility; ``documents`` adds the Postgres registry view. The two can
    differ: blobs ingested before the registry existed have no row.
    """
    org_id = _org_id(current_user)
    docs = get_document_store()
    if not docs.available:
        raise HTTPException(status_code=503, detail="Document store unavailable.")
    try:
        keys = await docs.list_documents(prefix=f"{org_id}/")
    except RuntimeError as exc:  # object store unreachable (e.g. SeaweedFS down)
        raise HTTPException(status_code=503, detail=str(exc))
    return {
        "count": len(keys),
        "keys": keys,
        "documents": await list_for_org(org_id),
    }


@router.get("/documents/{doc_id}/status", summary="Ingestion status of a document")
async def document_status(
    doc_id: str,
    current_user: User = Depends(get_current_active_user),
) -> Dict[str, Any]:
    """Poll a queued document until it reaches a terminal status.

    Terminal statuses are ``indexed`` (vectors are queryable), ``skipped``
    (nothing indexable — see ``reason``) and ``failed`` (infrastructure fault
    after retries — see ``error``). Unknown ids 404 regardless of which tenant
    owns them, so this cannot be used to probe another org.
    """
    row = await get_status(_org_id(current_user), _validated_doc_id(doc_id))
    if row is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    return row


@router.delete("/documents/{doc_id}", summary="Delete a document")
async def delete_document(
    doc_id: str,
    current_user: User = Depends(get_current_active_user),
) -> Dict[str, Any]:
    return await get_ingestion_pipeline().delete_document(
        doc_id=_validated_doc_id(doc_id), org_id=_org_id(current_user)
    )


@router.get("/health", summary="RAG services health")
async def health(
    current_user: User = Depends(get_current_active_user),
) -> Dict[str, Any]:
    retriever = get_retriever()
    status = await retriever.health_check()
    status["document_store"] = await get_document_store().health_check()
    return status

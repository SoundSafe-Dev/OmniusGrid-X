"""
RAG API

Exposes the retrieval-augmented pipeline over HTTP:

    POST   /ingest              multipart upload -> store + index a document
    POST   /query               ask a question, get a grounded, cited answer
    GET    /documents           list this org's stored documents
    POST   /documents/link      presigned URL to open a cited document
    DELETE /documents/{doc_id}  remove a document's vectors + blobs
    GET    /health              status of the RAG services

All endpoints are authenticated and scoped to the caller's organization: the
``org_id`` used for storage keys, vector payloads, and search filters comes from
the JWT-bound user, so tenants can never read or delete each other's documents.
"""

from typing import Optional, List, Dict, Any

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from app.core.config import settings
from app.core.tenant import get_tenant_db
from app.api.auth import get_current_active_user
from app.db.models import User
from app.services.rag_ingestion import get_ingestion_pipeline, IngestionResult
from app.services.rag_retriever import get_retriever, RagAnswer
from app.services.rag_erp_context import build_erp_context
from app.services.document_store import get_document_store

logger = structlog.get_logger()

router = APIRouter()


def _org_id(user: User) -> str:
    if not getattr(user, "organization_id", None):
        raise HTTPException(status_code=403, detail="User has no organization.")
    return str(user.organization_id)


class QueryRequest(BaseModel):
    query: str = Field(..., min_length=1)
    top_n: Optional[int] = Field(None, ge=1, le=50)
    generate: bool = True  # False -> return ranked citations without an LLM call


class DocumentLinkRequest(BaseModel):
    s3_key: str = Field(..., min_length=1)


class DocumentLinkResponse(BaseModel):
    url: str
    expires_in: int


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
    db: AsyncSession = Depends(get_tenant_db),
) -> RagAnswer:
    """Answer a question from this org's indexed documents, with citations.

    The answer is grounded in the document corpus and is the only thing cited.
    The generator is additionally given a block of the organization's own
    operational records so the answer can be specific to current conditions;
    that block is prompt-side only and appears nowhere in this response. See
    ``rag_erp_context`` for why it is a separate leg rather than a second corpus,
    and the ``rag_retriever.answered`` log event for its audit trail.
    """
    org_id = _org_id(current_user)

    erp_context, erp_meta = "", None
    if settings.RAG_ERP_CONTEXT_ENABLED:
        try:
            erp_context, erp_meta = await build_erp_context(db, org_id, body.query)
        except Exception as exc:  # noqa: BLE001
            # NEVER fail a compliance question because the operational leg broke.
            # It is an enrichment; the document answer stands without it.
            logger.warning("rag.erp_context_failed", org_id=org_id, error=str(exc))
            erp_context, erp_meta = "", None

    try:
        return await get_retriever().retrieve(
            body.query,
            org_id=org_id,
            top_n=body.top_n,
            generate=body.generate,
            erp_context=erp_context or None,
            erp_meta=erp_meta,
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
    keys = await docs.list_documents(prefix=f"{_org_id(current_user)}/")
    return {"count": len(keys), "keys": keys}


@router.post(
    "/documents/link",
    response_model=DocumentLinkResponse,
    summary="Presigned URL for a cited document",
)
async def document_link(
    body: DocumentLinkRequest,
    current_user: User = Depends(get_current_active_user),
) -> DocumentLinkResponse:
    """Turn a citation's ``s3_key`` into a time-limited URL that opens the file.

    A citation is only useful if the reader can get to the document behind it, and
    until now nothing exposed ``DocumentStore.generate_presigned_url`` over HTTP.

    POST, not GET, so the key travels in a body rather than in a URL that lands in
    every access log and proxy trace between here and the browser.
    """
    org_id = _org_id(current_user)
    key = body.s3_key

    # THE KEY COMES FROM THE CLIENT. Document keys are `{org_id}/{doc_id}/{name}`,
    # so without this check any authenticated user could presign any other
    # tenant's document by editing one UUID - a direct IDOR, and one that hands
    # back a URL that keeps working for an hour after the check would have failed.
    # `..` is rejected outright rather than normalized: a key that needs
    # normalizing is not one this API produced.
    if not key.startswith(f"{org_id}/") or ".." in key:
        logger.warning(
            "rag.document_link_rejected",
            org_id=org_id,
            user_id=str(current_user.id),
            key_prefix=key.split("/", 1)[0][:64],
        )
        raise HTTPException(status_code=403, detail="Document is not in your organization.")

    docs = get_document_store()
    if not docs.available:
        raise HTTPException(status_code=503, detail="Document store unavailable.")
    try:
        url = await docs.generate_presigned_url(key)
    except RuntimeError as exc:  # store not configured
        raise HTTPException(status_code=503, detail=str(exc))
    return DocumentLinkResponse(
        url=url, expires_in=settings.S3_PRESIGN_EXPIRE_SECONDS
    )


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

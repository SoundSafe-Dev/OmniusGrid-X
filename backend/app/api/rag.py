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


#: An unreachable object store is a 503, not a 500 (FS-431).
#:
#: `DocumentStore.available` is `aioboto3 is not None` — a check that the PACKAGE is
#: installed. It is True on every deployment, so the `if not docs.available: raise 503`
#: guards in this file could never fire for the condition anyone actually hits: the store
#: is configured and simply not answering. `GET /documents` and `DELETE /documents/{id}`
#: both surfaced `EndpointConnectionError: Could not connect to seaweedfs:8333` as a 500,
#: which tells a caller "this API is broken" about a dependency being down.
#:
#: 503 is the decision, matching what this file already does when the store is absent and
#: what every Redis-backed endpoint here does. It is retryable, it does not page anyone for
#: a bug in this service, and it is honest: we could not reach storage.
#:
#: `ClientError` is deliberately NOT in here. A 404 on a bucket or a signature rejection is
#: a configuration defect in this service, and turning it into "try again later" would hide
#: a broken deployment behind a status code that says nothing is wrong.
#: BOTH stores, because the delete path touches both. The register named SeaweedFS; the
#: DELETE actually failed on QDRANT first — `vectors.delete_by_doc` runs before any blob is
#: touched — so a fix covering only the object store would have left the endpoint 500ing and
#: the walk would have said so. `VectorStore.available` is `client installed and a URL set`:
#: the same configured-not-reachable check as `DocumentStore.available`, in a second file.
#:
#: `UnexpectedResponse` is excluded for the reason `ClientError` is: it means the store
#: ANSWERED and refused. That is a defect here, not an outage there.
_TRANSPORT: tuple[type[BaseException], ...] = (OSError,)
try:  # pragma: no cover - httpx is a hard dependency, guarded for symmetry
    import httpx

    # `httpx.TransportError` covers connect/read/write/pool failures and NOT
    # `HTTPStatusError`, which means the service answered — the same distinction the
    # `UnexpectedResponse` note above makes. Added because `httpx.ConnectError` is not an
    # `OSError` subclass, so an unreachable generator host escaped this tuple entirely.
    _TRANSPORT += (httpx.TransportError,)
except ImportError:  # pragma: no cover
    pass
try:  # pragma: no cover - import shape mirrors the services' optional dependencies
    from botocore.exceptions import BotoCoreError

    _TRANSPORT += (BotoCoreError,)
except ImportError:  # pragma: no cover
    pass
try:  # pragma: no cover
    from qdrant_client.http.exceptions import ResponseHandlingException

    _TRANSPORT += (ResponseHandlingException,)
except ImportError:  # pragma: no cover
    pass

#: Kept as a name because the guards and the `except` clauses read better for it.
_StoreTransportError = _TRANSPORT


class _StoreUnreachable(HTTPException):
    def __init__(self, exc: Exception) -> None:
        logger.warning("rag.document_store_unreachable", error=str(exc)[:200])
        super().__init__(
            status_code=503,
            detail="Document store unreachable. This is a dependency outage, not a "
                   "rejection of your request; retry shortly.",
        )


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
    except _StoreTransportError as exc:
        # THE COMMENT ABOVE WAS RIGHT AND THE CLAUSE WAS TOO NARROW (FS-742). "Inference
        # or vector store unavailable" is exactly the intent, and the commonest way that
        # happens — the generator host does not resolve — arrives as `httpx.ConnectError`,
        # which is not a `RuntimeError`. So `POST /rag/query` answered **500** whenever the
        # inference service was simply absent: one of the eight operations in the API still
        # returning a 500 under the contract gate, on the most ordinary outage there is.
        #
        # `_StoreTransportError` is the tuple this module already built for the document
        # store, and it is right here for the same reason: `OSError` and the client
        # libraries' transport errors mean the dependency did not answer. A store that
        # ANSWERS and refuses is deliberately excluded — that is a defect here, not an
        # outage there.
        raise _StoreUnreachable(exc) from exc


@router.get("/documents", summary="List this org's documents")
async def list_documents(
    current_user: User = Depends(get_current_active_user),
) -> Dict[str, Any]:
    docs = get_document_store()
    if not docs.available:
        raise HTTPException(status_code=503, detail="Document store unavailable.")
    try:
        keys = await docs.list_documents(prefix=f"{_org_id(current_user)}/")
    except _StoreTransportError as exc:
        raise _StoreUnreachable(exc) from exc
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
    """Remove a document's vectors and blobs.

    The delete is org-scoped inside the pipeline — blobs live under `{org_id}/{doc_id}/`
    and the prefix comes from the token, never the path — so an id belonging to another
    tenant deletes nothing rather than deleting theirs.
    """
    try:
        return await get_ingestion_pipeline().delete_document(
            doc_id=doc_id, org_id=_org_id(current_user)
        )
    except _StoreTransportError as exc:
        raise _StoreUnreachable(exc) from exc


@router.get("/health", summary="RAG services health")
async def health(
    current_user: User = Depends(get_current_active_user),
) -> Dict[str, Any]:
    retriever = get_retriever()
    status = await retriever.health_check()
    # A health check that raises when a dependency is down reports nothing about the rest
    # of the system — the one request where the answer matters most.
    try:
        status["document_store"] = await get_document_store().health_check()
    except _StoreTransportError as exc:
        status["document_store"] = {"status": "unreachable", "error": str(exc)[:200]}
    return status

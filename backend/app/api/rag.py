"""
RAG API

Exposes the retrieval-augmented pipeline over HTTP:

    POST   /ingest                     multipart upload -> store + queue a document
    POST   /query                       ask a question, get a grounded, cited answer
    POST   /query/stream                same, but stream the answer over SSE
    GET    /documents                   list this org's stored documents
    GET    /documents/{doc_id}/status   where a queued document got to
    DELETE /documents/{doc_id}          remove a document's vectors + blobs
    GET    /health                      status of the RAG services

All endpoints are authenticated and scoped to the caller's organization: the
``org_id`` used for storage keys, vector payloads, and search filters comes from
the JWT-bound user, so tenants can never read or delete each other's documents.
"""

import json
from datetime import datetime
from typing import AsyncIterator, Optional, List, Dict, Any

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    UploadFile,
    File,
    Form,
    status as http_status,
)
from fastapi.responses import StreamingResponse
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
from app.services.transport_errors import TRANSPORT_ERRORS
from app.services.document_store import (
    get_document_store,
    InvalidDocumentId,
    stream_size,
    validate_doc_id,
)
from app.services.rag_index_queue import (
    check_ingest_quota,
    get_status,
    list_for_org,
    quota_usage,
)

logger = structlog.get_logger()

router = APIRouter()


#: Kept as a name because the guards and the `except` clauses read better for it.
_StoreTransportError = TRANSPORT_ERRORS


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


def _validated_doc_id(doc_id: str) -> str:
    """Translate an unsafe doc_id into a 422 rather than a 500."""
    try:
        return validate_doc_id(doc_id)
    except InvalidDocumentId as exc:
        raise HTTPException(status_code=422, detail=str(exc))


async def _enforce_ingest_quota(
    *, org_id: str, doc_id: Optional[str], size_bytes: int
) -> None:
    """Refuse an upload that would exceed this org's ingest budget.

    Checked before the blob is stored, so a rejected upload costs no object
    storage. 429 for the rate limit (retrying later works), 409 for the
    document/byte quotas (retrying does not help until something is deleted).
    """
    rejection = await check_ingest_quota(
        org_id=org_id, doc_id=doc_id, size_bytes=size_bytes
    )
    if rejection is not None:
        raise HTTPException(
            status_code=rejection.status, detail=rejection.detail
        )


class QueryRequest(BaseModel):
    query: str = Field(..., min_length=1)
    top_n: Optional[int] = Field(None, ge=1, le=50)
    generate: bool = True  # False -> return ranked citations without an LLM call


class DocumentStatus(BaseModel):
    """The ingestion state of one document, as `rag_index_queue._to_dict` returns it.

    Declared rather than left as `Dict[str, Any]` because this is the response a caller
    POLLS: an SDK generated from the schema is how anyone waits for `indexed`, and a
    bare dict gives them nothing to wait on.
    """

    doc_id: str
    status: str
    kind: Optional[str] = None
    filename: Optional[str] = None
    s3_key: Optional[str] = None
    size_bytes: Optional[int] = None
    num_blocks: Optional[int] = None
    num_chunks: Optional[int] = None
    reason: Optional[str] = None
    error: Optional[str] = None
    attempts: Optional[int] = None
    created_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class DocumentLinkRequest(BaseModel):
    s3_key: str = Field(..., min_length=1)


class DocumentLinkResponse(BaseModel):
    url: str
    expires_in: int


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

    The upload is never read into memory here. Starlette has already spooled
    the multipart body to a temp file, so its size is a ``seek``/``tell`` and
    the file object itself is handed to the object store to stream. Calling
    ``.read()`` would undo that and put the whole document back on the heap.
    """
    org_id = _org_id(current_user)
    size_bytes = stream_size(file.file)
    if size_bytes == 0:
        raise HTTPException(status_code=400, detail="Empty file.")
    if size_bytes > settings.RAG_MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=(
                f"File too large ({size_bytes} bytes); the limit is "
                f"{settings.RAG_MAX_UPLOAD_BYTES} bytes."
            ),
        )
    if doc_id is not None:
        doc_id = _validated_doc_id(doc_id)

    await _enforce_ingest_quota(org_id=org_id, doc_id=doc_id, size_bytes=size_bytes)

    try:
        return await get_ingestion_pipeline().store_document(
            content=file.file,
            filename=file.filename or "upload",
            org_id=org_id,
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


def _sse(event: str, data: Dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


@router.post(
    "/query/stream",
    # SSE carries no JSON body, so `response_model` cannot describe it. Declaring the
    # media type is how a route says that HONESTLY: the contract gate and
    # `test_response_model_coverage_ratchet.py` both read `responses`, and a declared
    # non-JSON content type counts as documented rather than as debt. The alternative —
    # raising the ratchet — would have recorded a describable route as undescribed.
    responses={200: {"content": {"text/event-stream": {}}}},
    summary="Ask a question, stream the answer (SSE)",
)
async def query_stream(
    body: QueryRequest,
    current_user: User = Depends(get_current_active_user),
) -> StreamingResponse:
    """Same retrieval as ``/query``, but streams the generated answer over
    Server-Sent Events instead of waiting for the full completion.

    Retrieval and reranking run first, synchronously, so a 503 for an
    unavailable inference/vector service still comes back as a normal HTTP
    error rather than mid-stream. Frames after that, in order:

    - one ``citations`` event - the same structured sources ``/query``
      returns, plus ``used_context``/``generated`` flags
    - zero or more ``delta`` events, one per token chunk, while ``generated``
      was true
    - a terminal ``done`` event (or ``error`` if generation fails mid-stream)
    """
    org_id = _org_id(current_user)
    try:
        citations, used_context, generated, tokens = await get_retriever().stream(
            body.query, org_id=org_id, top_n=body.top_n, generate=body.generate
        )
    except RuntimeError as exc:  # inference/vector store unavailable
        raise HTTPException(status_code=503, detail=str(exc))

    async def event_source() -> AsyncIterator[str]:
        yield _sse(
            "citations",
            {
                "citations": [c.model_dump() for c in citations],
                "used_context": used_context,
                "generated": generated,
            },
        )
        if generated and tokens is not None:
            try:
                async for delta in tokens:
                    yield _sse("delta", {"content": delta})
            except (RuntimeError, *TRANSPORT_ERRORS) as exc:
                # NARROWED (2026-08-28) to the case the comment below already names: a
                # dropped LLM connection. Catching `Exception` meant a defect in our own
                # token handling was delivered to the browser as an `error` frame that
                # reads like the model went away, and the stream then closed cleanly —
                # so nothing anywhere recorded that this service was broken. An
                # unexpected exception now propagates, the stream breaks, and the
                # unhandled-exception middleware reports it.
                # Some exceptions (e.g. httpx's *Timeout family) stringify to
                # "" - fall back to the type name so the client never gets an
                # empty detail. Confirmed live: an Ollama cold-load exceeding
                # LLM_TIMEOUT raises httpx.ReadTimeout with str(exc) == "".
                yield _sse("error", {"detail": str(exc) or type(exc).__name__})
                return
        yield _sse("done", {})

    return StreamingResponse(event_source(), media_type="text/event-stream")


@router.get("/documents", summary="List this org's documents")
async def list_documents(
    current_user: User = Depends(get_current_active_user),
) -> Dict[str, Any]:
    """List stored documents.

    ``count``/``keys`` keep their original meaning and S3 source for backward
    compatibility; ``documents`` adds the Postgres registry view. The two can
    differ: blobs ingested before the registry existed have no row.

    ``quota`` reports this org's ingest budget and how much of it is used, so a
    client can see a 409 coming instead of discovering the limit by hitting it.
    A null limit means that dimension is unlimited.
    """
    org_id = _org_id(current_user)
    docs = get_document_store()
    if not docs.available:
        raise HTTPException(status_code=503, detail="Document store unavailable.")
    try:
        keys = await docs.list_documents(prefix=f"{org_id}/")
    except RuntimeError as exc:  # store not configured
        raise HTTPException(status_code=503, detail=str(exc))
    except _StoreTransportError as exc:
        # FS-742: `RuntimeError` alone does not cover it. An unreachable SeaweedFS
        # arrives as a botocore/httpx transport error, neither of which is a
        # RuntimeError, so this route answered 500 on the most ordinary outage there
        # is. `docs.available` cannot help — it is a package-installed check.
        raise _StoreUnreachable(exc) from exc
    return {
        "count": len(keys),
        "keys": keys,
        "documents": await list_for_org(org_id),
        "quota": (await quota_usage(org_id)).as_dict(),
    }


@router.get(
    "/documents/{doc_id}/status",
    response_model=DocumentStatus,
    summary="Ingestion status of a document",
)
async def document_status(
    doc_id: str,
    current_user: User = Depends(get_current_active_user),
) -> DocumentStatus:
    """Poll a queued document until it reaches a terminal status.

    Terminal statuses are ``indexed`` (vectors are queryable), ``skipped``
    (nothing indexable — see ``reason``) and ``failed`` (infrastructure fault
    after retries — see ``error``). Unknown ids 404 regardless of which tenant
    owns them, so this cannot be used to probe another org.
    """
    row = await get_status(_org_id(current_user), _validated_doc_id(doc_id))
    if row is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    return DocumentStatus(**row)


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
            doc_id=_validated_doc_id(doc_id), org_id=_org_id(current_user)
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

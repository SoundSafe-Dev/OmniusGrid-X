"""
RAG Ingestion Orchestrator

Turns an uploaded file into indexed, retrievable knowledge. This is the glue
that wires together the pieces built earlier - it owns the ingestion path end
to end:

    bytes -> document store (SeaweedFS)      # durable blob, returns s3_key
          -> parse (pdf / docx / image / text)
          -> normalize to linear TextBlocks  # flatten structured parser output
          -> chunk (rag_chunker)
          -> embed dense + sparse (rag-inference)
          -> upsert ChunkPoints (Qdrant)

The parsers (``pdf_parser``, ``docx_parser``, ``image_text_extractor``) were
built for the correlation/scenario pipeline and emit *structured* output
(pages/sections/tables). The ``_blocks_from_*`` adapters here flatten that into
the linear, boundary-aware ``TextBlock`` stream the chunker wants - serializing
tables to text so their contents stay retrievable, and preserving page/section
metadata so citations point at the right place.

Graceful degradation matches the rest of the RAG services: the blob is always
stored (that is the source of truth), and indexing is skipped with a clear
``reason`` if the inference or vector service is unavailable, so the document
can be re-indexed later without re-uploading.
"""

from typing import List, Dict, Any, Optional, Sequence
from functools import lru_cache
import uuid

import structlog
from pydantic import BaseModel

from app.core.config import settings
from app.services.document_store import get_document_store, build_document_key
from app.services.inference_client import get_rag_inference
from app.services.vector_store import get_vector_store, ChunkPoint
from app.services.rag_chunker import TextBlock, Chunk, chunk_blocks
from app.services.pdf_parser import parse_pdf_structure
from app.services.docx_parser import parse_docx_structure
from app.services.image_text_extractor import extract_text_from_image

logger = structlog.get_logger()

# Stable namespace so chunk point-ids are deterministic per (doc_id, ordinal):
# re-ingesting a document overwrites its own chunks instead of duplicating them.
_POINT_ID_NS = uuid.UUID("6f1e9a1c-3c2a-4f7d-9b1e-0a2b3c4d5e6f")

_IMAGE_EXTS = {"png", "jpg", "jpeg", "gif", "webp", "bmp", "tiff"}
_TEXT_EXTS = {"txt", "md", "markdown", "csv", "log", "json", "yaml", "yml"}


class IngestionResult(BaseModel):
    """Outcome of ingesting one document. ``stored`` and ``indexed`` are the
    two independent success flags - a doc can be stored but not indexed."""

    doc_id: str
    org_id: str
    filename: str
    s3_key: str
    kind: str  # pdf | docx | image | text | unsupported
    stored: bool
    indexed: bool
    num_blocks: int = 0
    num_chunks: int = 0
    reason: Optional[str] = None


# --------------------------------------------------------------------------- #
# Normalization adapters: structured parser output -> linear TextBlocks.
# Each block is one citable unit (page / section). Tables are serialized so
# their cell contents are embedded and searchable, not dropped.
# --------------------------------------------------------------------------- #

def _rows_to_text(rows: Sequence[Sequence[Any]]) -> str:
    """Serialize a table (list of rows) into pipe-delimited lines."""
    lines: List[str] = []
    for row in rows or []:
        cells = [("" if c is None else str(c)).strip() for c in row]
        if any(cells):
            lines.append(" | ".join(cells))
    return "\n".join(lines)


def _detect_kind(filename: str, content_type: Optional[str]) -> str:
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    ct = (content_type or "").lower()
    if ext == "pdf" or "pdf" in ct:
        return "pdf"
    if ext == "docx" or "wordprocessingml" in ct:
        return "docx"
    if ext in _IMAGE_EXTS or ct.startswith("image/"):
        return "image"
    if ext in _TEXT_EXTS or ct.startswith("text/"):
        return "text"
    return "unsupported"


def _blocks_from_pdf(parsed: Dict[str, Any]) -> List[TextBlock]:
    blocks: List[TextBlock] = []
    for page in parsed.get("pages", []):
        parts: List[str] = []
        headers = page.get("headers") or []
        if headers:
            parts.append(" — ".join(headers))
        text = (page.get("text") or "").strip()
        if text:
            parts.append(text)
        for table in page.get("tables") or []:
            serialized = _rows_to_text(table)
            if serialized:
                parts.append("[TABLE]\n" + serialized)
        body = "\n\n".join(parts).strip()
        if body:
            blocks.append(
                TextBlock(text=body, meta={"source_type": "pdf", "page": page.get("page_num")})
            )
    return blocks


def _blocks_from_docx(parsed: Dict[str, Any]) -> List[TextBlock]:
    blocks: List[TextBlock] = []
    for section in parsed.get("sections", []):
        parts: List[str] = []
        heading = (section.get("heading") or "").strip()
        if heading:
            parts.append(heading)
        paragraphs = section.get("paragraphs") or []
        if paragraphs:
            parts.append("\n".join(paragraphs))
        for table in section.get("tables") or []:
            serialized = _rows_to_text(table)
            if serialized:
                parts.append("[TABLE]\n" + serialized)
        body = "\n\n".join(parts).strip()
        if body:
            blocks.append(
                TextBlock(
                    text=body,
                    meta={
                        "source_type": "docx",
                        "section_id": section.get("section_id"),
                        "heading": heading or None,
                        "level": section.get("level"),
                    },
                )
            )
    return blocks


def _blocks_from_image(parsed: Dict[str, Any]) -> List[TextBlock]:
    text = (parsed.get("extracted_text") or "").strip()
    if not text:
        return []
    return [
        TextBlock(
            text=text,
            meta={
                "source_type": "image",
                "extraction_method": parsed.get("extraction_method"),
                "confidence": parsed.get("confidence"),
            },
        )
    ]


def _blocks_from_text(content: bytes) -> List[TextBlock]:
    text = content.decode("utf-8", errors="replace").strip()
    if not text:
        return []
    return [TextBlock(text=text, meta={"source_type": "text"})]


def _parse_to_blocks(kind: str, content: bytes, filename: str) -> List[TextBlock]:
    """Dispatch to the right parser and normalize to TextBlocks."""
    if kind == "pdf":
        return _blocks_from_pdf(parse_pdf_structure(content, filename))
    if kind == "docx":
        return _blocks_from_docx(parse_docx_structure(content, filename))
    if kind == "image":
        return _blocks_from_image(extract_text_from_image(content, filename))
    if kind == "text":
        return _blocks_from_text(content)
    return []


def _empty_reason(kind: str) -> str:
    if kind == "image":
        return (
            "No text extracted from image - enable VISION_MODEL_ENABLED with a "
            "vision provider to index images."
        )
    return "No extractable text found in document."


# --------------------------------------------------------------------------- #
# Orchestrator
# --------------------------------------------------------------------------- #

class IngestionPipeline:
    """Drives store -> parse -> chunk -> embed -> index for one document."""

    def __init__(self) -> None:
        self.docs = get_document_store()
        self.inference = get_rag_inference()
        self.vectors = get_vector_store()
        self.batch = settings.RAG_EMBED_BATCH

    async def ingest_document(
        self,
        *,
        content: bytes,
        filename: str,
        org_id: str,
        doc_id: Optional[str] = None,
        content_type: Optional[str] = None,
        extra_metadata: Optional[Dict[str, Any]] = None,
    ) -> IngestionResult:
        """Store, parse, chunk, embed and index a document.

        The blob is always persisted first (source of truth). Indexing is
        best-effort and degrades cleanly: an unsupported type, an empty
        extraction, or an unavailable inference/vector service returns a stored
        result with ``indexed=False`` and a ``reason`` rather than raising.
        """
        doc_id = doc_id or str(uuid.uuid4())
        kind = _detect_kind(filename, content_type)
        s3_key = build_document_key(org_id, doc_id, filename)

        if not self.docs.available:
            raise RuntimeError(
                "Document store unavailable (aioboto3 not installed) - cannot ingest."
            )
        await self.docs.ensure_bucket(self.docs.raw_bucket)
        await self.docs.put_document(
            key=s3_key,
            data=content,
            content_type=content_type or "application/octet-stream",
            metadata={"org_id": org_id, "doc_id": doc_id, "filename": filename},
        )

        result = IngestionResult(
            doc_id=doc_id,
            org_id=org_id,
            filename=filename,
            s3_key=s3_key,
            kind=kind,
            stored=True,
            indexed=False,
        )

        if kind == "unsupported":
            result.reason = f"Unsupported file type for RAG indexing: {filename}"
            return result

        try:
            blocks = _parse_to_blocks(kind, content, filename)
        except Exception as exc:  # parsing failed (e.g. optional lib missing)
            logger.warning("rag_ingestion.parse_failed", doc_id=doc_id, error=str(exc))
            result.reason = f"Parse failed: {exc}"
            return result

        result.num_blocks = len(blocks)
        if not blocks:
            result.reason = _empty_reason(kind)
            return result

        chunks = chunk_blocks(
            blocks,
            target_tokens=settings.RAG_CHUNK_TOKENS,
            overlap_tokens=settings.RAG_CHUNK_OVERLAP_TOKENS,
            chars_per_token=settings.RAG_CHARS_PER_TOKEN,
            min_chars=settings.RAG_MIN_CHUNK_CHARS,
        )
        result.num_chunks = len(chunks)
        if not chunks:
            result.reason = "No chunkable text produced."
            return result

        if not self.inference.available or not self.vectors.available:
            result.reason = (
                "Indexing skipped: inference or vector store unavailable. Blob "
                "stored - re-index later once the services are reachable."
            )
            return result

        await self.vectors.ensure_collection()
        # Idempotent re-ingest: drop any prior chunks for this document first.
        await self.vectors.delete_by_doc(doc_id)

        written = 0
        for start in range(0, len(chunks), self.batch):
            batch = chunks[start : start + self.batch]
            embeddings = await self.inference.embed(
                [c.text for c in batch], is_query=False
            )
            points = [
                self._to_point(doc_id, org_id, s3_key, filename, chunk, emb, extra_metadata)
                for chunk, emb in zip(batch, embeddings)
            ]
            written += await self.vectors.upsert_chunks(points)

        result.indexed = True
        result.num_chunks = written
        logger.info(
            "rag_ingestion.indexed",
            doc_id=doc_id,
            kind=kind,
            blocks=result.num_blocks,
            chunks=written,
        )
        return result

    def _to_point(
        self,
        doc_id: str,
        org_id: str,
        s3_key: str,
        filename: str,
        chunk: Chunk,
        embedding: Any,
        extra_metadata: Optional[Dict[str, Any]],
    ) -> ChunkPoint:
        payload: Dict[str, Any] = {
            "doc_id": doc_id,
            "chunk_id": chunk.ordinal,
            "org_id": org_id,
            "s3_key": s3_key,
            "filename": filename,
            "text": chunk.text,
            **chunk.meta,
        }
        if extra_metadata:
            payload.update(extra_metadata)
        point_id = str(uuid.uuid5(_POINT_ID_NS, f"{doc_id}:{chunk.ordinal}"))
        return ChunkPoint(
            id=point_id,
            dense=embedding.dense,
            sparse_indices=embedding.sparse.indices,
            sparse_values=embedding.sparse.values,
            payload=payload,
        )

    async def delete_document(self, *, doc_id: str, org_id: str) -> Dict[str, Any]:
        """Remove a document's vectors and its stored blobs."""
        if self.vectors.available:
            await self.vectors.delete_by_doc(doc_id)
        blobs_deleted = 0
        if self.docs.available:
            prefix = f"{org_id}/{doc_id}/"
            for key in await self.docs.list_documents(prefix=prefix):
                await self.docs.delete_document(key)
                blobs_deleted += 1
        logger.info(
            "rag_ingestion.deleted", doc_id=doc_id, blobs_deleted=blobs_deleted
        )
        return {
            "doc_id": doc_id,
            "vectors_deleted": self.vectors.available,
            "blobs_deleted": blobs_deleted,
        }


@lru_cache()
def get_ingestion_pipeline() -> IngestionPipeline:
    """Cached singleton accessor, mirroring the other RAG services."""
    return IngestionPipeline()

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

The blob is always stored first (that is the source of truth) via
``store_document``. Indexing runs separately via ``index_document``: an
unsupported file type or empty extraction is a terminal outcome and comes
back as a ``skipped`` result with a ``reason``, but an unavailable inference
or vector service is treated as a retryable infrastructure fault and raises,
so a caller (the worker) can requeue instead of permanently marking the
document skipped.
"""

from typing import List, Dict, Any, Optional, Sequence
from functools import lru_cache
import csv
import io
import re
import uuid

import structlog
from pydantic import BaseModel

from app.core.config import settings
from app.services.document_store import (
    get_document_store,
    build_document_key,
    validate_doc_id,
)
from app.services.inference_client import get_rag_inference
from app.services.vector_store import get_vector_store, ChunkPoint
from app.services.rag_chunker import TextBlock, Chunk, chunk_blocks
from app.services.pdf_parser import parse_pdf_structure
from app.services.docx_parser import parse_docx_structure
from app.services.image_text_extractor import extract_text_from_image
from app.services.rag_index_queue import ClaimedDocument, upsert_queued, delete_row

logger = structlog.get_logger()

# Stable namespace so chunk point-ids are deterministic per (doc_id, ordinal):
# re-ingesting a document overwrites its own chunks instead of duplicating them.
_POINT_ID_NS = uuid.UUID("6f1e9a1c-3c2a-4f7d-9b1e-0a2b3c4d5e6f")

_IMAGE_EXTS = {"png", "jpg", "jpeg", "gif", "webp", "bmp", "tiff"}
_MARKDOWN_EXTS = {"md", "markdown"}
_CSV_EXTS = {"csv"}
_TEXT_EXTS = {"txt", "log", "json", "yaml", "yml"}


class IngestionResult(BaseModel):
    """Outcome of ingesting one document. ``stored`` and ``indexed`` are the
    two independent success flags - a doc can be stored but not indexed."""

    doc_id: str
    org_id: str
    filename: str
    s3_key: str
    kind: str  # pdf | docx | markdown | csv | image | text | unsupported
    stored: bool
    indexed: bool
    status: str = "queued"  # queued | indexing | indexed | skipped | failed
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


def _table_rows_to_blocks(
    rows: Sequence[Sequence[Any]],
    base_meta: Dict[str, Any],
    *,
    heading: Optional[str] = None,
) -> List[TextBlock]:
    """Turn a table into one citable block PER ROW so rows never get packed
    together and scrambled at retrieval time (the "who signs vs who approves"
    failure mode). The first non-empty row is treated as the header; each data
    row is rendered as ``col: value | col: value`` so it stays self-describing
    even when retrieved in isolation, and the section ``heading`` is prepended
    for context. A header-only or single-row table falls back to one serialized
    block. Empty/ragged rows are tolerated."""
    clean: List[List[str]] = []
    for row in rows or []:
        cells = [("" if c is None else str(c)).strip() for c in row]
        if any(cells):
            clean.append(cells)
    if not clean:
        return []
    if len(clean) < 2:  # header-only / single row: keep as one block
        body = _rows_to_text(clean)
        meta = dict(base_meta)
        meta["is_table"] = True
        if heading:
            meta["heading"] = heading
        text = f"{heading}\n{body}" if heading else body
        return [TextBlock(text=text, meta=meta)]

    header = clean[0]
    ncols = len(header)
    blocks: List[TextBlock] = []
    for idx, row in enumerate(clean[1:], start=1):
        pairs: List[str] = []
        for j, val in enumerate(row):
            if not val:
                continue
            col = header[j] if j < ncols and header[j] else f"col{j + 1}"
            pairs.append(f"{col}: {val}")
        if not pairs:
            continue
        row_text = " | ".join(pairs)
        if heading:
            row_text = f"[{heading}] {row_text}"
        meta = dict(base_meta)
        meta["is_table"] = True
        meta["row"] = idx
        if heading:
            meta["heading"] = heading
        blocks.append(TextBlock(text=row_text, meta=meta))
    return blocks


# Markdown structure regexes. Headings/tables inside fenced code blocks are
# ignored so ``#`` in a code sample or ``|`` in prose don't create false splits.
_MD_HEADING_RE = re.compile(r"^\s{0,3}(#{1,6})\s+(.*\S)\s*$")
_MD_FENCE_RE = re.compile(r"^\s*(```|~~~)")
_MD_TABLE_ROW_RE = re.compile(r"^\s*\|.*\|\s*$")
_MD_TABLE_SEP_RE = re.compile(r"^\s*\|[\s:\-|]+\|\s*$")


def _split_md_cells(line: str) -> List[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def _blocks_from_markdown(content: bytes) -> List[TextBlock]:
    """Split markdown on headings into one citable block per section (heading in
    ``meta``), and split each GFM table into per-row blocks. Falls back to a
    single block when the document has no headings or tables (today's behavior),
    so unstructured ``.md`` never regresses."""
    text = content.decode("utf-8", errors="replace")
    lines = text.split("\n")
    blocks: List[TextBlock] = []
    current_heading: Optional[str] = None
    buf: List[str] = []
    in_fence = False

    def flush_prose() -> None:
        body = "\n".join(buf).strip()
        if body:
            head = current_heading
            blocks.append(
                TextBlock(
                    text=f"{head}\n{body}" if head else body,
                    meta={"source_type": "markdown", "heading": head},
                )
            )
        buf.clear()

    i = 0
    while i < len(lines):
        line = lines[i]
        if _MD_FENCE_RE.match(line):
            in_fence = not in_fence
            buf.append(line)
            i += 1
            continue
        if not in_fence:
            m = _MD_HEADING_RE.match(line)
            if m:
                flush_prose()
                current_heading = m.group(2).strip()
                i += 1
                continue
            # GFM table: a pipe row immediately followed by a separator row.
            if (
                _MD_TABLE_ROW_RE.match(line)
                and i + 1 < len(lines)
                and _MD_TABLE_SEP_RE.match(lines[i + 1])
            ):
                flush_prose()
                table_rows = [_split_md_cells(line)]
                i += 2  # header + separator
                while i < len(lines) and _MD_TABLE_ROW_RE.match(lines[i]):
                    table_rows.append(_split_md_cells(lines[i]))
                    i += 1
                blocks.extend(
                    _table_rows_to_blocks(
                        table_rows, {"source_type": "markdown"}, heading=current_heading
                    )
                )
                continue
        buf.append(line)
        i += 1
    flush_prose()

    if not blocks:  # no structure found -> single-block fallback
        return _blocks_from_text(content)
    return blocks


def _blocks_from_csv(content: bytes) -> List[TextBlock]:
    """Parse a CSV (proper quoting via the ``csv`` module, BOM-tolerant) into one
    self-describing block per row. Non-tabular or unparseable input falls back to
    plain-text chunking so nothing is lost."""
    text = content.decode("utf-8-sig", errors="replace")
    try:
        rows = [r for r in csv.reader(io.StringIO(text)) if any((c or "").strip() for c in r)]
    except csv.Error:
        return _blocks_from_text(content)
    if len(rows) < 2 or max((len(r) for r in rows), default=0) < 2:
        return _blocks_from_text(content)  # single column / not really tabular
    return _table_rows_to_blocks(rows, {"source_type": "csv"})


def _detect_kind(filename: str, content_type: Optional[str]) -> str:
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    ct = (content_type or "").lower()
    if ext == "pdf" or "pdf" in ct:
        return "pdf"
    if ext == "docx" or "wordprocessingml" in ct:
        return "docx"
    if ext in _IMAGE_EXTS or ct.startswith("image/"):
        return "image"
    # Markdown & CSV before generic text: they carry explicit structure
    # (headings / rows) we split on, rather than treating the file as one blob.
    if ext in _MARKDOWN_EXTS or "markdown" in ct:
        return "markdown"
    if ext in _CSV_EXTS or ct == "text/csv" or ct.endswith("/csv"):
        return "csv"
    if ext in _TEXT_EXTS or ct.startswith("text/"):
        return "text"
    return "unsupported"


def _blocks_from_pdf(parsed: Dict[str, Any]) -> List[TextBlock]:
    blocks: List[TextBlock] = []
    for page in parsed.get("pages", []):
        base = {"source_type": "pdf", "page": page.get("page_num")}
        parts: List[str] = []
        headers = page.get("headers") or []
        if headers:
            parts.append(" — ".join(headers))
        text = (page.get("text") or "").strip()
        if text:
            parts.append(text)
        body = "\n\n".join(parts).strip()
        if body:
            blocks.append(TextBlock(text=body, meta=dict(base)))
        # Tables become per-row blocks so rows stay individually retrievable.
        for table in page.get("tables") or []:
            blocks.extend(_table_rows_to_blocks(table, dict(base)))
    return blocks


def _blocks_from_docx(parsed: Dict[str, Any]) -> List[TextBlock]:
    blocks: List[TextBlock] = []
    for section in parsed.get("sections", []):
        heading = (section.get("heading") or "").strip()
        base = {
            "source_type": "docx",
            "section_id": section.get("section_id"),
            "heading": heading or None,
            "level": section.get("level"),
        }
        parts: List[str] = []
        if heading:
            parts.append(heading)
        paragraphs = section.get("paragraphs") or []
        if paragraphs:
            parts.append("\n".join(paragraphs))
        body = "\n\n".join(p for p in parts if p).strip()
        if body:
            blocks.append(TextBlock(text=body, meta=dict(base)))
        # Tables become per-row blocks (header repeated) so a row like "Shift
        # Supervisor co-signs the Line Release Form" is retrievable on its own.
        for table in section.get("tables") or []:
            blocks.extend(_table_rows_to_blocks(table, dict(base), heading=heading or None))
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
    if kind == "markdown":
        return _blocks_from_markdown(content)
    if kind == "csv":
        return _blocks_from_csv(content)
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

    async def store_document(
        self,
        *,
        content: bytes,
        filename: str,
        org_id: str,
        doc_id: Optional[str] = None,
        content_type: Optional[str] = None,
        uploaded_by: Optional[str] = None,
    ) -> IngestionResult:
        """Persist the blob and queue the document for indexing.

        This is the fast half of ingestion and the only half that runs inside
        the HTTP request: two S3 calls and one row UPSERT. Everything slow
        (parse/chunk/embed/upsert) is left to ``index_document`` on the worker,
        so the request cannot outlive the ingress read timeout.

        Blob first, row second, deliberately: a crash between them orphans a
        blob and the client's retry overwrites the same key, whereas row-first
        would queue a document whose blob does not exist.
        """
        doc_id = validate_doc_id(doc_id) if doc_id else str(uuid.uuid4())
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

        await upsert_queued(
            org_id=org_id,
            doc_id=doc_id,
            uploaded_by=uploaded_by,
            filename=filename,
            s3_key=s3_key,
            kind=kind,
        )
        logger.info("rag_ingestion.queued", doc_id=doc_id, kind=kind)

        return IngestionResult(
            doc_id=doc_id,
            org_id=org_id,
            filename=filename,
            s3_key=s3_key,
            kind=kind,
            stored=True,
            indexed=False,
            status="queued",
        )

    async def index_document(
        self,
        claimed: "ClaimedDocument",
        *,
        extra_metadata: Optional[Dict[str, Any]] = None,
    ) -> IngestionResult:
        """Parse, chunk, embed and index an already-stored document.

        Runs on the worker against a row it has claimed. Returns a result whose
        ``status`` is one of 'indexed' or 'skipped'. Infrastructure faults are
        raised, not returned, so the caller can decide to retry.
        """
        org_id, doc_id = claimed.org_id, claimed.doc_id
        result = IngestionResult(
            doc_id=doc_id,
            org_id=org_id,
            filename=claimed.filename,
            s3_key=claimed.s3_key,
            kind=claimed.kind,
            stored=True,
            indexed=False,
            status="skipped",
        )

        if claimed.kind == "unsupported":
            result.reason = (
                f"Unsupported file type for RAG indexing: {claimed.filename}"
            )
            return result

        # Raises on failure: an unreadable blob is an infra fault, so the
        # worker should retry rather than mark the document permanently skipped.
        content = await self.docs.get_document(claimed.s3_key)

        try:
            blocks = _parse_to_blocks(claimed.kind, content, claimed.filename)
        except Exception as exc:  # parsing failed (e.g. optional lib missing)
            logger.warning(
                "rag_ingestion.parse_failed", doc_id=doc_id, error=str(exc)
            )
            result.reason = f"Parse failed: {exc}"
            return result

        result.num_blocks = len(blocks)
        if not blocks:
            result.reason = _empty_reason(claimed.kind)
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

        # Durability guard: never let one document explode the embed/upsert path.
        cap = settings.RAG_MAX_CHUNKS_PER_DOC
        if len(chunks) > cap:
            logger.warning(
                "rag_ingestion.chunk_cap", doc_id=doc_id, produced=len(chunks), cap=cap
            )
            result.reason = (
                f"Chunk cap reached: indexed the first {cap} of {len(chunks)} "
                f"chunks. Split this document into smaller files."
            )
            chunks = chunks[:cap]

        if not self.inference.available or not self.vectors.available:
            raise RuntimeError(
                "Inference or vector store unavailable - cannot index."
            )

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
                self._to_point(
                    doc_id, org_id, claimed.s3_key, claimed.filename,
                    chunk, emb, extra_metadata,
                )
                for chunk, emb in zip(batch, embeddings)
            ]
            written += await self.vectors.upsert_chunks(points)

        result.indexed = True
        result.status = "indexed"
        result.num_chunks = written
        logger.info(
            "rag_ingestion.indexed",
            doc_id=doc_id,
            kind=claimed.kind,
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
        # Row last: an interrupted delete must never leave queryable vectors
        # behind, so vectors -> blobs -> row is the only safe order.
        row_deleted = await delete_row(org_id, doc_id)
        logger.info(
            "rag_ingestion.deleted", doc_id=doc_id, blobs_deleted=blobs_deleted
        )
        return {
            "doc_id": doc_id,
            "vectors_deleted": self.vectors.available,
            "blobs_deleted": blobs_deleted,
            "row_deleted": row_deleted,
        }


@lru_cache()
def get_ingestion_pipeline() -> IngestionPipeline:
    """Cached singleton accessor, mirroring the other RAG services."""
    return IngestionPipeline()

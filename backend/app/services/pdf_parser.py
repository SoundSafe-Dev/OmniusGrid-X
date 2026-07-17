"""
PDF Parser Service

Extracts structure (pages, headers, tables, text blocks, metadata) from PDF
files so multi-page PDFs can be converted into CorrelationScenarios, mirroring
the multi-tab spreadsheet intake pipeline.

Parsing is deterministic and library-based (pdfplumber for layout/tables,
pypdf for document metadata). Headers are detected via font-size heuristics;
tables via pdfplumber's table extraction. The output structure is consumed by
``document_domain_mapper`` and ``document_scenario_builder``.
"""

from typing import Dict, List, Any, Optional
import io
import re

import structlog

from app.services.shared_key_detector import extract_keys_from_text, extract_keys_from_filename

logger = structlog.get_logger()


# Caps to keep memory/compute bounded while preserving coverage via pagination.
DEFAULT_MAX_PAGES = 100
DEFAULT_MAX_SECTIONS_PER_PAGE = 20
# Heuristic: text whose font size exceeds (body_size * HEADER_SIZE_RATIO) is a header.
HEADER_SIZE_RATIO = 1.15


def estimate_processing_seconds(page_count: int) -> float:
    """Estimate ingestion+analysis time. ~0.5s per page."""
    return round(0.5 * max(page_count, 1), 1)


def _normalize_meta(raw: Any) -> Dict[str, Any]:
    """Convert pypdf DocumentInformation into a plain JSON-safe dict."""
    meta: Dict[str, Any] = {}
    if not raw:
        return meta
    for key in ("title", "author", "subject", "creator", "producer",
                "creation_date", "modification_date"):
        try:
            value = getattr(raw, key, None)
            if value is not None:
                meta[key] = str(value)
        except Exception:
            continue
    return meta


def _extract_headers_from_words(words: List[Dict[str, Any]]) -> List[str]:
    """Detect header-like text on a page using font-size heuristics."""
    if not words:
        return []
    sizes = [w.get("size", 0) for w in words if w.get("size")]
    if not sizes:
        return []
    body_size = sorted(sizes)[len(sizes) // 2]  # median
    threshold = body_size * HEADER_SIZE_RATIO
    headers: List[str] = []
    current: List[str] = []
    for w in words:
        if w.get("size", 0) >= threshold and w.get("text"):
            current.append(w["text"])
        elif current:
            headers.append(" ".join(current))
            current = []
    if current:
        headers.append(" ".join(current))
    # Dedupe while preserving order, cap count
    seen = set()
    result = []
    for h in headers:
        h = h.strip()
        if h and h not in seen:
            seen.add(h)
            result.append(h)
    return result[:DEFAULT_MAX_SECTIONS_PER_PAGE]


def parse_pdf_structure(
    content: bytes,
    filename: str,
    max_pages: int = DEFAULT_MAX_PAGES,
) -> Dict[str, Any]:
    """
    Parse a PDF into a structured representation.

    Returns:
        {
          "type": "report",
          "document_metadata": {...},
          "page_count": int,
          "pages_parsed": int,
          "truncated": bool,
          "pages": [
            {"page_num", "headers", "tables", "text", "shared_keys"}
          ],
          "tables": [...],            # flattened, with page_num
          "shared_keys": [...],
          "estimated_seconds": float,
        }
    """
    try:
        import pdfplumber
    except ImportError as e:  # pragma: no cover - dependency guard
        logger.error("pdfplumber_missing", error=str(e))
        raise RuntimeError("pdfplumber is required for PDF parsing") from e

    document_metadata: Dict[str, Any] = {}
    try:
        # pypdf is PyPDF2's successor (same PdfReader API; PyPDF2 3.0.1 was
        # the final release and carries an unfixed extraction CVE)
        import pypdf
        reader = pypdf.PdfReader(io.BytesIO(content))
        document_metadata = _normalize_meta(reader.metadata)
    except Exception as e:
        logger.warning("pdf_metadata_failed", error=str(e))

    pages: List[Dict[str, Any]] = []
    all_tables: List[Dict[str, Any]] = []
    page_count = 0
    truncated = False

    with pdfplumber.open(io.BytesIO(content)) as pdf:
        page_count = len(pdf.pages)
        for idx, page in enumerate(pdf.pages):
            if idx >= max_pages:
                truncated = True
                break
            try:
                words = page.extract_words(extra_attrs=["size"]) or []
            except Exception:
                words = []
            headers = _extract_headers_from_words(words)
            try:
                text = page.extract_text() or ""
            except Exception:
                text = ""
            tables: List[List[List[Any]]] = []
            try:
                for table in (page.extract_tables() or []):
                    tables.append(table)
                    all_tables.append({"page_num": idx + 1, "rows": table})
            except Exception:
                pass
            page_keys = extract_keys_from_text(text)
            pages.append({
                "page_num": idx + 1,
                "headers": headers,
                "tables": tables,
                "text": text[:20000],  # cap stored text per page
                "shared_keys": page_keys,
            })

    # Aggregate shared keys: filename + metadata + content
    shared_keys: List[str] = []
    shared_keys.extend(extract_keys_from_filename(filename))
    for v in document_metadata.values():
        shared_keys.extend(extract_keys_from_text(str(v)))
    for p in pages:
        shared_keys.extend(p["shared_keys"])
    shared_keys = _dedupe(shared_keys)

    return {
        "type": "report",
        "subtype": "pdf",
        "document_metadata": document_metadata,
        "page_count": page_count,
        "pages_parsed": len(pages),
        "truncated": truncated,
        "pages": pages,
        "tables": all_tables,
        "shared_keys": shared_keys,
        "estimated_seconds": estimate_processing_seconds(page_count),
    }


def _dedupe(items: List[str]) -> List[str]:
    seen = set()
    out = []
    for i in items:
        if i and i not in seen:
            seen.add(i)
            out.append(i)
    return out

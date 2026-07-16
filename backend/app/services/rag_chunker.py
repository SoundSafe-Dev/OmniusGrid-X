"""
RAG Chunker

Splits document text into overlapping, retrieval-sized chunks before embedding.

Design:
- **Boundary-aware.** The caller hands us ``TextBlock``s that already respect a
  document's natural structure - one block per PDF page, per DOCX section, or
  the whole of an image's extracted text. We chunk *within* a block and never
  merge text across blocks, so every chunk maps back to exactly one page/section
  and citations stay clean. Each block's ``meta`` rides along onto its chunks.
- **Token-approximate, dependency-free.** The backend has no BGE tokenizer, so
  sizes are expressed in *approximate* tokens and converted to characters with a
  chars-per-token ratio (see ``settings.RAG_CHARS_PER_TOKEN``). This keeps the
  chunker a pure function with no model/config import - trivially unit-testable.
- **Overlap.** Adjacent chunks share a trailing window so a fact spanning a
  boundary survives in at least one chunk.

The unit of packing is a "segment" - a sentence or a line (table rows are
newline-separated, so each row becomes its own segment). Oversized single
segments are hard-split on the nearest space.
"""

from typing import List, Dict, Any, Optional, Sequence
import re

from pydantic import BaseModel, Field

# Split on sentence terminators followed by whitespace, or on any run of
# newlines. Newline splitting keeps serialized table rows as separate segments.
_SEGMENT_RE = re.compile(r"(?<=[.!?])\s+|\n+")


class TextBlock(BaseModel):
    """A structural unit of a document (one page / section) plus its metadata."""

    text: str
    meta: Dict[str, Any] = Field(default_factory=dict)


class Chunk(BaseModel):
    """A retrieval-sized piece of text with its source block's metadata."""

    text: str
    ordinal: int  # 0-based position across the whole document
    meta: Dict[str, Any] = Field(default_factory=dict)


def _segments(text: str) -> List[str]:
    """Break text into sentence/line segments, dropping empties."""
    return [s.strip() for s in _SEGMENT_RE.split(text) if s and s.strip()]


def _hard_split(segment: str, max_chars: int) -> List[str]:
    """Split an oversized segment on the nearest space under ``max_chars``."""
    out: List[str] = []
    s = segment.strip()
    while len(s) > max_chars:
        cut = s.rfind(" ", 0, max_chars)
        if cut <= 0:  # no space to break on - hard cut
            cut = max_chars
        out.append(s[:cut].strip())
        s = s[cut:].strip()
    if s:
        out.append(s)
    return out


def _overlap_tail(segments: List[str], overlap_chars: int) -> List[str]:
    """Return the trailing segments of a chunk totaling ~``overlap_chars``."""
    if overlap_chars <= 0 or not segments:
        return []
    tail: List[str] = []
    total = 0
    for seg in reversed(segments):
        tail.insert(0, seg)
        total += len(seg) + 1
        if total >= overlap_chars:
            break
    return tail


def _chunk_one_block(text: str, max_chars: int, overlap_chars: int) -> List[str]:
    """Pack a single block's segments into overlapping ~``max_chars`` chunks."""
    # Expand any oversized segment so no single unit exceeds the budget.
    units: List[str] = []
    for seg in _segments(text):
        if len(seg) > max_chars:
            units.extend(_hard_split(seg, max_chars))
        else:
            units.append(seg)

    chunks: List[str] = []
    current: List[str] = []
    current_len = 0
    for unit in units:
        added = len(unit) + (1 if current else 0)
        if current and current_len + added > max_chars:
            chunks.append(" ".join(current).strip())
            current = _overlap_tail(current, overlap_chars)
            current_len = sum(len(u) + 1 for u in current)
            added = len(unit) + (1 if current else 0)
        current.append(unit)
        current_len += added
    if current:
        chunks.append(" ".join(current).strip())
    return [c for c in chunks if c]


def chunk_blocks(
    blocks: Sequence[TextBlock],
    *,
    target_tokens: int = 512,
    overlap_tokens: int = 64,
    chars_per_token: float = 4.0,
    min_chars: int = 40,
) -> List[Chunk]:
    """Chunk structural blocks into overlapping, retrieval-sized ``Chunk``s.

    Chunks never cross a block boundary, so each carries exactly one block's
    ``meta`` (page / section). A trailing chunk shorter than ``min_chars`` is
    merged back into the previous chunk of the *same* block to avoid slivers.
    Ordinals are assigned sequentially across the whole document.
    """
    max_chars = max(int(target_tokens * chars_per_token), 1)
    overlap_chars = max(int(overlap_tokens * chars_per_token), 0)
    # Overlap must be smaller than the chunk or packing cannot make progress.
    overlap_chars = min(overlap_chars, max_chars - 1) if max_chars > 1 else 0

    collected: List[tuple] = []  # (text, meta)
    for block in blocks:
        text = (block.text or "").strip()
        if not text:
            continue
        pieces = _chunk_one_block(text, max_chars, overlap_chars)
        if len(pieces) > 1 and len(pieces[-1]) < min_chars:
            pieces[-2] = f"{pieces[-2]} {pieces[-1]}".strip()
            pieces.pop()
        for piece in pieces:
            collected.append((piece, block.meta))

    return [
        Chunk(text=text, ordinal=i, meta=meta)
        for i, (text, meta) in enumerate(collected)
    ]


def chunk_text(
    text: str, meta: Optional[Dict[str, Any]] = None, **kwargs: Any
) -> List[Chunk]:
    """Convenience: chunk a single flat string (one implicit block)."""
    return chunk_blocks([TextBlock(text=text, meta=meta or {})], **kwargs)

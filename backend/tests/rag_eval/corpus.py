"""
Corpus registry — the single source of truth for *which documents* the RAG eval
suite runs against, and in *which formats*.

Historically the suite funneled ONE logical document (SOP-QA-014) through five
formats. It now supports a set of documents, each rendered in the same five
formats, so the tests parametrize over ``(document x format x query)`` and a
dedicated corpus-discrimination phase can index *all* documents at once and
assert that retrieval cites the RIGHT document.

Adding a document is a self-contained operation:
  1. author its source model + regenerate its 5 formats:  make_corpus.py
     (writes backend/tests/docs/<BASENAME>.{md,txt,csv,docx,pdf})
  2. register it below (a ``Doc`` entry)
  3. add its query specs + gold markers in queries.py under the same ``id``

Everything stays in-repo and stdlib-only for the *runner*, so anyone can clone
and run the suite; the generator's deps (reportlab / python-docx) are already
backend dependencies and are only needed to *regenerate* the committed files.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple

DOCS_DIR = Path(__file__).resolve().parent.parent / "docs"

# format -> MIME type sent on ingest
CTYPES: Dict[str, str] = {
    "pdf":  "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "md":   "text/markdown",
    "txt":  "text/plain",
    "csv":  "text/csv",
}

ALL_FORMATS: Tuple[str, ...] = ("pdf", "docx", "md", "txt", "csv")


@dataclass(frozen=True)
class Doc:
    """A logical document available as several on-disk renderings.

    ``id`` is the stable slug used everywhere (query specs, report matrix,
    discrimination assertions); ``basename`` is the on-disk file stem shared by
    all format renderings.
    """
    id: str
    basename: str
    title: str
    formats: Tuple[str, ...] = ALL_FORMATS

    def filename(self, fmt: str) -> str:
        return f"{self.basename}.{fmt}"

    def ctype(self, fmt: str) -> str:
        return CTYPES[fmt]

    def path(self, fmt: str) -> Path:
        return DOCS_DIR / self.filename(fmt)

    def file(self, fmt: str) -> Tuple[str, str]:
        """(filename, content-type) — mirrors the old FORMATS tuple shape."""
        return self.filename(fmt), self.ctype(fmt)


DOCS: List[Doc] = [
    Doc(
        id="sop-qa-014",
        basename="SOP-QA-014_Allergen_Control_Sanitation",
        title="Allergen Control and Sanitation Procedure",
    ),
    Doc(
        id="sop-wh-021",
        basename="SOP-WH-021_Cold_Chain_Temperature_Control",
        title=("Refrigerated and Frozen Storage Temperature Control and "
               "Cold-Chain Verification"),
    ),
]

DOC_BY_ID: Dict[str, Doc] = {d.id: d for d in DOCS}
PRIMARY: Doc = DOCS[0]


def doc_format_pairs() -> List[Tuple[str, str]]:
    """Every ``(doc_id, format)`` the matrix can ingest — the parametrization
    axis for the per-format isolation tests."""
    return [(d.id, f) for d in DOCS for f in d.formats]


_BY_BASENAME = {d.basename: d.id for d in DOCS}


def doc_id_for_citation(citation: Dict) -> str:
    """Map an API citation back to a corpus ``doc_id`` via its filename stem
    (robust to the per-run ingest id). '' if it matches no known document.
    Shared by the discrimination and tenant-isolation tests."""
    stem = (citation.get("filename") or "").rsplit(".", 1)[0]
    return _BY_BASENAME.get(stem, "")


# --------------------------------------------------------------------------- #
# Back-compat single-doc view (kept so the standalone matrix runner and any
# ``from client import FORMATS`` callers keep working without a rewrite). New
# code should use DOCS / DOC_BY_ID / doc_format_pairs above.
# --------------------------------------------------------------------------- #
FORMATS: Dict[str, Tuple[str, str]] = {
    f: PRIMARY.file(f) for f in PRIMARY.formats
}
BASENAME = PRIMARY.basename

"""Operational (ERP) context for the RAG generation prompt.

The second retrieval leg. ``rag_retriever`` answers a compliance question from the
document corpus; this module reads the *operational* record behind that question -
the open work orders, the certifications, the purchase orders - and hands the
generator a compact block of them so the answer can qualify written policy with
what is actually happening ("the CBA requires X; three of your open work orders
show Y").

WHY THIS IS NOT A SECOND CORPUS. The obvious alternative is to push ERP rows
through ``rag_ingestion`` into Qdrant and let hybrid search find them. That fights
the pipeline's design in four separate ways: the blobs would not exist (SeaweedFS
keys assume a real file), the citations would presume a document that cannot be
opened, every ERP sync would need a re-index, and ERP chunks would compete for the
five rerank slots that belong to policy text. So ERP enters as a parallel leg
instead: read live, rendered unnumbered, never cited. The document corpus stays
exactly as htreinen built it.

TENANCY. Rows are filtered on ``organization_id`` here AND the session is bound to
the tenant GUC by ``get_tenant_db``, so Postgres RLS is a second, independent
gate. That matches the Qdrant leg, which filters on the same ``org_id`` from the
same JWT.

FILTERING HAPPENS IN PYTHON, NOT SQL. ``ERPEntity.entity_data`` is ``JSON``, not
``JSONB`` (db/models.py). An ILIKE against it needs a dialect-specific cast, and
the SQLite dev path would then diverge from Postgres - a filter that silently
matches differently per environment is worse than no filter. Reading a bounded
window of recent rows and filtering them in Python is dialect-free, and is what
``platform_correlation.erp_provider`` already does for the correlation lane.
"""

from typing import Any, Dict, List, Optional, Sequence, Set, Tuple
import re

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import ERPEntity
from app.services.platform_correlation import flatten_erp_entity

logger = structlog.get_logger()


# Query intent -> ERP entity types worth reading. A compliance question about
# lockout/tagout wants work orders; one about certification wants employees.
# Matched case-insensitively against the raw question. Order is irrelevant - every
# matching group contributes, so "overtime on open work orders" reads both.
#
# Deliberately keyword-based rather than embedded: this runs on the hot path of
# every query, and an extra embedding round-trip to rank ~300 short rows would cost
# more latency than the precision is worth. If routing proves too blunt, the upgrade
# is to embed the ROW TEXT at sync time, not to embed the question here.
_ENTITY_ROUTES: List[Tuple[re.Pattern, Tuple[str, ...]]] = [
    (
        re.compile(
            r"lockout|loto|tagout|work\s*order|maintenance|preventive|\bpm\b|"
            r"repair|downtime|breakdown|equipment|machine|asset",
            re.I,
        ),
        ("WorkOrder", "ManufacturingOrder"),
    ),
    (
        re.compile(
            r"training|certif|qualif|licen[cs]|employee|worker|staff|personnel|"
            r"overtime|shift|steward|union|grievance|seniority|hours",
            re.I,
        ),
        ("Employee",),
    ),
    (
        re.compile(
            r"supplier|vendor|purchas|procure|\bpo\b|contract|invoice|payment|audit",
            re.I,
        ),
        ("PurchaseOrder", "Vendor", "Invoice", "Payment"),
    ),
    (
        re.compile(r"shipment|ship|carrier|cold\s*chain|transport|deliver|freight", re.I),
        ("Shipment",),
    ),
    (
        re.compile(r"inventor|stock|material|part\b|parts\b|batch|lot\b|storage|warehouse", re.I),
        ("Inventory", "Product"),
    ),
]

# Words too common to say anything about which rows matter. Dropping them stops
# "what does the policy require for a shift change" from matching every row that
# happens to contain the word "for".
_STOPWORDS: Set[str] = {
    "the", "and", "for", "are", "our", "with", "what", "when", "which", "does",
    "who", "how", "any", "all", "from", "into", "have", "has", "was", "were",
    "this", "that", "these", "those", "must", "should", "shall", "can", "may",
    "policy", "policies", "rule", "rules", "require", "required", "requires",
    "requirement", "requirements", "compliance", "compliant", "need", "needs",
    "about", "there", "their", "them", "then", "than", "you", "your", "not",
}

# entity_data keys that carry no information for a compliance reader. Dropping
# them keeps the per-row rendering inside the char budget.
_NOISE_KEYS: Set[str] = {
    "id", "guid", "uuid", "etag", "odata_etag", "created_by_id", "modified_by_id",
    "row_version", "checksum", "hash", "internal_id", "external_id",
}

_MAX_FIELDS_PER_ROW = 12


def _query_tokens(query: str) -> Set[str]:
    """Content words from the question, lowercased, stopwords and stubs removed."""
    return {
        t for t in re.findall(r"[a-z0-9][a-z0-9_\-]{2,}", query.lower())
        if t not in _STOPWORDS
    }


def _routed_entity_types(query: str) -> Optional[Set[str]]:
    """Entity types this question is about, or None for 'no opinion'.

    None is NOT the empty set: an unrouted question should still see the most
    recent operational records rather than none at all, since the point of the leg
    is to give the generator situational awareness it would otherwise lack.
    """
    types: Set[str] = set()
    for pattern, entity_types in _ENTITY_ROUTES:
        if pattern.search(query):
            types.update(entity_types)
    return types or None


def _render_row(record: Dict[str, Any]) -> str:
    """One flattened ERP record -> one self-describing line.

    ``EntityType | entity_id | key: value | key: value`` - the same
    ``col: value | col: value`` shape ``rag_ingestion._table_rows_to_blocks``
    already produces for table rows, so the generator is reading a format the rest
    of the corpus has trained it on rather than a novel one.
    """
    head = f"{record.get('entity_type') or 'Record'} | {record.get('entity_id') or '?'}"
    pairs: List[str] = []
    for key, value in record.items():
        if key in ("entity_type", "entity_id") or key in _NOISE_KEYS:
            continue
        if value is None or value == "":
            continue
        pairs.append(f"{key}: {value}")
        if len(pairs) >= _MAX_FIELDS_PER_ROW:
            break
    return " | ".join([head, *pairs])


def _score(record: Dict[str, Any], tokens: Set[str]) -> int:
    """How many question tokens appear anywhere in this record's values."""
    if not tokens:
        return 0
    haystack = " ".join(str(v) for v in record.values() if v is not None).lower()
    return sum(1 for t in tokens if t in haystack)


async def build_erp_context(
    db: AsyncSession,
    org_id: str,
    query: str,
    *,
    max_rows: Optional[int] = None,
    max_chars: Optional[int] = None,
) -> Tuple[str, Dict[str, Any]]:
    """Read this org's operational records and render the ones this question needs.

    Returns ``(block, meta)``. ``block`` is "" when there is nothing relevant, and
    the caller must treat that as normal - most deployments have no ERP integration
    at all. ``meta`` carries the counts that go into the structlog record: it is the
    only trace that this leg contributed to an answer, since nothing about it
    reaches the API response.
    """
    max_rows = max_rows or settings.RAG_ERP_CONTEXT_ROWS
    max_chars = max_chars or settings.RAG_ERP_CONTEXT_CHARS
    empty: Dict[str, Any] = {"rows": 0, "entity_types": [], "chars": 0, "candidates": 0}

    stmt = (
        select(ERPEntity)
        .where(
            ERPEntity.organization_id == org_id,
            ERPEntity.is_active == True,  # noqa: E712 - SQL boolean, not Python
        )
        .order_by(ERPEntity.updated_at.desc())
        .limit(settings.RAG_ERP_CANDIDATE_ROWS)
    )
    rows: Sequence[ERPEntity] = (await db.execute(stmt)).scalars().all()
    if not rows:
        return "", empty

    wanted = _routed_entity_types(query)
    tokens = _query_tokens(query)

    # Rank, don't filter. A routed type or a token hit promotes a row; nothing
    # excludes one outright, because the recency ordering already carries real
    # signal and an over-eager filter would silently empty the block. Ties fall
    # back to the DB order, which is most-recent-first.
    ranked: List[Tuple[int, int, Dict[str, Any]]] = []
    for i, entity in enumerate(rows):
        record = flatten_erp_entity(entity)
        relevance = _score(record, tokens) * 2
        if wanted and entity.entity_type in wanted:
            relevance += 3
        ranked.append((-relevance, i, record))
    ranked.sort(key=lambda t: (t[0], t[1]))

    lines: List[str] = []
    entity_types: List[str] = []
    used = 0
    for _, _, record in ranked:
        if len(lines) >= max_rows:
            break
        line = _render_row(record)
        if used + len(line) + 1 > max_chars:
            break  # budget spent; keep what fits rather than truncating a row
        lines.append(line)
        used += len(line) + 1
        etype = record.get("entity_type")
        if etype and etype not in entity_types:
            entity_types.append(etype)

    if not lines:
        return "", {**empty, "candidates": len(rows)}

    return "\n".join(lines), {
        "rows": len(lines),
        "entity_types": entity_types,
        "chars": used,
        "candidates": len(rows),
    }

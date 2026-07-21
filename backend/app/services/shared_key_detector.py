"""
Shared Key Detector

Extracts and correlates "shared keys" (the unifying tokens that link records
across tabs, pages, documents, and files) from filenames, document metadata,
and content. Shared keys drive cross-file CorrelationScenario linkage, the same
way ``asset_id``/``date`` link spreadsheet tabs.

All key categories are treated as equally important. Keys are normalized to a
canonical string so the same physical key extracted from different sources
(filename vs. content) collides and forms a correlation group.
"""

from typing import Dict, List, Any, Optional, Iterable
import re
import os


# Ordered pattern library. Each entry: (category, compiled regex).
# Patterns are intentionally specific to avoid noisy matches.
_KEY_PATTERNS = [
    ("timestamp_iso", re.compile(r"\b\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2})?\b")),
    ("date_iso", re.compile(r"\b\d{4}-\d{2}-\d{2}\b")),
    ("date_us", re.compile(r"\b\d{1,2}/\d{1,2}/\d{2,4}\b")),
    ("order_po", re.compile(r"\bPO[-_ ]?\d{3,}\b", re.IGNORECASE)),
    ("order_so", re.compile(r"\bSO[-_ ]?\d{3,}\b", re.IGNORECASE)),
    ("invoice", re.compile(r"\bINV[-_ ]?\d{3,}\b", re.IGNORECASE)),
    ("trailer", re.compile(r"\bTR[-_ ]?\d{3,}\b", re.IGNORECASE)),
    ("work_order", re.compile(r"\bWO[-_ ]?\d{3,}\b", re.IGNORECASE)),
    ("asset_id", re.compile(r"\b(?:ASSET|EQ|EQUIP|MCH|MACHINE)[-_ ]?\d{2,}\b", re.IGNORECASE)),
    ("dock_door", re.compile(r"\bDOCK[-_ ]?\d{1,3}\b", re.IGNORECASE)),
    ("zone_code", re.compile(r"\b(?:ZONE|BIN|SLOT)[-_ ]?[A-Z]?\d{1,4}\b", re.IGNORECASE)),
    ("lot_batch", re.compile(r"\b(?:LOT|BATCH)[-_ ]?[A-Z0-9]{3,}\b", re.IGNORECASE)),
    ("shipment", re.compile(r"\b(?:SHIP|SHP|TRACK)[-_ ]?[A-Z0-9]{4,}\b", re.IGNORECASE)),
]

# Field-name hints used when scanning structured key/value content (tables,
# row dicts) so we also pick up values under columns like "asset_id".
_KEY_FIELD_HINTS = [
    "asset_id", "asset", "equipment_id", "machine_id", "trailer_id", "trailer",
    "order_id", "order_number", "po_number", "purchase_order", "so_number",
    "invoice", "invoice_number", "work_order", "wo_number", "lot", "batch",
    "lot_number", "batch_id", "dock", "dock_door", "zone", "bin", "slot",
    "date", "timestamp", "shipment_id", "tracking_number",
]


def normalize_key(value: Any) -> str:
    """Canonicalize a key token: uppercase, collapse separators."""
    if value is None:
        return ""
    text = str(value).strip().upper()
    # Collapse separators around a hyphen: "PO - 123" -> "PO-123"
    text = re.sub(r"[\s_-]+", "-", text)
    text = text.strip("-")
    return text


def _dedupe(items: Iterable[str]) -> List[str]:
    seen = set()
    out: List[str] = []
    for i in items:
        if i and i not in seen:
            seen.add(i)
            out.append(i)
    return out


def extract_keys_from_text(text: str, max_keys: int = 200) -> List[str]:
    """Scan free text for known key patterns."""
    if not text:
        return []
    found: List[str] = []
    for _category, pattern in _KEY_PATTERNS:
        for match in pattern.findall(str(text)):
            found.append(normalize_key(match))
            if len(found) >= max_keys:
                return _dedupe(found)
    return _dedupe(found)


def extract_keys_from_filename(filename: Optional[str]) -> List[str]:
    """Extract keys from a filename (extension stripped)."""
    if not filename:
        return []
    base = os.path.basename(str(filename))
    stem = re.sub(r"\.[A-Za-z0-9]+$", "", base)
    # Replace separators with spaces so patterns can match.
    spaced = re.sub(r"[_\-]+", " ", stem)
    keys = extract_keys_from_text(stem) + extract_keys_from_text(spaced)
    return _dedupe(keys)


def extract_keys_from_metadata(metadata: Optional[Dict[str, Any]]) -> List[str]:
    """Extract keys from document metadata values."""
    if not metadata:
        return []
    keys: List[str] = []
    for value in metadata.values():
        keys.extend(extract_keys_from_text(str(value)))
    return _dedupe(keys)


def extract_keys_from_records(records: List[Dict[str, Any]],
                              max_records: int = 500) -> List[str]:
    """Extract keys from structured rows by inspecting hint columns and values."""
    if not records:
        return []
    keys: List[str] = []
    for record in records[:max_records]:
        for col, val in record.items():
            col_l = str(col).lower()
            if any(hint in col_l for hint in _KEY_FIELD_HINTS) and val is not None:
                keys.append(normalize_key(val))
            else:
                keys.extend(extract_keys_from_text(str(val)))
    return _dedupe(keys)


def detect_shared_keys(data_sources: List[Dict[str, Any]]) -> Dict[str, List[str]]:
    """
    Find keys shared across multiple data sources.

    Args:
        data_sources: list of {"source_id": str, "keys": [str, ...]}

    Returns:
        {key: [source_id, ...]} for keys present in >= 2 sources.
    """
    key_to_sources: Dict[str, List[str]] = {}
    for source in data_sources:
        sid = str(source.get("source_id"))
        for key in set(source.get("keys") or []):
            key_to_sources.setdefault(key, []).append(sid)
    return {k: v for k, v in key_to_sources.items() if len(set(v)) >= 2}


def auto_detect_correlation_groups(
    data_sources: List[Dict[str, Any]],
    manual_keys: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """
    Group data sources by shared keys into correlation groups.

    Args:
        data_sources: list of {"source_id", "keys", "domains"(optional)}
        manual_keys: user-specified keys; when provided they are treated as
            authoritative and merged with auto-detected keys (normalized).

    Returns:
        [{"shared_keys": [...], "source_ids": [...], "domains": [...]}]
        One group per connected component of sources linked by shared keys.
    """
    normalized_manual = {normalize_key(k) for k in (manual_keys or []) if k}

    # Augment each source's keys with manual keys that appear in its content.
    shared = detect_shared_keys(data_sources)
    if normalized_manual:
        # Manual keys force grouping even if auto-detection missed them.
        for key in normalized_manual:
            members = [
                str(s.get("source_id"))
                for s in data_sources
                if key in {normalize_key(k) for k in (s.get("keys") or [])}
            ]
            if len(set(members)) >= 2:
                shared[key] = members

    if not shared:
        return []

    # Union-Find over source ids linked by any shared key.
    parent: Dict[str, str] = {}

    def find(x: str) -> str:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        parent[find(a)] = find(b)

    key_by_source: Dict[str, set] = {}
    for key, sources in shared.items():
        uniq = list(dict.fromkeys(sources))
        for s in uniq:
            key_by_source.setdefault(s, set()).add(key)
        for s in uniq[1:]:
            union(uniq[0], s)

    domains_by_source = {
        str(s.get("source_id")): list(s.get("domains") or []) for s in data_sources
    }

    groups: Dict[str, Dict[str, Any]] = {}
    for source in key_by_source:
        root = find(source)
        g = groups.setdefault(root, {"shared_keys": set(), "source_ids": set(), "domains": set()})
        g["shared_keys"].update(key_by_source.get(source, set()))
        g["source_ids"].add(source)
        for d in domains_by_source.get(source, []):
            g["domains"].add(d)

    result = []
    for g in groups.values():
        if len(g["source_ids"]) >= 2:
            result.append({
                "shared_keys": sorted(g["shared_keys"]),
                "source_ids": sorted(g["source_ids"]),
                "domains": sorted(g["domains"]),
            })
    return result

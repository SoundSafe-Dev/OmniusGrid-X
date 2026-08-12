"""Human-readable labels for operator-facing correlation text.

Raw identifiers remain in lineage and machine-readable API fields.  This
module is only for language shown in question suggestions and AI prose.
"""

from __future__ import annotations

import re
from pathlib import PurePath


def humanize_label(value: object) -> str:
    """Turn a file, tab, column, or unit-style name into plain display text."""
    text = str(value or "").strip()
    if not text:
        return ""

    # Files should read as titles, not implementation details.
    suffix = PurePath(text).suffix.lower()
    if suffix in {".csv", ".tsv", ".xlsx", ".xls", ".xlsm", ".xlsb", ".json", ".parquet"}:
        text = text[: -len(suffix)]

    text = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", text)
    text = re.sub(r"[_/]+", " ", text)
    text = re.sub(r"(?i)\bFY\s*(\d{4})\b", r"Fiscal year \1", text)
    text = re.sub(r"(?i)\bLINE[-\s]*(\d+)\b", r"Line \1", text)
    text = re.sub(r"\s+", " ", text).strip(" -–—")

    # Keep intentionally uppercase abbreviations (OEE, KPI, ERP) intact, but
    # make ordinary implementation names read like normal English.
    words = []
    for word in text.split(" "):
        if re.fullmatch(r"[A-Z]{2,6}", word) or re.fullmatch(r"\d+(?:\.\d+)?", word):
            words.append(word)
        elif re.fullmatch(r"[A-Z]{2,6}-\d+(?:-\d+)*", word):
            words.append(word)
        else:
            words.append(word.capitalize())
    return " ".join(words)

"""Shared aware-UTC datetime helpers.

The FS-96/97 sweep moved runtime code onto timezone-aware UTC, but values read
back from the database can still arrive naive — SQLite has no timezone type, and
rows written before the sweep are naive on Postgres too. Mixing the two raises
TypeError on every comparison or subtraction, which in worker code surfaces as a
silently dropped message rather than an error anyone sees.

Import these rather than re-deriving the coercion per module.
"""
from __future__ import annotations

from datetime import datetime, timezone


def utcnow() -> datetime:
    """Current time as an aware UTC datetime."""
    return datetime.now(timezone.utc)


def aware_utc(dt: datetime) -> datetime:
    """Coerce a possibly-naive datetime to aware UTC (naive is assumed UTC)."""
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)

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


def canonical_timezone_key(value: str) -> str | None:
    """The canonical IANA key for `value`, or None if it is not a usable timezone.

    THREE MODULES HAND-ROLLED THIS AND ALL THREE LEAKED THE SAME EXCEPTION.
    `zoneinfo.ZoneInfoNotFoundError` is what an *unknown* zone raises, and every one of
    them caught it — but `ZoneInfo` raises a plain **ValueError** for two other shapes:

        ZoneInfo("")               ValueError: keys must be normalized relative paths
        ZoneInfo("../etc/passwd")  ValueError: keys must refer to subdirectories

    So a caller sending an empty timezone, or a traversal-shaped one, got a **500** while
    every other bad value got a clean 400. `POST /compliance/reports/schedules` was one of
    eight operations the contract gate found answering a bare `internal server error`, and
    `exports.py` and `maintenance_windows.py` carried the same handler shape.

    Returning None rather than raising is deliberate: the three call sites live in
    different layers and each owns its own error vocabulary — an HTTPException with a 400,
    a `MaintenanceWindowValidationError`, a scheduler that must not raise into a loop.
    Imposing one exception type here would make two of them translate it back.

    The traversal shape is worth naming even though `ZoneInfo` refuses it: a timezone name
    is caller-supplied and reaches a filesystem lookup, so "the library said no" is the
    right outcome — answering 500 tells the caller their input caused a server fault, which
    is both wrong and the shape somebody probes further.
    """
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

    name = (value or "").strip()
    if not name:
        return None
    try:
        return ZoneInfo(name).key
    except (ZoneInfoNotFoundError, ValueError, OSError):
        # THREE exception types, and the third was found by this function's own test.
        # `ZoneInfo` resolves a name to a FILE, so the failure modes are the filesystem's:
        # ZoneInfoNotFoundError for a name that is not a zone, ValueError for a name that is
        # not a usable key, and **OSError** for one the filesystem itself refuses —
        # `ZoneInfo("x" * 300)` raises `[Errno 63] File name too long`. The first draft
        # caught the first two, having reasoned about them; the long-name case was in the
        # test list because it is the shape a fuzzer sends, not because it was predicted.
        # Anything that cannot be constructed is not a timezone, which is the whole
        # question being asked here.
        return None

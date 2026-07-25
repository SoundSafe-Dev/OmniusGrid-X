"""Dialect-portable time bucketing for dashboard/trend aggregation.

TimescaleDB has ``time_bucket``; SQLite (the offline demo path) has nothing
equivalent. ``app/api/telemetry.py`` already solved this once by branching on
the dialect and doing a pure-Python rollup otherwise — this generalises that
pattern so trend endpoints don't each reinvent it (and so the SQLite demo keeps
working; see the FS-204 dialect-portability item).

Buckets are aligned to the epoch — ``floor(ts / seconds) * seconds`` — which is
what ``time_bucket`` does for fixed intervals, so both paths agree.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable

from sqlalchemy import func, text

# Kept small and explicit: an arbitrary interval string would be a SQL-injection
# seam, since Postgres INTERVAL literals can't be bound as parameters.
BUCKET_SECONDS: dict[str, int] = {
    "5min": 300,
    "15min": 900,
    "1hour": 3600,
    "6hour": 21600,
    "1day": 86400,
}

DEFAULT_BUCKET = "1hour"


def resolve_bucket(bucket: str | None) -> tuple[str, int]:
    """Validate a bucket name and return ``(name, seconds)``."""
    name = bucket or DEFAULT_BUCKET
    if name not in BUCKET_SECONDS:
        raise ValueError(
            f"unsupported bucket '{name}'; expected one of {sorted(BUCKET_SECONDS)}"
        )
    return name, BUCKET_SECONDS[name]


def is_postgres(session) -> bool:
    """True when the bound dialect supports TimescaleDB's time_bucket."""
    return session.bind.dialect.name == "postgresql"


def pg_bucket(column, seconds: int):
    """A TimescaleDB ``time_bucket`` expression over ``column``.

    ``seconds`` comes from BUCKET_SECONDS (never user text), so interpolating it
    into the INTERVAL literal is safe — INTERVAL cannot take a bind parameter.
    """
    return func.time_bucket(text(f"INTERVAL '{int(seconds)} seconds'"), column)


def bucket_start(ts: datetime, seconds: int) -> datetime:
    """Floor a timestamp to its epoch-aligned bucket start (UTC)."""
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    epoch = int(ts.timestamp())
    return datetime.fromtimestamp(epoch - (epoch % seconds), tz=timezone.utc)


def empty_series(start: datetime, end: datetime, seconds: int) -> list[datetime]:
    """Every bucket start in [start, end], so a sparse series still plots.

    Without this a chart with no data in a window renders as a gap rather than a
    flat line, and the x-axis silently changes shape between refreshes.
    """
    out: list[datetime] = []
    cursor = bucket_start(start, seconds)
    last = bucket_start(end, seconds)
    while cursor <= last:
        out.append(cursor)
        cursor = datetime.fromtimestamp(
            cursor.timestamp() + seconds, tz=timezone.utc
        )
    return out


def fill_series(
    rows: dict[datetime, dict],
    start: datetime,
    end: datetime,
    seconds: int,
    default: dict | None = None,
) -> list[dict]:
    """Densify bucketed rows across the whole window, oldest → newest."""
    filled = []
    for ts in empty_series(start, end, seconds):
        row = rows.get(ts)
        entry = {"timestamp": ts.isoformat()}
        entry.update(dict(default or {}))
        if row:
            entry.update(row)
        filled.append(entry)
    return filled

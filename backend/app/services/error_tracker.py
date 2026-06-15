"""Error tracking core — fingerprint, scrub, aggregate, flush.

Self-contained unhandled-exception aggregation for the Error Triage feature.
Unhandled exceptions are fingerprinted (so identical bugs collapse into one
row), scrubbed of PII, accumulated in-process, and periodically flushed to the
``error_events`` / ``error_event_buckets`` tables.

Design guarantees:
  * The request path is never blocked or broken by tracking — ``record`` only
    touches an in-memory dict under a lock and never awaits I/O.
  * The aggregator is bounded; under a flood, new fingerprints are dropped
    (counted) rather than growing memory without limit. Known fingerprints keep
    counting cheaply.
  * A dead database degrades gracefully: the flush loop logs, counts the
    failure, re-queues the batch, and retries next cycle. It never crashes.
  * Only metadata is persisted — exception type, route TEMPLATE, scrubbed
    message/traceback samples, counts. No request bodies, headers, query
    params, or user identity (GDPR-safe by construction).

Configuration is read from environment variables here (not app.core.config),
matching the convention used by app/middleware/profiling.py.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import re
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

import structlog
from prometheus_client import Counter, Gauge
from sqlalchemy import text

# Imported as a module (not ``from ... import AsyncSessionLocal``) so the flush
# loop always uses the current session maker. The test suite rebinds
# ``app.db.database.AsyncSessionLocal`` to an ephemeral container; referencing it
# through the module means the background flush is exercised against that DB too.
from app.db import database as _db

logger = structlog.get_logger()


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


# --- Configuration (env-driven; see module docstring) -----------------------
# Disabled by default, matching the PROFILING_ENABLED precedent: nothing changes
# for any deployment until the flag is explicitly flipped on.
ERROR_TRACKING_ENABLED: bool = _env_bool("ERROR_TRACKING_ENABLED", False)
FLUSH_INTERVAL_SECONDS: float = _env_float("ERROR_TRACKING_FLUSH_INTERVAL_SECONDS", 30.0)
MAX_PENDING_FINGERPRINTS: int = _env_int("ERROR_TRACKING_MAX_PENDING_FINGERPRINTS", 500)
TRACEBACK_MAX_BYTES: int = _env_int("ERROR_TRACKING_TRACEBACK_MAX_BYTES", 8192)
BUCKET_RETENTION_DAYS: int = _env_int("ERROR_TRACKING_BUCKET_RETENTION_DAYS", 90)
MESSAGE_MAX_CHARS: int = 500


# --- Prometheus metrics (default registry -> existing /metrics) --------------
UNHANDLED_EXCEPTIONS_TOTAL = Counter(
    "opsgrid_unhandled_exceptions_total",
    "Total unhandled exceptions observed by the error tracker",
    ["exception_type", "method", "endpoint"],
)

ERROR_TRACKER_DROPPED_TOTAL = Counter(
    "opsgrid_error_tracker_dropped_total",
    "Error occurrences dropped because the pending aggregator was at capacity",
)

ERROR_TRACKER_FLUSH_FAILURES_TOTAL = Counter(
    "opsgrid_error_tracker_flush_failures_total",
    "Number of failed flush cycles (batch re-queued and retried)",
)

ERROR_TRACKER_PENDING_FINGERPRINTS = Gauge(
    "opsgrid_error_tracker_pending_fingerprints",
    "Distinct fingerprints currently buffered awaiting flush",
)


# --- Scrubbing ---------------------------------------------------------------
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_BEARER_RE = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-]+")
_LONG_HEX_RE = re.compile(r"\b[A-Fa-f0-9]{32,}\b")
_LONG_B64_RE = re.compile(r"\b[A-Za-z0-9+/]{40,}={0,2}\b")


def scrub(value: Optional[str]) -> Optional[str]:
    """Remove likely-PII / secret tokens from a free-text sample.

    Order matters: emails first, then bearer tokens, then bare high-entropy
    runs. This is the GDPR-facing surface and is unit-tested in isolation.
    """
    if not value:
        return value
    value = _EMAIL_RE.sub("<email>", value)
    value = _BEARER_RE.sub("Bearer <token>", value)
    value = _LONG_HEX_RE.sub("<token>", value)
    value = _LONG_B64_RE.sub("<token>", value)
    return value


def _app_frame(exc: BaseException) -> Optional[traceback.FrameSummary]:
    """Last traceback frame inside application code (skip site-packages/stdlib).

    Walks from the deepest frame outward so the fingerprint pins to where the
    bug actually surfaced in our code, not inside a library. Falls back to the
    deepest frame when nothing matches.
    """
    frames = traceback.extract_tb(exc.__traceback__)
    if not frames:
        return None
    for frame in reversed(frames):
        filename = frame.filename or ""
        if "site-packages" in filename or "dist-packages" in filename:
            continue
        if "/app/" in filename or filename.startswith("app/") or "\\app\\" in filename:
            return frame
    return frames[-1]


def compute_fingerprint(exception_type: str, method: str, route: str, exc: BaseException) -> str:
    """Stable 16-char id for an error class.

    Collapses identical bugs (same type, route template, and crash site) into a
    single fingerprint while keeping distinct routes/types/sites separate.
    """
    frame = _app_frame(exc)
    site = f"{frame.filename}:{frame.name}" if frame else "<no-frame>"
    raw = f"{exception_type}|{method}|{route}|{site}"
    return hashlib.sha256(raw.encode("utf-8", "replace")).hexdigest()[:16]


def _format_traceback(exc: BaseException) -> str:
    text_tb = "".join(
        traceback.format_exception(type(exc), exc, exc.__traceback__)
    )
    scrubbed = scrub(text_tb) or ""
    encoded = scrubbed.encode("utf-8", "replace")
    if len(encoded) > TRACEBACK_MAX_BYTES:
        encoded = encoded[:TRACEBACK_MAX_BYTES]
    return encoded.decode("utf-8", "replace")


def _hour_floor(moment: datetime) -> datetime:
    return moment.replace(minute=0, second=0, microsecond=0)


@dataclass
class PendingError:
    """Mutable in-memory accumulator for one fingerprint between flushes."""
    exception_type: str
    route: str
    method: str
    status_code: int
    message_sample: Optional[str]
    traceback_sample: Optional[str]
    count: int
    first_seen: datetime
    last_seen: datetime
    organization_id: Optional[str]
    bucket_counts: dict = field(default_factory=dict)


class ErrorTracker:
    """Bounded in-memory aggregator + durable background flush loop."""

    def __init__(self) -> None:
        self.enabled = ERROR_TRACKING_ENABLED
        self._pending: dict[str, PendingError] = {}
        self._lock = asyncio.Lock()
        self._task: Optional[asyncio.Task] = None
        self._stopping = False
        self._last_retention = datetime.now(timezone.utc)

    # -- request-path entry point --------------------------------------------
    async def record(self, exc: BaseException, *, method: str, route: str,
                     organization_id: Optional[str] = None) -> None:
        """Accumulate one unhandled-exception occurrence. Never raises."""
        exception_type = type(exc).__name__
        now = datetime.now(timezone.utc)
        hour = _hour_floor(now)

        UNHANDLED_EXCEPTIONS_TOTAL.labels(exception_type, method, route).inc()

        fingerprint = compute_fingerprint(exception_type, method, route, exc)
        message = scrub(str(exc))
        if message and len(message) > MESSAGE_MAX_CHARS:
            message = message[:MESSAGE_MAX_CHARS]
        tb_sample = _format_traceback(exc)

        async with self._lock:
            existing = self._pending.get(fingerprint)
            if existing is not None:
                existing.count += 1
                existing.last_seen = now
                existing.message_sample = message
                existing.traceback_sample = tb_sample
                if organization_id:
                    existing.organization_id = organization_id
                existing.bucket_counts[hour] = existing.bucket_counts.get(hour, 0) + 1
            else:
                if len(self._pending) >= MAX_PENDING_FINGERPRINTS:
                    # At capacity: drop this NEW fingerprint (count it) rather
                    # than growing unbounded during an error storm.
                    ERROR_TRACKER_DROPPED_TOTAL.inc()
                    return
                self._pending[fingerprint] = PendingError(
                    exception_type=exception_type,
                    route=route,
                    method=method,
                    status_code=500,
                    message_sample=message,
                    traceback_sample=tb_sample,
                    count=1,
                    first_seen=now,
                    last_seen=now,
                    organization_id=organization_id,
                    bucket_counts={hour: 1},
                )
            ERROR_TRACKER_PENDING_FINGERPRINTS.set(len(self._pending))

    # -- lifecycle ------------------------------------------------------------
    async def start(self) -> None:
        if not self.enabled:
            logger.info("error_tracker_disabled")
            return
        if self._task is not None:
            return
        self._stopping = False
        self._task = asyncio.create_task(self._run())
        logger.info(
            "error_tracker_started",
            flush_interval_seconds=FLUSH_INTERVAL_SECONDS,
            max_pending=MAX_PENDING_FINGERPRINTS,
            bucket_retention_days=BUCKET_RETENTION_DAYS,
        )

    async def stop(self) -> None:
        if self._task is None:
            return
        self._stopping = True
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None
        # Best-effort final flush so in-flight counts are not lost on shutdown.
        try:
            await self._flush_once()
        except Exception as exc:  # noqa: BLE001
            logger.error("error_tracker_final_flush_failed", error=str(exc))
        logger.info("error_tracker_stopped")

    async def _run(self) -> None:
        while not self._stopping:
            try:
                await asyncio.sleep(FLUSH_INTERVAL_SECONDS)
                await self._flush_once()
            except asyncio.CancelledError:
                break
            except Exception as exc:  # noqa: BLE001 — loop must survive anything
                ERROR_TRACKER_FLUSH_FAILURES_TOTAL.inc()
                logger.error("error_tracker_flush_loop_error", error=str(exc))

    # -- flush ----------------------------------------------------------------
    async def _swap(self) -> dict[str, PendingError]:
        async with self._lock:
            batch = self._pending
            self._pending = {}
            ERROR_TRACKER_PENDING_FINGERPRINTS.set(0)
            return batch

    async def _merge_back(self, batch: dict[str, PendingError]) -> None:
        """Re-queue an un-flushed batch after a DB failure (respect the bound)."""
        async with self._lock:
            for fp, pending in batch.items():
                current = self._pending.get(fp)
                if current is not None:
                    current.count += pending.count
                    current.first_seen = min(current.first_seen, pending.first_seen)
                    current.last_seen = max(current.last_seen, pending.last_seen)
                    for hour, n in pending.bucket_counts.items():
                        current.bucket_counts[hour] = current.bucket_counts.get(hour, 0) + n
                elif len(self._pending) < MAX_PENDING_FINGERPRINTS:
                    self._pending[fp] = pending
                else:
                    ERROR_TRACKER_DROPPED_TOTAL.inc(pending.count)
            ERROR_TRACKER_PENDING_FINGERPRINTS.set(len(self._pending))

    async def _flush_once(self) -> None:
        batch = await self._swap()
        if not batch:
            await self._maybe_prune()
            return
        try:
            async with _db.AsyncSessionLocal() as session:
                for fp, pending in batch.items():
                    await session.execute(_UPSERT_EVENT, {
                        "fingerprint": fp,
                        "exception_type": pending.exception_type,
                        "route": pending.route,
                        "method": pending.method,
                        "status_code": pending.status_code,
                        "message_sample": pending.message_sample,
                        "traceback_sample": pending.traceback_sample,
                        "count": pending.count,
                        "first_seen": pending.first_seen,
                        "last_seen": pending.last_seen,
                        "organization_id": pending.organization_id,
                    })
                    for hour, n in pending.bucket_counts.items():
                        await session.execute(_UPSERT_BUCKET, {
                            "fingerprint": fp,
                            "bucket_hour": hour,
                            "count": n,
                        })
                await session.commit()
        except Exception as exc:  # noqa: BLE001
            ERROR_TRACKER_FLUSH_FAILURES_TOTAL.inc()
            logger.error("error_tracker_flush_failed", error=str(exc),
                         fingerprints=len(batch))
            await self._merge_back(batch)
            return
        await self._maybe_prune()

    async def _maybe_prune(self) -> None:
        """Delete hourly buckets older than the retention horizon (~once/day)."""
        now = datetime.now(timezone.utc)
        if now - self._last_retention < timedelta(hours=24):
            return
        self._last_retention = now
        cutoff = now - timedelta(days=BUCKET_RETENTION_DAYS)
        try:
            async with _db.AsyncSessionLocal() as session:
                await session.execute(
                    text("DELETE FROM error_event_buckets WHERE bucket_hour < :cutoff"),
                    {"cutoff": cutoff},
                )
                await session.commit()
        except Exception as exc:  # noqa: BLE001
            logger.error("error_tracker_prune_failed", error=str(exc))


_UPSERT_EVENT = text(
    """
    INSERT INTO error_events (
        fingerprint, exception_type, route, method, status_code,
        message_sample, traceback_sample, total_count, regression_count,
        status, first_seen, last_seen, organization_id
    ) VALUES (
        :fingerprint, :exception_type, :route, :method, :status_code,
        :message_sample, :traceback_sample, :count, 0,
        'open', :first_seen, :last_seen, :organization_id
    )
    ON CONFLICT (fingerprint) DO UPDATE SET
        total_count      = error_events.total_count + EXCLUDED.total_count,
        last_seen        = GREATEST(error_events.last_seen, EXCLUDED.last_seen),
        traceback_sample = EXCLUDED.traceback_sample,
        message_sample   = EXCLUDED.message_sample,
        organization_id  = COALESCE(EXCLUDED.organization_id, error_events.organization_id),
        regression_count = error_events.regression_count
                           + CASE WHEN error_events.status = 'resolved' THEN 1 ELSE 0 END,
        status           = CASE WHEN error_events.status = 'resolved' THEN 'open'
                                ELSE error_events.status END
    """
)

_UPSERT_BUCKET = text(
    """
    INSERT INTO error_event_buckets (fingerprint, bucket_hour, count)
    VALUES (:fingerprint, :bucket_hour, :count)
    ON CONFLICT (fingerprint, bucket_hour) DO UPDATE SET
        count = error_event_buckets.count + EXCLUDED.count
    """
)


# Module-level singleton, wired into the app lifespan (mirrors the other
# background services started in app/main.py).
error_tracker = ErrorTracker()

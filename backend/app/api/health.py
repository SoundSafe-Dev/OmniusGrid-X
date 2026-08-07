"""Health check endpoints and metrics for observability"""

import asyncio
import time
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID

from aiokafka import AIOKafkaConsumer
from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.api.auth import get_current_active_user
from app.db.database import engine, get_db
from app.middleware.tenant_isolation import get_tenant_db
from app.db.models import Alarm, Asset, User
from app.middleware.rbac import require_admin

router = APIRouter()

# Simple health status cache to prevent DB overload on high-frequency probes
_health_cache: dict[str, Any] = {"status": "unknown", "last_check": 0}
_cache_ttl = 5  # seconds

# Telemetry older than this is treated as a stale ingestion pipeline
INGESTION_STALE_SECONDS = 900  # 15 minutes
BROKER_CHECK_TIMEOUT_SECONDS = 3.0


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


async def _check_database(db: AsyncSession) -> tuple[str, dict[str, Any]]:
    """Verify the database accepts queries."""
    try:
        result = await db.execute(text("SELECT 1"))
        result.scalar()
        return "ok", {}
    except Exception as exc:
        return f"error: {exc}", {}


async def _check_redis() -> tuple[str, dict[str, Any]]:
    """Verify Redis when rate limiting depends on it."""
    if not settings.RATE_LIMIT_ENABLED:
        return "skipped", {"reason": "rate_limit_disabled"}

    try:
        import redis.asyncio as redis

        client = redis.from_url(
            settings.REDIS_URL,
            socket_connect_timeout=BROKER_CHECK_TIMEOUT_SECONDS,
        )
        try:
            await asyncio.wait_for(client.ping(), timeout=BROKER_CHECK_TIMEOUT_SECONDS)
        finally:
            await client.aclose()
        return "ok", {"url": settings.REDIS_URL.split("@")[-1]}
    except Exception as exc:
        return f"error: {exc}", {}


async def _check_message_broker() -> tuple[str, dict[str, Any]]:
    """Verify Redpanda/Kafka is reachable (not just that a consumer object exists)."""
    from app.services.websocket_manager import websocket_manager

    if websocket_manager._running and websocket_manager.consumer:
        try:
            await asyncio.wait_for(
                websocket_manager.consumer.topics(),
                timeout=BROKER_CHECK_TIMEOUT_SECONDS,
            )
            return "ok", {"source": "websocket_manager", "broker": settings.REDPANDA_URL}
        except Exception as exc:
            return f"error: {exc}", {"source": "websocket_manager"}

    consumer = AIOKafkaConsumer(bootstrap_servers=settings.REDPANDA_URL)
    try:
        await asyncio.wait_for(consumer.start(), timeout=BROKER_CHECK_TIMEOUT_SECONDS)
        await asyncio.wait_for(consumer.topics(), timeout=BROKER_CHECK_TIMEOUT_SECONDS)
        return "ok", {"source": "ephemeral_probe", "broker": settings.REDPANDA_URL}
    except Exception as exc:
        return f"error: {exc}", {"source": "ephemeral_probe"}
    finally:
        await consumer.stop()


def _as_datetime(value: Any) -> Optional[datetime]:
    """Normalise a driver's idea of a timestamp into a `datetime`.

    `SELECT MAX(time)` is not typed by SQLAlchemy here — it comes back from a raw `text()`
    query, so the value is whatever the DBAPI hands over. asyncpg builds a `datetime`;
    aiosqlite returns the **raw string**, because SQLite has no timestamp type and the
    column-type converters only fire for columns it can name.

    The consequence was visible rather than theoretical: on the documented local dev path
    (`DATABASE_URL=sqlite+aiosqlite:///dev.db`, which is what `make seed-demo` sets up) the
    readiness report showed

        "ingestion": "error: 'str' object has no attribute 'isoformat'"

    so a developer's first look at System Health was a subsystem in error, for a database
    that was working perfectly. Returning None for anything unparseable keeps the existing
    "no_data_yet" branch as the fallback — the one outcome that is never a false alarm.
    """
    if value is None or isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            # SQLite writes 'YYYY-MM-DD HH:MM:SS[.ffffff]'; fromisoformat accepts the
            # space separator, and on 3.11+ the trailing 'Z' form too.
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


async def _check_ingestion(db: AsyncSession) -> tuple[str, dict[str, Any]]:
    """Verify telemetry has been ingested recently (when data exists).

    READS `telemetry` ONLY, and deliberately no longer `MAX(assets.last_seen)`.

    This runs from the PUBLIC readiness probe, which has no authenticated user and so
    no tenant context. `assets` is FORCE ROW LEVEL SECURITY, so that query returned
    NULL for a NOBYPASSRLS role no matter how much data existed — and the report then
    published `latest_asset_seen_at: null`, which reads as "no asset has ever been
    seen". That is a different and false statement from "this figure is not obtainable
    here", and a monitoring endpoint is the worst place to blur the two.

    `telemetry` has no policy and was already the primary signal
    (`latest = latest_telemetry or latest_asset_seen`), so removing the asset read
    changes no verdict: it only stops reporting a field that could never be populated.
    A per-tenant asset figure belongs on a tenant-scoped endpoint, where a caller and
    therefore a GUC exists.
    """
    try:
        result = await db.execute(text("SELECT MAX(time) FROM telemetry"))
        latest_telemetry = _as_datetime(result.scalar())

        latest = latest_telemetry
        details: dict[str, Any] = {
            "latest_telemetry_at": (
                latest_telemetry.isoformat() if latest_telemetry else None
            ),
        }

        if latest is None:
            return "ok", {**details, "note": "no_data_yet"}

        if latest.tzinfo is None:
            latest = latest.replace(tzinfo=timezone.utc)

        age_seconds = (_utc_now() - latest).total_seconds()
        details["age_seconds"] = int(age_seconds)

        if age_seconds > INGESTION_STALE_SECONDS:
            return f"stale ({int(age_seconds)}s)", details

        return "ok", details
    except Exception as exc:
        return f"error: {exc}", {}


async def _check_notifications(db: AsyncSession) -> tuple[str, dict[str, Any]]:
    """Verify the notification subscription store is reachable/queryable."""
    try:
        result = await db.execute(
            text("SELECT COUNT(*) FROM notification_subscriptions")
        )
        count = result.scalar() or 0
        return "ok", {"subscriptions": int(count)}
    except Exception as exc:
        await _rollback_quietly(db)
        return f"error: {exc}", {}


async def _check_historian(db: AsyncSession) -> tuple[str, dict[str, Any]]:
    """Verify the historian's backing table accepts queries."""
    try:
        result = await db.execute(text("SELECT 1 FROM telemetry LIMIT 1"))
        result.scalar()
        return "ok", {"table": "telemetry"}
    except Exception as exc:
        await _rollback_quietly(db)
        return f"error: {exc}", {"table": "telemetry"}


async def _rollback_quietly(db: AsyncSession) -> None:
    """Reset a failed transaction so later checks on the shared session run."""
    try:
        await db.rollback()
    except Exception:  # pragma: no cover - defensive
        pass


def _check_model_registry_storage() -> tuple[str, dict[str, Any]]:
    """Verify the model-registry artifact root exists (or can be created)."""
    import os

    try:
        from app.services.model_registry_store import model_storage_root

        root = model_storage_root()
        if root.is_dir():
            if os.access(root, os.W_OK):
                return "ok", {"path": str(root)}
            return "error: storage root not writable", {"path": str(root)}

        # save_model_artifact() mkdirs on demand, so a missing root is fine as
        # long as the nearest existing ancestor is writable.
        ancestor = root
        while not ancestor.exists() and ancestor.parent != ancestor:
            ancestor = ancestor.parent
        if ancestor.exists() and os.access(ancestor, os.W_OK):
            return "ok", {"path": str(root), "note": "created_on_first_save"}
        return (
            "error: storage root missing and not creatable",
            {"path": str(root), "nearest_existing": str(ancestor)},
        )
    except Exception as exc:
        return f"error: {exc}", {}


def _check_command_dispatch() -> tuple[str, dict[str, Any]]:
    """Verify the durable command-dispatch loop is running."""
    try:
        from app.services.command_executor import command_executor

        running = bool(command_executor._running)
        details: dict[str, Any] = {"running": running}
        if not running:
            return "not_running", details
        dispatch_task = command_executor._dispatch_task
        if dispatch_task is not None and dispatch_task.done():
            return "error: dispatch loop exited", details
        return "ok", details
    except Exception as exc:
        return f"error: {exc}", {}


async def _run_extended_checks(
    db: AsyncSession,
) -> tuple[dict[str, str], dict[str, dict[str, Any]]]:
    """Per-subsystem checks for /health/detailed; each is isolated and the
    caller never raises on a failing component."""
    notifications_status, notifications_details = await _check_notifications(db)
    historian_status, historian_details = await _check_historian(db)
    registry_status, registry_details = _check_model_registry_storage()
    command_status, command_details = _check_command_dispatch()

    checks = {
        "notifications": notifications_status,
        "historian": historian_status,
        "model_registry_storage": registry_status,
        "command_dispatch": command_status,
    }
    details = {
        "notifications": notifications_details,
        "historian": historian_details,
        "model_registry_storage": registry_details,
        "command_dispatch": command_details,
    }
    return checks, details


def _component_is_healthy(status: str) -> bool:
    return status == "ok" or status == "skipped"


async def _run_health_checks(db: AsyncSession) -> dict[str, Any]:
    """Run all dependency checks and return a structured report."""
    db_status, db_details = await _check_database(db)
    redis_status, redis_details = await _check_redis()
    broker_status, broker_details = await _check_message_broker()
    ingestion_status, ingestion_details = await _check_ingestion(db)

    checks = {
        "database": db_status,
        "redis": redis_status,
        "message_broker": broker_status,
        "ingestion": ingestion_status,
    }
    details = {
        "database": db_details,
        "redis": redis_details,
        "message_broker": broker_details,
        "ingestion": ingestion_details,
    }

    critical_ok = _component_is_healthy(db_status) and _component_is_healthy(broker_status)
    if settings.RATE_LIMIT_ENABLED:
        critical_ok = critical_ok and _component_is_healthy(redis_status)

    supporting_ok = _component_is_healthy(ingestion_status)
    overall = "ready" if critical_ok and supporting_ok else "degraded"
    if not critical_ok:
        overall = "not_ready"

    return {
        "status": overall,
        "checks": checks,
        "details": details,
        "checked_at": _utc_now().isoformat(),
    }


def _public_status(status: str) -> str:
    """Collapse a component status to something safe for an anonymous caller.

    THE DISCLOSURE THIS CLOSES. `_check_message_broker` returns strings like
    `"error: KafkaConnectionError: Unable to bootstrap from [('redpanda', 29092, ...)]"`,
    and the public probes returned them verbatim — leaking the internal broker hostname,
    its port and the technology to anybody who can reach the endpoint unauthenticated.

    That contradicted the design already stated one function below: `/health/detailed` is
    auth-gated precisely because "the per-component report (broker/redis/ingestion state,
    connection error strings) is recon-useful". The gating was right; the same strings
    simply escaped through the probes.

    A probe consumer needs the STATUS, not the reason. Kubernetes reads the code, and an
    operator reads the logs or `/health/detailed`, which still carry the full text — this
    withholds nothing from anyone entitled to it. Statuses that are already coarse
    ("ok", "skipped", "degraded") pass through unchanged; anything carrying a payload
    collapses to its first word.
    """
    if not status:
        return status
    head = status.split(":", 1)[0].strip()
    return head or "error"


def _public_checks(checks: dict[str, Any]) -> dict[str, Any]:
    return {name: _public_status(value) for name, value in checks.items()}


def _raise_if_not_ready(report: dict[str, Any]) -> None:
    if report["status"] != "ready":
        # `details` is dropped and `checks` collapsed: this response is public. The
        # full report stays available on /health/detailed, which requires a user.
        raise HTTPException(
            status_code=503,
            detail={
                "status": report["status"],
                "checks": _public_checks(report["checks"]),
            },
        )


# ==================== Response models ====================
#
# WHAT THE PROBES ACTUALLY READ, checked before declaring any of this.
# `infrastructure/k8s/base/backend-deployment.yaml` wires all three probes as `httpGet`:
# liveness and startup to `/health` (served outside this module), readiness to
# `/health/ready`. An httpGet probe reads the STATUS CODE and nothing else — kubelet never
# parses the body — so no field named here can break a rollout by being absent.
#
# The hazard runs the other way, and it is worse than the usual one. A response model that
# REJECTS a payload turns a 200 into a 500, and on `/health/ready` a 500 is a failed
# readiness probe: three of those and the pod is pulled out of the Service on a backend that
# is perfectly healthy. So every field below is typed against what the checkers can actually
# produce, and the two shapes that vary are left open rather than pinned:
#
#   * `/health/db|redis|kafka` return `{"status": ..., **details}`, and `details` belongs to
#     the CHECKER — `{"reason": "rate_limit_disabled"}`, `{"url": ...}`,
#     `{"source": ..., "broker": ...}`, or `{}`. Each model documents the keys its own
#     checker emits today and sets `extra="allow"`, so a key added to a checker tomorrow
#     reaches the caller instead of being silently filtered out of the response.
#   * `/health/detailed`'s `details` and `/admin/system/status`'s `data_pipeline` are the
#     per-component payloads, likewise checker-owned. Declared as open objects.
#
# The auth split is preserved as-is: these models describe what each route already sends,
# and `_public_status` still collapses error text on the public ones. Nothing here widens
# what an anonymous caller can see.


class ProbeOut(BaseModel):
    """`/health/live` and `/health/startup` — two fixed literals, no I/O behind either."""

    status: str
    service: str


class ReadinessOut(BaseModel):
    """The 200 path only. The not-ready path raises `HTTPException(503)`, whose body is the
    handler's `detail` and is not filtered through this model."""

    status: str
    #: Component name -> status, already collapsed by `_public_status`. This response is
    #: PUBLIC; the uncollapsed text stays on `/health/detailed`, which requires a user.
    checks: dict[str, str]


class DetailedHealthOut(BaseModel):
    """Auth-gated, so this one carries the full per-component detail."""

    status: str
    checks: dict[str, str]
    #: Per-component payloads, each owned by its checker. Left open on purpose — a fixed
    #: model here would delete whatever a checker starts reporting.
    details: dict[str, Any]
    checked_at: str


class SystemMetricsOut(BaseModel):
    """`available: False` with three nulls is the real answer when psutil is not installed —
    the page prints "—" for each, which is why they are nullable rather than zeroed."""

    available: bool
    cpu_percent: float | None = None
    memory_percent: float | None = None
    disk_percent: float | None = None


class DatabaseHealthOut(BaseModel):
    """`_check_database` returns no details today; `extra="allow"` so it may."""

    model_config = ConfigDict(extra="allow")

    status: str


class RedisHealthOut(BaseModel):
    model_config = ConfigDict(extra="allow")

    status: str
    #: `rate_limit_disabled` — a skipped check, which is not a failing one.
    reason: str | None = None
    #: Host and port only; `_check_redis` splits the credentials off at the `@`.
    url: str | None = None


class KafkaHealthOut(BaseModel):
    model_config = ConfigDict(extra="allow")

    status: str
    #: `websocket_manager` (the live consumer) or `ephemeral_probe` (one opened to answer
    #: this call). Which one answered changes what a failure means.
    source: str | None = None
    broker: str | None = None


class MaintenanceModeOut(BaseModel):
    asset_id: str
    #: The word, not the boolean: `"enabled"` / `"disabled"`.
    maintenance_mode: str
    message: str


class VacuumTriggered(BaseModel):
    message: str
    status: str
    note: str


class SystemStatusServices(BaseModel):
    #: `"healthy"`, unconditionally — the process answering the request is by definition up.
    backend: str
    #: The RAW check statuses, error text and all. This route is admin-gated, which is what
    #: makes that acceptable here and not on the public probes.
    database: str
    redis: str
    message_broker: str
    ingestion: str


class SystemStatusStorage(BaseModel):
    #: `pg_database_size(current_database())`. `None` if the row could not be read.
    database_size_bytes: int | None = None
    #: The CALLER'S organisation, not the platform — `assets` is FORCE ROW LEVEL SECURITY
    #: and this handler runs on a tenant session.
    active_assets: int


class SystemStatusAlerts(BaseModel):
    """Every severity present at 0 rather than omitted: the handler fills all four from a
    GROUP BY that only returns the severities that occur."""

    critical: int
    high: int
    medium: int
    low: int


class SystemStatusOut(BaseModel):
    services: SystemStatusServices
    #: `_check_ingestion`'s details verbatim — `latest_telemetry_at`, and `age_seconds` or
    #: `note` depending on whether any telemetry exists. Checker-owned, left open.
    data_pipeline: dict[str, Any]
    storage: SystemStatusStorage
    alerts: SystemStatusAlerts
    checked_at: str


@router.get("/health/live", response_model=ProbeOut)
async def liveness_probe():
    """Kubernetes Liveness Probe - Is the process running?"""
    return {"status": "alive", "service": "opsgrid-backend"}


@router.get("/health/ready", response_model=ReadinessOut)
async def readiness_probe(db: AsyncSession = Depends(get_db)):
    """Kubernetes Readiness Probe - Can the pod accept traffic?"""
    now = time.time()
    if now - _health_cache["last_check"] < _cache_ttl:
        if _health_cache["status"] == "ready":
            return {
                "status": "ready",
                "checks": _public_checks(_health_cache.get("checks", {})),
            }
        # Same shape as the uncached path below. This used to be a bare
        # "Service not ready" string, so the probe's response shape depended on whether
        # the cache had expired — an operator hitting it twice got two different
        # answers, and the second told them nothing about WHICH component was down.
        raise HTTPException(
            status_code=503,
            detail={
                "status": _health_cache["status"],
                "checks": _public_checks(_health_cache.get("checks", {})),
            },
        )

    report = await _run_health_checks(db)
    _health_cache.update(
        {
            "status": report["status"],
            "last_check": now,
            "checks": report["checks"],
        }
    )
    _raise_if_not_ready(report)
    return {"status": report["status"], "checks": _public_checks(report["checks"])}


@router.get("/health/startup", response_model=ProbeOut)
async def startup_probe():
    """Kubernetes Startup Probe - Is the application fully started?"""
    return {"status": "started", "service": "opsgrid-backend"}


@router.get("/health/detailed", response_model=DetailedHealthOut)
async def detailed_health(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Engineer-facing health report with per-component detail (not cached).

    Auth-gated for the same reason as /health/system: the per-component report
    (broker/redis/ingestion state, connection error strings) is recon-useful.
    Probes use /health/live|ready, which stay public.

    Extends the core checks with per-subsystem coverage (notifications,
    historian, model-registry storage, command dispatch). Supporting-subsystem
    failures degrade the report but never raise, and they are deliberately NOT
    part of /health/ready so readiness probes keep their existing semantics.
    """
    report = await _run_health_checks(db)
    extended_checks, extended_details = await _run_extended_checks(db)
    report["checks"].update(extended_checks)
    report["details"].update(extended_details)
    if report["status"] == "ready" and not all(
        _component_is_healthy(status) for status in extended_checks.values()
    ):
        report["status"] = "degraded"
    return report


# Explicit, distinct operation_ids (FS-215). These endpoints are exposed at
# BOTH an unprefixed path (for probes that predate the /api/v1 convention) and
# the versioned one. Stacked decorators on one function make FastAPI derive the
# same operationId for both, which collides in the generated SDK and warns at
# import. The paths stay as they are; only the ids are disambiguated.
@router.get("/health/system", operation_id="health_system_metrics_unversioned", response_model=SystemMetricsOut)
@router.get("/api/v1/health/system", operation_id="health_system_metrics_v1", response_model=SystemMetricsOut)
async def system_metrics(current_user=Depends(get_current_active_user)):
    """Real host resource utilization (psutil) for the admin SystemHealth page.

    Auth-gated (host sizing is recon-useful; probes should use /health/live).
    cpu_percent(interval=None) is non-blocking — it reports usage since the
    previous call, which suits the page's 15s polling; interval>0 would sleep
    ON the event loop.
    """
    try:
        import psutil
    except Exception:
        return {"available": False, "cpu_percent": None, "memory_percent": None,
                "disk_percent": None}
    return {
        "available": True,
        "cpu_percent": psutil.cpu_percent(interval=None),
        "memory_percent": psutil.virtual_memory().percent,
        "disk_percent": psutil.disk_usage("/").percent,
    }


@router.get("/health/db", operation_id="health_health_database_unversioned", response_model=DatabaseHealthOut)
@router.get("/api/v1/health/db", operation_id="health_health_database_v1", response_model=DatabaseHealthOut)
async def health_database(db: AsyncSession = Depends(get_db)):
    """Database connectivity check."""
    status, details = await _check_database(db)
    if not _component_is_healthy(status):
        # Public route: the status only. `details` carries connection error text.
        raise HTTPException(status_code=503, detail={"status": _public_status(status)})
    return {"status": _public_status(status), **details}


@router.get("/health/redis", operation_id="health_health_redis_unversioned", response_model=RedisHealthOut)
@router.get("/api/v1/health/redis", operation_id="health_health_redis_v1", response_model=RedisHealthOut)
async def health_redis():
    """Redis connectivity check (required when rate limiting is enabled)."""
    status, details = await _check_redis()
    if not _component_is_healthy(status):
        # Public route: the status only. `details` carries connection error text.
        raise HTTPException(status_code=503, detail={"status": _public_status(status)})
    return {"status": _public_status(status), **details}


@router.get("/health/kafka", operation_id="health_health_kafka_unversioned", response_model=KafkaHealthOut)
@router.get("/api/v1/health/kafka", operation_id="health_health_kafka_v1", response_model=KafkaHealthOut)
async def health_kafka():
    """Message broker (Redpanda/Kafka) connectivity check."""
    status, details = await _check_message_broker()
    if not _component_is_healthy(status):
        # Public route: the status only. `details` carries connection error text.
        raise HTTPException(status_code=503, detail={"status": _public_status(status)})
    return {"status": _public_status(status), **details}


# Prometheus metrics endpoint
TELEMETRY_INGESTED = Counter(
    "opsgrid_telemetry_ingested_total",
    "Total telemetry messages ingested",
    ["asset_id", "metric_name"],
)

TELEMETRY_INGEST_DURATION = Histogram(
    "opsgrid_telemetry_ingest_duration_seconds",
    "Time spent ingesting telemetry",
    buckets=[0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0],
)

ACTIVE_ASSETS = Gauge(
    "opsgrid_active_assets",
    "Number of active assets",
    ["organization_id"],
)

PACKML_STATE_CHANGES = Counter(
    "opsgrid_packml_state_changes_total",
    "Total PackML state transitions",
    ["asset_id", "from_state", "to_state"],
)

INGESTION_LAG = Gauge(
    "opsgrid_ingestion_lag_seconds",
    "Lag between message timestamp and ingestion",
    ["topic"],
)

EDGE_BUFFER_MESSAGES = Gauge(
    "opsgrid_edge_buffer_messages",
    "Number of messages buffered at edge",
    ["agent_id", "asset_id"],
)

OCR_ACCURACY = Gauge(
    "opsgrid_ocr_accuracy",
    "OCR accuracy percentage",
    ["asset_id"],
)

ALERTS_ACTIVE = Gauge(
    "opsgrid_alerts_active",
    "Number of active alerts by severity",
    ["severity"],
)


# CONTENT_TYPE_LATEST is Prometheus's exposition format
# ("text/plain; version=0.0.4; charset=utf-8"), not JSON. Declaring it keeps the
# OpenAPI document honest about what a scraper actually receives.
@router.get("/metrics", responses={200: {"content": {"text/plain": {}}}})
async def metrics():
    """Prometheus metrics endpoint"""
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


async def _vacuum_telemetry() -> None:
    # RESOLVED AT CALL TIME, from the module that owns it. This used the `engine` captured by
    # `from app.db.database import ...` at import, and the test harness rebinds that name PER
    # MODULE — so `app.api.health`'s copy was the placeholder, and the endpoint answered
    # `role "placeholder" does not exist` to any test that reached it. Rule 45, and the same
    # correction `core.tenant.tenant_session` needed for the same reason.
    #
    # Production has one engine, so this was never a live defect. It made the endpoint
    # untestable, which is how it stayed unreached until a write-surface walk found it.
    from app.db import database as _database

    async with _database.engine.connect() as connection:
        autocommit_connection = await connection.execution_options(
            isolation_level="AUTOCOMMIT"
        )
        await autocommit_connection.execute(
            text("VACUUM (VERBOSE, ANALYZE) telemetry")
        )


# REMOVED 2026-08-01 (FS-352): POST /admin/collectors/{collector_id}/restart.
#
# The whole handler was a `return`. It answered
#   {"message": "Restart signal sent to collector …", "status": "pending",
#    "timestamp": "2026-01-15T10:30:00Z"}
# — past tense about a signal no code sent, with a hardcoded timestamp — and nothing
# anywhere restarted anything.
#
# WHY REMOVED RATHER THAN IMPLEMENTED. A restart would have to reach the device, and the
# edge agent registers exactly one command handler: `agent_update`, bound by
# `OTAUpdateExecutor.register` (`edge-agent/opsgrid_agent/ota/executor.py:68`), which
# `main.py:68,209` constructs and registers. Submitting a `restart_collector` command would
# queue something nothing consumes — the same lie moved one layer down, and harder to see.
# Adding the handler is Hridyansh's lane.
#
# CORRECTED 2026-08-07 (FS-505). This note previously said "exactly two … `agent_update` and
# `model_update`". `ModelUpdateExecutor.register` does bind `model_update`
# (`ota/model_executor.py:68-70`), but nothing ever constructs that class, so `register()` is
# never called and the agent answers `unknown_action` — which also means every model rollout
# `rollout_orchestrator.py:297` dispatches fails against working hardware. The decision above
# was right; the premise under it was half true. `tests/test_dispatched_commands_have_a_handler.py`
# now pairs the two sides so neither the claim nor the gap can drift again.
#
# WHY REMOVED RATHER THAN 501. A 501 is a 5xx, and the contract gate counts any 5xx as a
# ServerError, so an honest "not implemented" would have made conformance worse than the
# dishonest 200 did.
#
# NOTHING CALLED IT. `assetsApi.restartCollector` existed in the frontend with zero call
# sites and is removed with it; the Collectors page renders `/api/v1/edge/fleet` and has no
# restart control. (Earlier notes in this repo — including the response_model burn-down doc
# — said "the UI calls it and an operator gets a 200 and no restart". That was wrong: the
# client function existed, no component invoked it. Corrected where it appears.)
#
# To bring it back: register a handler in the edge agent, then submit through
# `command_executor.submit_command(command_type="system", action_id="restart_collector")`
# exactly as `POST /commands/asset/{asset_id}/emergency-stop` does.


@router.post("/admin/assets/{asset_id}/maintenance", dependencies=[Depends(require_admin)],
             response_model=MaintenanceModeOut)
async def set_maintenance_mode(
    asset_id: UUID,
    enabled: bool = True,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_tenant_db),
):
    """Manual override: Set asset to maintenance mode (blocks game-theoretic commands)"""
    # SCOPED TO THE CALLER'S ORGANISATION, and the rowcount is checked.
    #
    # The session is `get_tenant_db`, not `get_db`. `assets` is FORCE ROW LEVEL SECURITY,
    # so without the `app.current_org_id` GUC the policy hides every row and the UPDATE
    # matches nothing — an explicit `organization_id` predicate cannot rescue a row RLS
    # has already removed. Adding the predicate first and testing it was what made that
    # obvious: the caller's OWN asset came back 404.
    #
    # This updated `assets` by id alone. Two separate reasons it could touch nothing: the
    # asset might belong to another tenant, and `assets` is FORCE ROW LEVEL SECURITY
    # while this handler runs on `get_db`, which sets no `app.current_org_id`. Under RLS
    # an INSERT is rejected loudly and an UPDATE is FILTERED — it succeeds having matched
    # no rows — so the endpoint returned 200 and told the operator "Game-theoretic engine
    # commands are blocked" for a write that never happened.
    #
    # The explicit organisation predicate does the scoping rather than relying on a GUC
    # this session does not set, and the rowcount turns a silent miss into a 404.
    result = await db.execute(
        text(
            """
            UPDATE assets
            SET maintenance_mode = :enabled,
                updated_at = NOW()
            WHERE id = :asset_id
              AND organization_id = :org
            """
        ),
        {
            "enabled": enabled,
            "asset_id": str(asset_id),
            "org": str(current_user.organization_id),
        },
    )
    if result.rowcount == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Asset not found in your organization.",
        )
    await db.commit()

    mode = "enabled" if enabled else "disabled"
    return {
        "asset_id": str(asset_id),
        "maintenance_mode": mode,
        "message": f"Maintenance mode {mode}. Game-theoretic engine commands are {'blocked' if enabled else 'allowed'}.",
    }


@router.post("/admin/database/vacuum", dependencies=[Depends(require_admin)],
             response_model=VacuumTriggered)
async def trigger_database_vacuum(
    current_user: User = Depends(get_current_active_user),
):
    """Manual override: Trigger database vacuum (maintenance)"""
    await _vacuum_telemetry()

    return {
        "message": "Database vacuum initiated",
        "status": "running",
        "note": "This may take several minutes for large datasets",
    }


@router.get("/admin/system/status", dependencies=[Depends(require_admin)],
            response_model=SystemStatusOut)
async def get_system_status(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_tenant_db),
):
    """Comprehensive system status for engineers (live queries, not placeholders).

    THE ONE TENANT-SCOPED ENDPOINT IN THIS FILE, and the reason the rest are not.

    `health.py` is deliberately mixed: `/health/live`, `/health/ready` and
    `/health/startup` are UNAUTHENTICATED probes, so they cannot use `get_tenant_db`
    (which resolves a tenant from an authenticated user) and must read only tables
    without a policy. They do — see `_check_ingestion`, which had to drop an
    `assets.last_seen` read for exactly that reason.

    This handler is different: it is admin-gated and has a user. On `get_db` it set no
    tenant GUC, so `assets` and `alarms` — both FORCE ROW LEVEL SECURITY — returned
    **zero** no matter how much existed. An engineer's system-status page reported
    `active_assets: 0` and no alarms on a running platform, which reads as an idle
    system rather than a broken query.

    The counts are now the caller's organisation. Platform-wide totals across tenants
    would need the super-admin role that does not exist yet — the same one
    `data_retention` and the audit log's cross-org view are blocked on.
    """
    health = await _run_health_checks(db)

    active_assets = (
        await db.execute(
            select(func.count()).select_from(Asset).where(Asset.is_active.is_(True))
        )
    ).scalar() or 0

    alarm_rows = (
        await db.execute(
            select(Alarm.severity, func.count())
            .where(Alarm.is_active.is_(True))
            .group_by(Alarm.severity)
        )
    ).all()
    alerts = {severity: count for severity, count in alarm_rows}

    # POSTGRES-ONLY, AND GUARDED RATHER THAN ASSUMED. `pg_database_size` and
    # `current_database` do not exist on SQLite, so on the documented local dev path
    # (`make seed-demo` writes `dev.db`) this raised `no such function:
    # current_database` and took the WHOLE endpoint down with it — the admin System
    # Status page 500'd over one optional figure that the model already declares
    # optional. Found by an endpoint sweep on 2026-08-01.
    #
    # `None` here means exactly what the field says it means: the size could not be
    # read. That is the honest answer for a backend with no such function, and it is
    # a strictly better one than reporting a number this database cannot produce.
    db_size_row = None
    if db.bind is not None and db.bind.dialect.name == "postgresql":
        db_size_row = (
            await db.execute(
                text("SELECT pg_database_size(current_database()) AS size_bytes")
            )
        ).mappings().first()

    return {
        "services": {
            "backend": "healthy",
            "database": health["checks"]["database"],
            "redis": health["checks"]["redis"],
            "message_broker": health["checks"]["message_broker"],
            "ingestion": health["checks"]["ingestion"],
        },
        "data_pipeline": health["details"]["ingestion"],
        "storage": {
            "database_size_bytes": db_size_row["size_bytes"] if db_size_row else None,
            "active_assets": active_assets,
        },
        "alerts": {
            "critical": alerts.get("critical", 0),
            "high": alerts.get("high", 0),
            "medium": alerts.get("medium", 0),
            "low": alerts.get("low", 0),
        },
        "checked_at": health["checked_at"],
    }

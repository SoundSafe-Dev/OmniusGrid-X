"""Health check endpoints and metrics for observability"""

import asyncio
import time
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID

import structlog
from aiokafka import AIOKafkaConsumer
from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.api.auth import get_current_active_user
from app.db.database import engine, get_db
from app.middleware.tenant_isolation import get_tenant_db
from app.db.models import Alarm, Asset, User
from app.middleware.rbac import require_admin

logger = structlog.get_logger()

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

        # DELIBERATELY NOT `core/redis_client.get_redis()` (FS-847). A health probe wants
        # the opposite of what the shared accessor provides: a fresh connection with its
        # own bounded connect timeout, closed immediately. Borrowing the shared pool would
        # report "ok" from a connection established minutes ago, and `aclose()` on it
        # would close the pool every other caller is using.
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


#: Consecutive failed iterations before a loop is reported as broken (FS-693). Dispatch
#: polls once a second, so three is about three seconds of a loop achieving nothing —
#: comfortably past a single transient DB hiccup, and far short of an operator waiting on
#: a command that will never be sent.
_MAX_CONSECUTIVE_LOOP_FAILURES = 3


def _check_command_dispatch() -> tuple[str, dict[str, Any]]:
    """Verify the durable command-dispatch loop is doing its work — not merely alive.

    THE OLD CHECK ASKED WHETHER THE TASK HAD EXITED, and a loop that fails on every
    iteration never exits: `_dispatch_loop` catches every exception and continues, which
    is correct behaviour (one poisoned command must not stop dispatch for the fleet) and
    which makes `done()` useless as a health signal. A misconfigured producer or a schema
    the loop cannot read would leave `command_dispatch: ok` on the operator's health page
    while **not one command was dispatched** — and commands are how an operator reaches a
    machine.

    That is rule 196: liveness derived from the worker is not liveness of the work. The
    executor now counts consecutive failed iterations, which is the work, and this reads
    that. Exiting is still checked — it is a real failure, just not the only one.
    """
    try:
        from app.services.command_executor import command_executor

        running = bool(command_executor._running)
        failures = getattr(command_executor, "_loop_failures", {})
        details: dict[str, Any] = {"running": running, "consecutive_failures": dict(failures)}
        if not running:
            return "not_running", details

        dispatch_task = command_executor._dispatch_task
        if dispatch_task is not None and dispatch_task.done():
            return "error: dispatch loop exited", details

        broken = sorted(
            name
            for name, count in failures.items()
            if count >= _MAX_CONSECUTIVE_LOOP_FAILURES
        )
        if broken:
            return (
                f"error: {', '.join(broken)} loop failing every iteration",
                details,
            )
        return "ok", details
    except Exception as exc:
        return f"error: {exc}", {}


def _check_export_scheduler() -> tuple[str, dict[str, Any]]:
    """Report the export scheduler on what it dispatches, not on whether it exists (FS-693).

    `ExportScheduler._run` has the same shape as the command loops — swallow the iteration's
    exception and carry on — so its task outlives any failure and cannot report one. A
    scheduler whose every cycle throws leaves scheduled exports undelivered indefinitely,
    and the customer discovers it, not the operator.

    DISABLED IS NOT BROKEN, and conflating them would be its own defect: `start()` returns
    immediately when `EXPORT_SCHEDULER_ENABLED` is false, which is a deployment posture and
    not a fault. It is reported as its own state so a health page cannot be read as "exports
    are fine" on an instance where exports were never turned on.
    """
    try:
        from app.core.config import settings
        from app.services.export_delivery import export_scheduler

        if not settings.EXPORT_SCHEDULER_ENABLED:
            return "disabled", {"enabled": False}

        failures = getattr(export_scheduler, "_consecutive_failures", 0)
        details: dict[str, Any] = {
            "enabled": True,
            "running": bool(export_scheduler._running),
            "consecutive_failures": failures,
        }
        if not export_scheduler._running:
            return "not_running", details
        if failures >= _MAX_CONSECUTIVE_LOOP_FAILURES:
            return "error: export scheduler failing every iteration", details
        return "ok", details
    except Exception as exc:
        return f"error: {exc}", {}


def _check_report_scheduler() -> tuple[str, dict[str, Any]]:
    """The compliance report scan, reported on what it achieves (FS-693).

    APScheduler catches a job's exception and keeps the schedule, so a `dispatch_due`
    failing every scan runs forever and enqueues nothing — a missed compliance report is
    otherwise discovered by an auditor. The scheduler counts consecutive failed scans in
    a wrapper job precisely because APScheduler gives the job no other way to report.
    """
    try:
        from app.core.config import settings
        from app.services.report_scheduler import report_scheduler

        if not settings.COMPLIANCE_REPORT_SCHEDULER_ENABLED:
            return "disabled", {"enabled": False}

        failures = getattr(report_scheduler, "_consecutive_scan_failures", 0)
        details: dict[str, Any] = {
            "enabled": True,
            "started": bool(report_scheduler._started),
            "consecutive_failures": failures,
        }
        if not report_scheduler._started:
            return "not_running", details
        if failures >= _MAX_CONSECUTIVE_LOOP_FAILURES:
            return "error: report scan failing every cycle", details
        return "ok", details
    except Exception as exc:
        return f"error: {exc}", {}


def _check_error_tracker() -> tuple[str, dict[str, Any]]:
    """The error tracker, which fails in the most deceptive direction available (FS-693).

    If the flush loop breaks, errors stop being persisted — and a system that has stopped
    reporting errors looks exactly like a system that has stopped having them. Every other
    subsystem failing loudly depends on this one working quietly, which is why it gets a
    check despite `_run`'s own comment that the loop must survive anything: surviving is
    not the same as working, and the consecutive-failure counter is the difference.
    """
    try:
        from app.services.error_tracker import error_tracker

        if not error_tracker.enabled:
            return "disabled", {"enabled": False}

        failures = getattr(error_tracker, "_consecutive_flush_failures", 0)
        running = error_tracker._task is not None
        details: dict[str, Any] = {
            "enabled": True,
            "running": running,
            "consecutive_failures": failures,
        }
        if not running:
            return "not_running", details
        if failures >= _MAX_CONSECUTIVE_LOOP_FAILURES:
            return "error: error flushes failing — new errors are not being recorded", details
        return "ok", details
    except Exception as exc:
        return f"error: {exc}", {}


def _check_oee_calculator() -> tuple[str, dict[str, Any]]:
    """The OEE loop, reported on whether cycles complete (FS-693).

    A stalled calculator leaves every OEE figure on the dashboard frozen at its last good
    value — which reads as a quiet shift, not a broken service. Per-asset failures inside a
    cycle are logged and tolerated (one bad asset must not starve the rest); what this
    reports is the whole cycle failing repeatedly.
    """
    try:
        from app.services.oee_calculator import oee_calculator

        failures = getattr(oee_calculator, "_consecutive_failures", 0)
        details: dict[str, Any] = {
            "running": bool(oee_calculator._running),
            "consecutive_failures": failures,
            "tracked_assets": len(getattr(oee_calculator, "_asset_states", {})),
        }
        if not oee_calculator._running:
            return "not_running", details
        if failures >= _MAX_CONSECUTIVE_LOOP_FAILURES:
            return "error: OEE cycles failing — dashboard figures are frozen", details
        return "ok", details
    except Exception as exc:
        return f"error: {exc}", {}


def _check_posting_drain() -> tuple[str, dict[str, Any]]:
    """The ledger drain, reported on whether passes complete (FS-693).

    A ledger that stops draining looks exactly like a ledger with nothing to drain: the
    queue quietly grows, and postings raised overnight wait for someone to open the Shop
    Floor page and press the button — the manual path FS-427 built this scheduler to
    retire.
    """
    try:
        from app.core.config import settings
        from app.services.posting_drain_scheduler import posting_drain_scheduler

        if not settings.POSTING_DRAIN_ENABLED:
            return "disabled", {"enabled": False}

        failures = getattr(posting_drain_scheduler, "_consecutive_failures", 0)
        details: dict[str, Any] = {
            "enabled": True,
            "running": bool(posting_drain_scheduler._running),
            "consecutive_failures": failures,
        }
        if not posting_drain_scheduler._running:
            return "not_running", details
        if failures >= _MAX_CONSECUTIVE_LOOP_FAILURES:
            return "error: posting drain failing every pass", details
        return "ok", details
    except Exception as exc:
        return f"error: {exc}", {}


def _check_fleet_sweep() -> tuple[str, dict[str, Any]]:
    """The fleet-liveness sweep (FS-704), watched from birth per FS-693's rule that a new
    background loop arrives with its failure accounting. If this loop fails every pass,
    the liveness gauges quietly revert to ingest-only writes — exactly the pre-FS-704
    world where a backend restart makes an already-dead agent unalertable."""
    try:
        from app.core.config import settings
        from app.services.edge_fleet_sweep import edge_fleet_sweep

        if not settings.EDGE_FLEET_SWEEP_ENABLED:
            return "disabled", {"enabled": False}

        failures = getattr(edge_fleet_sweep, "_consecutive_failures", 0)
        details: dict[str, Any] = {
            "enabled": True,
            "running": bool(edge_fleet_sweep._running),
            "consecutive_failures": failures,
        }
        if not edge_fleet_sweep._running:
            return "not_running", details
        if failures >= _MAX_CONSECUTIVE_LOOP_FAILURES:
            return "error: fleet sweep failing every pass", details
        return "ok", details
    except Exception as exc:
        return f"error: {exc}", {}


def _check_compliance_dispatcher() -> tuple[str, dict[str, Any]]:
    """The compliance report dispatcher (FS-705) — the register's last-but-one entry.
    A due report that never dispatches is discovered by an auditor, not an operator."""
    try:
        from app.core.config import settings
        from app.services.compliance_report_queue import compliance_report_dispatcher

        if not settings.COMPLIANCE_REPORT_DISPATCH_ENABLED:
            return "disabled", {"enabled": False}

        failures = getattr(compliance_report_dispatcher, "_consecutive_failures", 0)
        details: dict[str, Any] = {
            "enabled": True,
            "running": bool(compliance_report_dispatcher._running),
            "consecutive_failures": failures,
        }
        if not compliance_report_dispatcher._running:
            return "not_running", details
        if failures >= _MAX_CONSECUTIVE_LOOP_FAILURES:
            return "error: compliance dispatch failing every cycle", details
        return "ok", details
    except Exception as exc:
        return f"error: {exc}", {}


def _check_rollout_orchestrator() -> tuple[str, dict[str, Any]]:
    """The OTA rollout dispatcher (FS-705) — the register's last entry. Its cumulative
    OTA_ROLLOUT_FAILURES counter answers "how often, ever"; this answers "failing right
    now". A rollout stuck dispatching leaves a fleet half-upgraded indefinitely."""
    try:
        from app.core.config import settings
        from app.services.rollout_orchestrator import rollout_orchestrator

        if not settings.OTA_ROLLOUT_DISPATCH_ENABLED:
            return "disabled", {"enabled": False}

        failures = getattr(rollout_orchestrator, "_consecutive_failures", 0)
        details: dict[str, Any] = {
            "enabled": True,
            "running": bool(rollout_orchestrator._running),
            "consecutive_failures": failures,
        }
        if not rollout_orchestrator._running:
            return "not_running", details
        if failures >= _MAX_CONSECUTIVE_LOOP_FAILURES:
            return "error: rollout dispatch failing every cycle", details
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
    export_status, export_details = _check_export_scheduler()
    report_status, report_details = _check_report_scheduler()
    tracker_status, tracker_details = _check_error_tracker()
    oee_status, oee_details = _check_oee_calculator()
    drain_status, drain_details = _check_posting_drain()
    sweep_status, sweep_details = _check_fleet_sweep()
    compliance_status, compliance_details = _check_compliance_dispatcher()
    rollout_status, rollout_details = _check_rollout_orchestrator()

    checks = {
        "notifications": notifications_status,
        "historian": historian_status,
        "model_registry_storage": registry_status,
        "command_dispatch": command_status,
        "export_scheduler": export_status,
        "report_scheduler": report_status,
        "error_tracker": tracker_status,
        "oee_calculator": oee_status,
        "posting_drain": drain_status,
        "edge_fleet_sweep": sweep_status,
        "compliance_dispatcher": compliance_status,
        "rollout_orchestrator": rollout_status,
    }
    details = {
        "notifications": notifications_details,
        "historian": historian_details,
        "model_registry_storage": registry_details,
        "command_dispatch": command_details,
        "export_scheduler": export_details,
        "report_scheduler": report_details,
        "error_tracker": tracker_details,
        "oee_calculator": oee_details,
        "posting_drain": drain_details,
        "edge_fleet_sweep": sweep_details,
        "compliance_dispatcher": compliance_details,
        "rollout_orchestrator": rollout_details,
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
    unavailable = {"available": False, "cpu_percent": None, "memory_percent": None,
                   "disk_percent": None}
    try:
        import psutil
    except Exception:
        return unavailable

    # FS-540 hardening. The `try` covered only the IMPORT; the three calls below were
    # unguarded. psutil raises under a restrictive seccomp profile or when /proc is not
    # mounted — both ordinary in a hardened container — and the result was a 500 on an
    # admin page whose whole design is to say "unavailable" gracefully. `available: False`
    # already exists for exactly this answer, so the fix is to reach it.
    #
    # The plan filed this endpoint as "returns 200 with nulls on any failure —
    # indistinguishable from a working probe with no data". That premise is wrong: the
    # `available` flag distinguishes them, the response model documents why the three are
    # nullable, and `AdminPages.tsx:535` renders "Host metrics unavailable" off it. The
    # unguarded calls were the only real gap.
    try:
        return {
            "available": True,
            "cpu_percent": psutil.cpu_percent(interval=None),
            "memory_percent": psutil.virtual_memory().percent,
            "disk_percent": psutil.disk_usage("/").percent,
        }
    except Exception as exc:  # noqa: BLE001 — see above
        logger.warning("system_metrics_unavailable", error=str(exc))
        return unavailable


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


# EIGHT METRIC DEFINITIONS DELETED HERE, not moved (FS-696). They sat beside this
# endpoint for the life of the file and NOTHING incremented any of them — this is the
# API process, and the quantities they describe (telemetry ingested, PackML transitions,
# ingestion lag, edge buffer depth, OCR accuracy, active alerts) all happen in the
# ingestion worker or on the edge agent. Two of them were load-bearing anyway:
# `IngestionLagHighApp` and `OcrAccuracyLow` alerted on series only these dead
# definitions named, so neither alert could ever fire; their promtool tests passed by
# writing the series by hand (rule 188, again).
#
# The two with alerts now live where their quantity is produced:
#   opsgrid_ingestion_lag_seconds -> app/workers/health_server.py, fed by the worker
#   opsgrid_ocr_accuracy          -> edge-agent metrics, fed by the screen scraper
# The other six described things either already measured under other names
# (opsgrid_edge_buffer_messages is exported by the agent itself) or never measured at
# all; if one is wanted, define it in the process that can feed it.
# `test_no_metric_is_exported_and_never_fed.py` keeps this file from growing new ones.


# CONTENT_TYPE_LATEST is Prometheus's exposition format
# ("text/plain; version=0.0.4; charset=utf-8"), not JSON. Declaring it keeps the
# OpenAPI document honest about what a scraper actually receives.
@router.get("/metrics", responses={200: {"content": {"text/plain": {}}}})
async def metrics():
    """Prometheus metrics endpoint"""
    # FS-841. The pool gauges are read from SQLAlchemy HERE rather than maintained on
    # every checkout, so they cannot drift from the pool they describe — a connection
    # invalidated rather than returned would desynchronise hand-kept counters, and the
    # moment that matters is exactly when the pool is under stress.
    #
    # `engine` is resolved at call time from the module that owns it, for the reason
    # written out at `_vacuum_telemetry` below: `from ... import engine` captures a
    # per-module copy the test harness rebinds, and this endpoint would report the
    # placeholder's pool.
    from app.core.http_metrics import observe_db_pool
    from app.db import database as _database

    observe_db_pool(_database.engine.pool)
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
# Adding the handler was Hridyansh's lane; it is Hamad's since 2026-08-28.
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

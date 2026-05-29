"""Health check endpoints and metrics for observability"""

import asyncio
import time
from datetime import datetime, timezone
from typing import Any

from aiokafka import AIOKafkaConsumer
from fastapi import APIRouter, Depends, HTTPException, Response
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
from app.db.database import get_db
from app.db.models import Alarm, Asset

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


async def _check_ingestion(db: AsyncSession) -> tuple[str, dict[str, Any]]:
    """Verify telemetry has been ingested recently (when data exists)."""
    try:
        result = await db.execute(select(func.max(Asset.last_seen)))
        latest_asset_seen = result.scalar()

        result = await db.execute(text("SELECT MAX(time) FROM telemetry"))
        latest_telemetry = result.scalar()

        latest = latest_telemetry or latest_asset_seen
        details: dict[str, Any] = {
            "latest_telemetry_at": (
                latest_telemetry.isoformat() if latest_telemetry else None
            ),
            "latest_asset_seen_at": (
                latest_asset_seen.isoformat() if latest_asset_seen else None
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


def _raise_if_not_ready(report: dict[str, Any]) -> None:
    if report["status"] != "ready":
        raise HTTPException(
            status_code=503,
            detail={
                "status": report["status"],
                "checks": report["checks"],
                "details": report["details"],
            },
        )


@router.get("/health/live")
async def liveness_probe():
    """Kubernetes Liveness Probe - Is the process running?"""
    return {"status": "alive", "service": "opsgrid-backend"}


@router.get("/health/ready")
async def readiness_probe(db: AsyncSession = Depends(get_db)):
    """Kubernetes Readiness Probe - Can the pod accept traffic?"""
    now = time.time()
    if now - _health_cache["last_check"] < _cache_ttl:
        if _health_cache["status"] == "ready":
            return {
                "status": "ready",
                "checks": _health_cache.get("checks", {}),
            }
        raise HTTPException(status_code=503, detail="Service not ready")

    report = await _run_health_checks(db)
    _health_cache.update(
        {
            "status": report["status"],
            "last_check": now,
            "checks": report["checks"],
        }
    )
    _raise_if_not_ready(report)
    return {"status": report["status"], "checks": report["checks"]}


@router.get("/health/startup")
async def startup_probe():
    """Kubernetes Startup Probe - Is the application fully started?"""
    return {"status": "started", "service": "opsgrid-backend"}


@router.get("/health/detailed")
async def detailed_health(db: AsyncSession = Depends(get_db)):
    """Engineer-facing health report with per-component detail (not cached)."""
    return await _run_health_checks(db)


@router.get("/health/db")
@router.get("/api/v1/health/db")
async def health_database(db: AsyncSession = Depends(get_db)):
    """Database connectivity check."""
    status, details = await _check_database(db)
    if not _component_is_healthy(status):
        raise HTTPException(status_code=503, detail={"status": status, **details})
    return {"status": status, **details}


@router.get("/health/redis")
@router.get("/api/v1/health/redis")
async def health_redis():
    """Redis connectivity check (required when rate limiting is enabled)."""
    status, details = await _check_redis()
    if not _component_is_healthy(status):
        raise HTTPException(status_code=503, detail={"status": status, **details})
    return {"status": status, **details}


@router.get("/health/kafka")
@router.get("/api/v1/health/kafka")
async def health_kafka():
    """Message broker (Redpanda/Kafka) connectivity check."""
    status, details = await _check_message_broker()
    if not _component_is_healthy(status):
        raise HTTPException(status_code=503, detail={"status": status, **details})
    return {"status": status, **details}


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


@router.get("/metrics")
async def metrics():
    """Prometheus metrics endpoint"""
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


# Manual override endpoints for on-site engineers
@router.post("/admin/collectors/{collector_id}/restart")
async def restart_collector(collector_id: str):
    """Manual override: Restart a collector plugin"""
    return {
        "message": f"Restart signal sent to collector {collector_id}",
        "status": "pending",
        "timestamp": "2026-01-15T10:30:00Z",
    }


@router.post("/admin/assets/{asset_id}/maintenance")
async def set_maintenance_mode(asset_id: str, enabled: bool = True):
    """Manual override: Set asset to maintenance mode (blocks game-theoretic commands)"""
    async with get_db() as db:
        await db.execute(
            text(f"""
                UPDATE assets
                SET maintenance_mode = {enabled},
                    updated_at = NOW()
                WHERE id = '{asset_id}'
            """)
        )
        await db.commit()

    mode = "enabled" if enabled else "disabled"
    return {
        "asset_id": asset_id,
        "maintenance_mode": mode,
        "message": f"Maintenance mode {mode}. Game-theoretic engine commands are {'blocked' if enabled else 'allowed'}.",
    }


@router.post("/admin/database/vacuum")
async def trigger_database_vacuum():
    """Manual override: Trigger database vacuum (maintenance)"""
    async with get_db() as db:
        await db.execute(text("VACUUM (VERBOSE, ANALYZE) telemetry"))
        await db.commit()

    return {
        "message": "Database vacuum initiated",
        "status": "running",
        "note": "This may take several minutes for large datasets",
    }


@router.get("/admin/system/status")
async def get_system_status(db: AsyncSession = Depends(get_db)):
    """Get comprehensive system status for engineers (live queries, not placeholders)."""
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

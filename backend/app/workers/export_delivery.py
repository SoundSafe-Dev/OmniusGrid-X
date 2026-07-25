"""Redpanda worker for durable scheduled report generation and SMTP delivery."""

import asyncio
import os
from datetime import datetime, timezone
from uuid import UUID

import structlog
from aiokafka import AIOKafkaConsumer
from sqlalchemy import select, text

from app.core.config import settings
from app.workers.health_server import start_health_server
from app.db.database import AsyncSessionLocal
from app.db.models import ExportDeliveryJob, ExportTemplate, ScheduledExport
from app.services.export_delivery import (
    create_download_signature,
    send_export_email,
)
from app.services.export_processor import export_processor

logger = structlog.get_logger()

def _health_port():
    """WORKER_HEALTH_PORT, or None outside Kubernetes (tests/local runs)."""
    raw = os.getenv("WORKER_HEALTH_PORT")
    return int(raw) if raw else None



async def _load_job(job_id: UUID, org_id: UUID):
    async with AsyncSessionLocal() as session:
        await session.execute(
            text("SELECT set_config('app.current_org_id', :org, false)"),
            {"org": str(org_id)},
        )
        job = (
            await session.execute(
                select(ExportDeliveryJob).where(
                    ExportDeliveryJob.id == job_id,
                    ExportDeliveryJob.organization_id == org_id,
                )
            )
        ).scalar_one_or_none()
        if job is None or job.status == "completed":
            return None
        schedule = (
            await session.execute(
                select(ScheduledExport).where(
                    ScheduledExport.id == job.schedule_id,
                    ScheduledExport.organization_id == org_id,
                )
            )
        ).scalar_one()
        template = (
            await session.execute(
                select(ExportTemplate).where(
                    ExportTemplate.id == job.template_id,
                    ExportTemplate.organization_id == org_id,
                )
            )
        ).scalar_one()
        job.status = "running"
        job.attempts += 1
        job.started_at = datetime.now(timezone.utc)
        job.error = None
        await session.commit()
        return {
            "job_id": job.id,
            "requested_by": job.requested_by,
            "schedule_name": schedule.name,
            "recipients": list(schedule.recipients or []),
            "export_type": template.export_type,
            "columns": list(template.columns or []),
            "filters": dict(template.filters or {}),
        }


async def _finish_job(
    job_id: UUID,
    org_id: UUID,
    status: str,
    path: str | None = None,
    filename: str | None = None,
    error: str | None = None,
) -> None:
    async with AsyncSessionLocal() as session:
        await session.execute(
            text("SELECT set_config('app.current_org_id', :org, false)"),
            {"org": str(org_id)},
        )
        job = (
            await session.execute(
                select(ExportDeliveryJob).where(ExportDeliveryJob.id == job_id)
            )
        ).scalar_one()
        schedule = (
            await session.execute(
                select(ScheduledExport).where(
                    ScheduledExport.id == job.schedule_id
                )
            )
        ).scalar_one()
        job.status = status
        job.file_path = path
        job.filename = filename
        job.error = error
        job.completed_at = datetime.now(timezone.utc) if status == "completed" else None
        job.updated_at = datetime.now(timezone.utc)
        schedule.last_run_at = datetime.now(timezone.utc)
        schedule.last_status = status
        schedule.updated_at = datetime.now(timezone.utc)
        await session.commit()


async def process_job(job_id: UUID, org_id: UUID) -> None:
    # _load_job returns None for an already-completed job, so a redelivered
    # message (e.g. offset not committed before a crash) is skipped, not re-sent.
    data = await _load_job(job_id, org_id)
    if data is None:
        return
    path = None
    try:
        path, filename = await export_processor.generate_scheduled_export(
            data["export_type"],
            data["columns"],
            data["filters"],
            org_id,
            job_id,
        )
        signature = create_download_signature(job_id, org_id)
        base = settings.EXPORT_PUBLIC_BASE_URL.rstrip("/")
        url = (
            f"{base}/api/v1/exports/deliveries/{job_id}/download"
            f"?signature={signature}"
        )
        await send_export_email(data["recipients"], data["schedule_name"], url)
    except Exception as exc:
        # Nothing was delivered (generation or the email failed): mark failed and
        # re-raise so the consumer can retry. Safe — no email has gone out yet.
        if path and os.path.exists(path):
            os.remove(path)
        await _finish_job(job_id, org_id, "failed", error=str(exc))
        await export_processor._audit(
            "scheduled_export_delivery",
            {
                "job_id": str(job_id),
                "type": data["export_type"],
                "total": 1,
                "succeeded": 0,
                "status": "failed",
            },
            org_id,
            data["requested_by"],
        )
        raise

    # The email has been sent. Finalize best-effort and never raise past here, so
    # a transient bookkeeping error can't trigger a retry/redelivery that would
    # generate a second report and send a duplicate email.
    try:
        await _finish_job(job_id, org_id, "completed", path, filename)
        await export_processor._audit(
            "scheduled_export_delivery",
            {
                "job_id": str(job_id),
                "type": data["export_type"],
                "total": 1,
                "succeeded": 1,
                "status": "completed",
            },
            org_id,
            data["requested_by"],
        )
        export_processor._cleanup_old_exports()
    except Exception as exc:  # noqa: BLE001 - post-delivery bookkeeping is non-critical
        logger.error("scheduled_export_finalize_failed", job_id=str(job_id), error=str(exc))


async def run() -> None:
    consumer = AIOKafkaConsumer(
        settings.REDPANDA_EXPORT_TOPIC,
        bootstrap_servers=settings.REDPANDA_URL,
        group_id="omniusgrid-export-delivery",
        value_deserializer=lambda value: __import__("json").loads(value.decode("utf-8")),
        enable_auto_commit=False,
        auto_offset_reset="earliest",
    )
    await consumer.start()
    # stale_after=0: scheduled exports are BURSTY — the topic can be idle for
    # hours between due runs, so a staleness deadline would restart a perfectly
    # healthy worker. Readiness-only is the correct liveness semantic here.
    health = start_health_server("export-delivery", port=_health_port(), stale_after_seconds=0)
    if health:
        health.ready()
    try:
        async for message in consumer:
            for attempt in range(1, 4):
                try:
                    await process_job(
                        UUID(message.value["job_id"]),
                        UUID(message.value["organization_id"]),
                    )
                    break
                except Exception as exc:
                    logger.error(
                        "scheduled_export_failed",
                        attempt=attempt,
                        error=str(exc),
                    )
                    if attempt < 3:
                        await asyncio.sleep(5 * attempt)
            await consumer.commit()
            if health:
                health.beat()
    finally:
        await export_processor.close()
        await consumer.stop()


if __name__ == "__main__":
    asyncio.run(run())

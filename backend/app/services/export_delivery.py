"""Durable scheduled export dispatch and authenticated email delivery."""

import asyncio
import calendar
import json
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from typing import Any, Optional
from uuid import UUID
from zoneinfo import ZoneInfo

import structlog
from aiokafka import AIOKafkaProducer
from jose import JWTError, jwt
from sqlalchemy import select, text

from app.core.config import settings
from app.db.database import AsyncSessionLocal
from app.db.models import (
    ExportDeliveryJob,
    ExportTemplate,
    Organization,
    ScheduledExport,
)

logger = structlog.get_logger()


def next_run_at(current: datetime, frequency: str, timezone_name: str) -> datetime:
    """Advance a schedule while preserving its local wall-clock time."""
    zone = ZoneInfo(timezone_name)
    local = current.astimezone(zone)
    if frequency == "daily":
        result = local + timedelta(days=1)
    elif frequency == "weekly":
        result = local + timedelta(weeks=1)
    elif frequency == "monthly":
        month = local.month + 1
        year = local.year + (month > 12)
        month = 1 if month > 12 else month
        day = min(local.day, calendar.monthrange(year, month)[1])
        result = local.replace(year=year, month=month, day=day)
    else:
        raise ValueError(f"Unsupported schedule frequency '{frequency}'")
    return result.astimezone(timezone.utc)


def create_download_signature(job_id: Any, organization_id: Any) -> str:
    expires = datetime.now(timezone.utc) + timedelta(
        minutes=settings.EXPORT_LINK_EXPIRE_MINUTES
    )
    return jwt.encode(
        {
            "organization_id": str(organization_id),
            "job_id": str(job_id),
            "purpose": "export_download",
            "exp": expires,
        },
        settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )


def decode_download_signature(token: str) -> Optional[dict]:
    """Return the verified payload of a download signature, or None.

    Verifies the server signature and expiry (via ``jwt.decode``) and that the
    token was minted for export downloads. The caller is responsible for checking
    the ``job_id``/``organization_id`` claims against the resource being served.
    """
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
        )
    except JWTError:
        return None
    if payload.get("purpose") != "export_download":
        return None
    return payload


def verify_download_signature(
    token: str, job_id: Any, organization_id: Any
) -> bool:
    payload = decode_download_signature(token)
    return bool(
        payload
        and payload.get("job_id") == str(job_id)
        and payload.get("organization_id") == str(organization_id)
    )


async def send_export_email(
    recipients: list[str],
    schedule_name: str,
    download_url: str,
) -> None:
    import aiosmtplib

    if not settings.SMTP_HOST:
        raise RuntimeError("SMTP_HOST is not configured")

    message = EmailMessage()
    message["From"] = (
        f"{settings.SMTP_FROM_NAME} <{settings.SMTP_FROM_EMAIL}>"
        if settings.SMTP_FROM_NAME
        else settings.SMTP_FROM_EMAIL
    )
    message["To"] = ", ".join(recipients)
    message["Subject"] = f"OmniusGrid scheduled report: {schedule_name}"
    message.set_content(
        "Your scheduled report is ready.\n\n"
        f"Download: {download_url}\n\n"
        "This link is time-limited and grants access to this one report — "
        "please do not forward it."
    )
    await aiosmtplib.send(
        message,
        hostname=settings.SMTP_HOST,
        port=settings.SMTP_PORT,
        username=settings.SMTP_USERNAME or None,
        password=settings.SMTP_PASSWORD or None,
        use_tls=settings.SMTP_USE_TLS,
        start_tls=settings.SMTP_START_TLS,
    )


class ExportScheduler:
    """DB-backed scheduler and Redpanda outbox publisher."""

    def __init__(self) -> None:
        self._producer: Optional[AIOKafkaProducer] = None
        self._task: Optional[asyncio.Task] = None
        self._running = False

    async def start(self) -> None:
        if not settings.EXPORT_SCHEDULER_ENABLED:
            return
        self._running = True
        # Best-effort initial connect; if Redpanda is down the run loop keeps
        # retrying via _ensure_producer and queued jobs stay in the DB outbox.
        await self._ensure_producer()
        self._task = asyncio.create_task(self._run())

    async def _ensure_producer(self) -> bool:
        """Lazily (re)create the Redpanda producer. Returns True if connected.

        Called on every publish pass so a startup-time outage (or a broker that
        drops mid-run) self-heals on a later tick instead of leaving the producer
        permanently None with jobs piling up in the outbox.
        """
        if self._producer is not None:
            return True
        try:
            producer = AIOKafkaProducer(
                bootstrap_servers=settings.REDPANDA_URL,
                value_serializer=lambda value: json.dumps(value).encode("utf-8"),
                acks="all",
                enable_idempotence=True,
            )
            await producer.start()
        except Exception as exc:
            logger.error("export_scheduler_redpanda_unavailable", error=str(exc))
            return False
        self._producer = producer
        logger.info("export_scheduler_redpanda_connected")
        return True

    async def _reset_producer(self) -> None:
        """Drop the current producer so the next publish pass reconnects."""
        producer, self._producer = self._producer, None
        if producer is not None:
            try:
                await producer.stop()
            except Exception as exc:  # noqa: BLE001
                logger.warning("export_scheduler_producer_stop_failed", error=str(exc))

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        if self._producer:
            await self._producer.stop()
            self._producer = None

    async def _run(self) -> None:
        while self._running:
            try:
                await self.dispatch_due()
            except Exception as exc:
                logger.error("export_scheduler_iteration_failed", error=str(exc))
            await asyncio.sleep(settings.EXPORT_SCHEDULER_INTERVAL_SECONDS)

    async def dispatch_due(self) -> None:
        now = datetime.now(timezone.utc)
        async with AsyncSessionLocal() as session:
            org_ids = (
                await session.execute(select(Organization.id))
            ).scalars().all()

        for org_id in org_ids:
            await self._queue_due_for_org(org_id, now)
            await self._publish_queued_for_org(org_id)

    async def _set_org(self, session, org_id: Any) -> None:
        await session.execute(
            text("SELECT set_config('app.current_org_id', :org, false)"),
            {"org": str(org_id)},
        )

    async def _queue_due_for_org(self, org_id: Any, now: datetime) -> None:
        async with AsyncSessionLocal() as session:
            await self._set_org(session, org_id)
            schedules = (
                await session.execute(
                    select(ScheduledExport)
                    .where(
                        ScheduledExport.organization_id == org_id,
                        ScheduledExport.is_active == True,  # noqa: E712
                        ScheduledExport.next_run_at <= now,
                    )
                    .with_for_update(skip_locked=True)
                )
            ).scalars().all()
            for schedule in schedules:
                session.add(
                    ExportDeliveryJob(
                        organization_id=org_id,
                        schedule_id=schedule.id,
                        template_id=schedule.template_id,
                        requested_by=schedule.created_by,
                        scheduled_for=schedule.next_run_at,
                        status="queued",
                    )
                )
                schedule.last_status = "queued"
                schedule.next_run_at = next_run_at(
                    schedule.next_run_at, schedule.frequency, schedule.timezone
                )
                schedule.updated_at = datetime.now(timezone.utc)
            await session.commit()

    async def _publish_queued_for_org(self, org_id: Any) -> None:
        if not await self._ensure_producer():
            return  # Redpanda still down; jobs stay queued in the DB outbox
        async with AsyncSessionLocal() as session:
            await self._set_org(session, org_id)
            jobs = (
                await session.execute(
                    select(ExportDeliveryJob)
                    .where(
                        ExportDeliveryJob.organization_id == org_id,
                        ExportDeliveryJob.status == "queued",
                    )
                    .order_by(ExportDeliveryJob.created_at)
                    .limit(100)
                )
            ).scalars().all()
            for job in jobs:
                try:
                    await self._producer.send_and_wait(
                        settings.REDPANDA_EXPORT_TOPIC,
                        {
                            "job_id": str(job.id),
                            "organization_id": str(job.organization_id),
                        },
                        key=str(job.id).encode("utf-8"),
                    )
                except Exception as exc:  # broker went away mid-batch
                    logger.error("export_publish_failed", job_id=str(job.id), error=str(exc))
                    await self._reset_producer()
                    break  # leave this and remaining jobs queued for the next tick
                # Mark + commit per job so a crash re-publishes at most one job;
                # the duplicate is then absorbed by the worker's completed-guard.
                job.status = "published"
                job.published_at = datetime.now(timezone.utc)
                job.updated_at = datetime.now(timezone.utc)
                await session.commit()


export_scheduler = ExportScheduler()

"""DB-backed compliance report scheduler (APScheduler wake-up only)."""

from __future__ import annotations

import asyncio
import calendar
import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from app.core.config import settings
from app.db.database import AsyncSessionLocal
from app.db.models import ComplianceReportJob, Organization, ScheduledComplianceReport

logger = structlog.get_logger()

SCHEDULE_FREQUENCIES = frozenset(
    {"daily", "weekly", "monthly", "quarterly", "annually"}
)


def _add_months(local_dt: datetime, months: int) -> datetime:
    month = local_dt.month + months
    year = local_dt.year + (month - 1) // 12
    month = ((month - 1) % 12) + 1
    day = min(local_dt.day, calendar.monthrange(year, month)[1])
    return local_dt.replace(year=year, month=month, day=day)


def next_compliance_run_at(
    current: datetime,
    frequency: str,
    timezone_name: str,
) -> datetime:
    """Advance a schedule while preserving its local wall-clock time."""
    if frequency not in SCHEDULE_FREQUENCIES:
        raise ValueError(f"Unsupported schedule frequency '{frequency}'")

    zone = ZoneInfo(timezone_name)
    local = current.astimezone(zone)

    if frequency == "daily":
        result = local + timedelta(days=1)
    elif frequency == "weekly":
        result = local + timedelta(weeks=1)
    elif frequency == "monthly":
        result = _add_months(local, 1)
    elif frequency == "quarterly":
        result = _add_months(local, 3)
    else:  # annually
        year = local.year + 1
        day = local.day
        if local.month == 2 and local.day == 29 and not calendar.isleap(year):
            day = 28
        max_day = calendar.monthrange(year, local.month)[1]
        result = local.replace(year=year, month=local.month, day=min(day, max_day))

    return result.astimezone(timezone.utc)


def first_next_run_after(
    now: datetime,
    due_at: datetime,
    frequency: str,
    timezone_name: str,
) -> datetime:
    """Return the first recurrence strictly after ``now`` (coalesce missed runs)."""
    next_dt = next_compliance_run_at(due_at, frequency, timezone_name)
    while next_dt <= now:
        next_dt = next_compliance_run_at(next_dt, frequency, timezone_name)
    return next_dt


class ComplianceReportScheduler:
    """Periodic DB scan that enqueues due compliance report jobs."""

    _SCAN_JOB_ID = "compliance_report_schedule_scan"

    def __init__(self) -> None:
        self._scheduler = AsyncIOScheduler(timezone=timezone.utc)
        self._started = False

    async def start(self) -> None:
        if not settings.COMPLIANCE_REPORT_SCHEDULER_ENABLED:
            logger.info("compliance_report_scheduler_disabled")
            return
        if self._started:
            return
        self._scheduler.add_job(
            self.dispatch_due,
            "interval",
            seconds=settings.COMPLIANCE_REPORT_SCHEDULER_INTERVAL_SECONDS,
            id=self._SCAN_JOB_ID,
            replace_existing=True,
            max_instances=1,
        )
        self._scheduler.start()
        self._started = True
        logger.info(
            "compliance_report_scheduler_started",
            interval_seconds=settings.COMPLIANCE_REPORT_SCHEDULER_INTERVAL_SECONDS,
        )

    async def stop(self) -> None:
        if not self._started:
            return
        self._started = False
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)
            await asyncio.sleep(0)
        logger.info("compliance_report_scheduler_stopped")

    async def dispatch_due(self, now: datetime | None = None) -> None:
        if now is None:
            now = datetime.now(timezone.utc)
        elif now.tzinfo is None:
            raise ValueError("now must be timezone-aware")

        async with AsyncSessionLocal() as session:
            org_ids = (await session.execute(select(Organization.id))).scalars().all()

        for org_id in org_ids:
            await self._dispatch_due_for_org(org_id, now)

    async def _set_org(self, session, org_id: UUID) -> None:
        await session.execute(
            text("SELECT set_config('app.current_org_id', :org, true)"),
            {"org": str(org_id)},
        )

    async def _dispatch_due_for_org(self, org_id: UUID, now: datetime) -> None:
        async with AsyncSessionLocal() as session:
            await self._set_org(session, org_id)
            due_ids = (
                await session.execute(
                    select(ScheduledComplianceReport.id).where(
                        ScheduledComplianceReport.organization_id == org_id,
                        ScheduledComplianceReport.is_active == True,  # noqa: E712
                        ScheduledComplianceReport.next_run_at <= now,
                    )
                )
            ).scalars().all()

        for schedule_id in due_ids:
            await self._enqueue_due_schedule(org_id, schedule_id, now)

    async def _enqueue_due_schedule(
        self,
        org_id: UUID,
        schedule_id: UUID,
        now: datetime,
    ) -> ComplianceReportJob | None:
        async with AsyncSessionLocal() as session:
            await self._set_org(session, org_id)
            schedule = (
                await session.execute(
                    select(ScheduledComplianceReport)
                    .where(
                        ScheduledComplianceReport.id == schedule_id,
                        ScheduledComplianceReport.organization_id == org_id,
                        ScheduledComplianceReport.is_active == True,  # noqa: E712
                        ScheduledComplianceReport.next_run_at <= now,
                    )
                    .with_for_update(skip_locked=True)
                )
            ).scalar_one_or_none()
            if schedule is None:
                return None

            due_at = schedule.next_run_at
            job = ComplianceReportJob(
                organization_id=org_id,
                requested_by=schedule.created_by,
                framework=schedule.framework,
                format=schedule.format,
                recipients=list(schedule.recipients or []),
                schedule_id=schedule.id,
                scheduled_for=due_at,
                report_status="queued",
                delivery_status="pending",
            )
            schedule.last_status = "queued"
            schedule.next_run_at = first_next_run_after(
                now,
                due_at,
                schedule.frequency,
                schedule.timezone,
            )
            schedule.updated_at = now
            session.add(job)
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                logger.warning(
                    "compliance_report_schedule_duplicate_skipped",
                    schedule_id=str(schedule_id),
                    scheduled_for=due_at.isoformat(),
                )
                return None

        await self._audit_enqueue(org_id, schedule_id, job, due_at)
        return job

    async def _audit_enqueue(
        self,
        org_id: UUID,
        schedule_id: UUID,
        job: ComplianceReportJob,
        scheduled_for: datetime,
    ) -> None:
        details: dict[str, Any] = {
            "schedule_id": str(schedule_id),
            "job_id": str(job.id),
            "framework": job.framework,
            "format": job.format,
            "scheduled_for": scheduled_for.isoformat(),
            "status": "queued",
        }
        try:
            async with AsyncSessionLocal() as session:
                await self._set_org(session, org_id)
                await session.execute(
                    text(
                        """
                        INSERT INTO audit_logs
                            (id, timestamp, user_id, organization_id, action,
                             resource_type, resource_id, details)
                        VALUES
                            (:id, now(), NULL, :organization_id,
                             'compliance_report_schedule_enqueued',
                             'compliance_report_schedule', :resource_id,
                             CAST(:details AS JSONB))
                        """
                    ),
                    {
                        "id": str(uuid.uuid4()),
                        "organization_id": str(org_id),
                        "resource_id": str(schedule_id),
                        "details": json.dumps(details),
                    },
                )
                await session.commit()
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "compliance_report_schedule_enqueue_audit_failed",
                schedule_id=str(schedule_id),
                job_id=str(job.id),
                error=str(exc),
            )


report_scheduler = ComplianceReportScheduler()

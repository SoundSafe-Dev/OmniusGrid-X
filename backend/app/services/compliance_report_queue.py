"""Durable compliance-report outbox dispatcher and Redpanda publisher."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from uuid import UUID

import structlog
from aiokafka import AIOKafkaProducer
from sqlalchemy import select, text

from app.core.config import settings
from app.db.database import AsyncSessionLocal
from app.db.models import ComplianceReportJob, Organization

logger = structlog.get_logger()

MESSAGE_SCHEMA_VERSION = 1


async def enqueue_compliance_report_job(
    *,
    organization_id: UUID,
    requested_by: UUID,
    framework: str,
    report_format: str,
    recipients: list[str],
) -> ComplianceReportJob:
    """Persist a queued job before any broker publication attempt."""
    async with AsyncSessionLocal() as session:
        await session.execute(
            text("SELECT set_config('app.current_org_id', :org_id, true)"),
            {"org_id": str(organization_id)},
        )
        job = ComplianceReportJob(
            organization_id=organization_id,
            requested_by=requested_by,
            framework=framework,
            format=report_format,
            recipients=list(recipients),
            report_status="queued",
            delivery_status="pending",
        )
        session.add(job)
        await session.flush()
        await session.refresh(job)
        await session.commit()
        return job


class ComplianceReportDispatcher:
    """Scan queued jobs and publish them to Redpanda."""

    def __init__(self) -> None:
        self._producer: Optional[AIOKafkaProducer] = None
        # Bootstrap address the cached producer was built for, so a changed
        # REDPANDA_URL forces a rebuild instead of reusing a stale connection.
        self._producer_bootstrap: Optional[str] = None
        self._task: Optional[asyncio.Task] = None
        self._running = False
        #: Consecutive failed dispatch cycles (FS-693's pattern, closing the register's
        #: last-but-one entry). The loop swallows to survive, so its task cannot say that
        #: every cycle is failing — and a due compliance report that never dispatches is
        #: discovered by an auditor, not an operator.
        self._consecutive_failures = 0

    async def start(self) -> None:
        if not settings.COMPLIANCE_REPORT_DISPATCH_ENABLED:
            return
        self._running = True
        await self._ensure_producer()
        self._task = asyncio.create_task(self._run())

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

    async def _ensure_producer(self) -> bool:
        # Rebuild if REDPANDA_URL has changed since this producer was created.
        # A cached producer was previously returned unconditionally, so once built
        # it kept talking to whatever address it was born with — forever. In
        # long-lived workers a reconfigured broker address was never picked up, and
        # in tests the singleton leaked a connection to a torn-down broker across
        # modules (the residual state behind the "flaky" Kafka e2e).
        if self._producer is not None and self._producer_bootstrap != settings.REDPANDA_URL:
            await self._reset_producer()
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
        except Exception as exc:  # noqa: BLE001
            logger.error("compliance_report_redpanda_unavailable", error=str(exc))
            return False
        self._producer = producer
        self._producer_bootstrap = settings.REDPANDA_URL
        logger.info("compliance_report_redpanda_connected")
        return True

    async def _reset_producer(self) -> None:
        producer, self._producer = self._producer, None
        self._producer_bootstrap = None
        if producer is not None:
            try:
                await producer.stop()
            except Exception as exc:  # noqa: BLE001
                logger.warning("compliance_report_producer_stop_failed", error=str(exc))

    async def _run(self) -> None:
        while self._running:
            try:
                await self.dispatch_queued()
                self._consecutive_failures = 0
            except Exception as exc:  # noqa: BLE001
                self._consecutive_failures += 1
                logger.error("compliance_report_dispatch_iteration_failed", error=str(exc))
            await asyncio.sleep(settings.COMPLIANCE_REPORT_DISPATCH_INTERVAL_SECONDS)

    async def _set_org(self, session, org_id: Any) -> None:
        await session.execute(
            text("SELECT set_config('app.current_org_id', :org, true)"),
            {"org": str(org_id)},
        )

    async def recover_stale_publications(self) -> None:
        cutoff = datetime.now(timezone.utc) - timedelta(
            seconds=settings.COMPLIANCE_REPORT_STALE_PUBLISHING_SECONDS
        )
        async with AsyncSessionLocal() as session:
            org_ids = (await session.execute(select(Organization.id))).scalars().all()
            for org_id in org_ids:
                await self._set_org(session, org_id)
                stale = (
                    await session.execute(
                        select(ComplianceReportJob).where(
                            ComplianceReportJob.organization_id == org_id,
                            ComplianceReportJob.report_status == "publishing",
                            ComplianceReportJob.updated_at <= cutoff,
                        )
                    )
                ).scalars().all()
                for job in stale:
                    job.report_status = "queued"
                    job.updated_at = datetime.now(timezone.utc)
                if stale:
                    await session.commit()

    async def dispatch_queued(self) -> None:
        await self.recover_stale_publications()
        if not await self._ensure_producer():
            return

        async with AsyncSessionLocal() as session:
            org_ids = (await session.execute(select(Organization.id))).scalars().all()

        for org_id in org_ids:
            await self._publish_queued_for_org(org_id)

    async def _claim_next_for_org(
        self,
        org_id: Any,
    ) -> tuple[UUID, UUID] | None:
        async with AsyncSessionLocal() as session:
            await self._set_org(session, org_id)
            job = (
                await session.execute(
                    select(ComplianceReportJob)
                    .where(
                        ComplianceReportJob.organization_id == org_id,
                        ComplianceReportJob.report_status == "queued",
                    )
                    .order_by(ComplianceReportJob.created_at)
                    .limit(1)
                    .with_for_update(skip_locked=True)
                )
            ).scalar_one_or_none()
            if job is None:
                return None
            job.report_status = "publishing"
            job.publication_attempts += 1
            job.updated_at = datetime.now(timezone.utc)
            claimed = (job.id, job.organization_id)
            await session.commit()
            return claimed

    async def _finish_publication(
        self,
        job_id: UUID,
        org_id: UUID,
        *,
        error: Exception | None = None,
    ) -> None:
        async with AsyncSessionLocal() as session:
            await self._set_org(session, org_id)
            job = (
                await session.execute(
                    select(ComplianceReportJob)
                    .where(
                        ComplianceReportJob.id == job_id,
                        ComplianceReportJob.organization_id == org_id,
                        ComplianceReportJob.report_status == "publishing",
                    )
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if job is None:
                return
            job.updated_at = datetime.now(timezone.utc)
            if error is None:
                job.report_status = "published"
                job.published_at = datetime.now(timezone.utc)
                job.error_report = None
            else:
                job.report_status = "queued"
                job.error_report = str(error)[:2000]
            await session.commit()

    async def _publish_queued_for_org(self, org_id: Any) -> None:
        if not await self._ensure_producer():
            return

        for _ in range(100):
            claimed = await self._claim_next_for_org(org_id)
            if claimed is None:
                return
            job_id, claimed_org_id = claimed
            payload = {
                "schema_version": MESSAGE_SCHEMA_VERSION,
                "job_id": str(job_id),
                "organization_id": str(claimed_org_id),
            }
            try:
                await self._producer.send_and_wait(
                    settings.REDPANDA_COMPLIANCE_REPORTS_TOPIC,
                    payload,
                    key=str(job_id).encode("utf-8"),
                )
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "compliance_report_publish_failed",
                    job_id=str(job_id),
                    error=str(exc),
                )
                await self._finish_publication(
                    job_id,
                    claimed_org_id,
                    error=exc,
                )
                await self._reset_producer()
                return
            await self._finish_publication(job_id, claimed_org_id)


compliance_report_dispatcher = ComplianceReportDispatcher()

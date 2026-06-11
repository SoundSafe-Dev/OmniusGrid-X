"""Redpanda worker for async compliance report generation and email delivery."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Callable
from uuid import UUID

import structlog
from aiokafka import AIOKafkaConsumer
from sqlalchemy import select, text

from app.core.config import settings
from app.db.database import AsyncSessionLocal
from app.db.models import ComplianceReportJob, Organization
from app.services.compliance_report_queue import MESSAGE_SCHEMA_VERSION
from app.services.compliance_report_service import (
    absolute_report_path,
    generate_and_store_report,
    report_file_matches_metadata,
    truncate_error,
)
from app.services.email_service import (
    EmailConfigurationError,
    send_compliance_report_email,
)
from app.utils.signed_urls import build_compliance_signed_download_url

logger = structlog.get_logger()

DownloadUrlFactory = Callable[[UUID, UUID, datetime], tuple[str, datetime]]


class RetryableComplianceReportError(RuntimeError):
    """A persisted job failure that should be retried before committing the offset."""


def build_signed_compliance_download_url(
    job_id: UUID,
    organization_id: UUID,
    expires_at: datetime,
) -> tuple[str, datetime]:
    return build_compliance_signed_download_url(job_id, organization_id, expires_at)


async def _set_org(session, org_id: UUID) -> None:
    await session.execute(
        text("SELECT set_config('app.current_org_id', :org, true)"),
        {"org": str(org_id)},
    )


async def recover_stale_jobs() -> None:
    now = datetime.now(timezone.utc)
    running_cutoff = now - timedelta(seconds=settings.COMPLIANCE_REPORT_STALE_RUNNING_SECONDS)
    sending_cutoff = now - timedelta(seconds=settings.COMPLIANCE_REPORT_STALE_SENDING_SECONDS)

    async with AsyncSessionLocal() as session:
        org_ids = (await session.execute(select(Organization.id))).scalars().all()

    for org_id in org_ids:
        async with AsyncSessionLocal() as session:
            await _set_org(session, org_id)
            jobs = (
                await session.execute(
                    select(ComplianceReportJob).where(
                        ComplianceReportJob.organization_id == org_id
                    )
                )
            ).scalars().all()
            changed = False
            for job in jobs:
                if (
                    job.report_status == "running"
                    and job.started_at
                    and job.started_at <= running_cutoff
                ):
                    job.report_status = (
                        "failed"
                        if job.generation_attempts
                        >= settings.COMPLIANCE_REPORT_GENERATION_MAX_ATTEMPTS
                        else "published"
                    )
                    job.updated_at = now
                    changed = True
                if job.delivery_status == "sending" and job.updated_at <= sending_cutoff:
                    job.delivery_status = (
                        "failed"
                        if job.email_attempts
                        >= settings.COMPLIANCE_REPORT_EMAIL_MAX_ATTEMPTS
                        else "pending"
                    )
                    job.updated_at = now
                    changed = True
            if changed:
                await session.commit()


async def _load_job(job_id: UUID, org_id: UUID) -> ComplianceReportJob | None:
    async with AsyncSessionLocal() as session:
        await _set_org(session, org_id)
        return (
            await session.execute(
                select(ComplianceReportJob).where(
                    ComplianceReportJob.id == job_id,
                    ComplianceReportJob.organization_id == org_id,
                )
            )
        ).scalar_one_or_none()


async def _claim_for_generation(job_id: UUID, org_id: UUID) -> ComplianceReportJob | None:
    async with AsyncSessionLocal() as session:
        await _set_org(session, org_id)
        job = (
            await session.execute(
                select(ComplianceReportJob)
                .where(
                    ComplianceReportJob.id == job_id,
                    ComplianceReportJob.organization_id == org_id,
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if job is None:
            return None
        if job.report_status in {"completed", "failed"}:
            return None
        if job.report_status == "running":
            return None
        if job.report_status not in {"published", "queued"}:
            return None
        if (
            job.generation_attempts
            >= settings.COMPLIANCE_REPORT_GENERATION_MAX_ATTEMPTS
        ):
            job.report_status = "failed"
            job.updated_at = datetime.now(timezone.utc)
            await session.commit()
            return None

        job.report_status = "running"
        job.generation_attempts += 1
        job.started_at = datetime.now(timezone.utc)
        job.updated_at = datetime.now(timezone.utc)
        job.error_report = None
        await session.commit()
        return job


async def _mark_report_completed(job: ComplianceReportJob, metadata: dict) -> None:
    async with AsyncSessionLocal() as session:
        await _set_org(session, job.organization_id)
        row = (
            await session.execute(
                select(ComplianceReportJob).where(ComplianceReportJob.id == job.id)
            )
        ).scalar_one()
        row.report_status = "completed"
        row.file_path = metadata["file_path"]
        row.filename = metadata["filename"]
        row.media_type = metadata["media_type"]
        row.file_size = metadata["file_size"]
        row.file_sha256 = metadata["file_sha256"]
        row.completed_at = datetime.now(timezone.utc)
        row.updated_at = datetime.now(timezone.utc)
        row.error_report = None
        await session.commit()


async def _record_generation_failure(
    job_id: UUID,
    org_id: UUID,
    error: str,
) -> bool:
    """Persist a generation failure and return whether another attempt is allowed."""
    async with AsyncSessionLocal() as session:
        await _set_org(session, org_id)
        row = (
            await session.execute(
                select(ComplianceReportJob)
                .where(ComplianceReportJob.id == job_id)
                .with_for_update()
            )
        ).scalar_one()
        retryable = (
            row.generation_attempts
            < settings.COMPLIANCE_REPORT_GENERATION_MAX_ATTEMPTS
        )
        row.report_status = "published" if retryable else "failed"
        row.error_report = truncate_error(error)
        row.updated_at = datetime.now(timezone.utc)
        await session.commit()
        return retryable


def _stored_file_is_valid(job: ComplianceReportJob) -> bool:
    if not job.file_path or not job.file_sha256:
        return False
    try:
        path = absolute_report_path(
            job.file_path,
            organization_id=job.organization_id,
            job_id=job.id,
        )
        return report_file_matches_metadata(
            path,
            expected_sha256=job.file_sha256,
            expected_size=job.file_size,
        )
    except (OSError, ValueError):
        return False


async def _reset_invalid_completed_job(job_id: UUID, org_id: UUID) -> None:
    async with AsyncSessionLocal() as session:
        await _set_org(session, org_id)
        row = (
            await session.execute(
                select(ComplianceReportJob)
                .where(
                    ComplianceReportJob.id == job_id,
                    ComplianceReportJob.organization_id == org_id,
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if row is None or row.report_status != "completed":
            return
        row.report_status = "published"
        row.file_path = None
        row.filename = None
        row.media_type = None
        row.file_size = None
        row.file_sha256 = None
        row.completed_at = None
        row.updated_at = datetime.now(timezone.utc)
        await session.commit()


async def _mark_delivery_skipped(job: ComplianceReportJob) -> None:
    async with AsyncSessionLocal() as session:
        await _set_org(session, job.organization_id)
        row = (
            await session.execute(
                select(ComplianceReportJob)
                .where(ComplianceReportJob.id == job.id)
                .with_for_update()
            )
        ).scalar_one()
        if row.email_sent_at is None:
            row.delivery_status = "skipped"
            row.updated_at = datetime.now(timezone.utc)
            await session.commit()


async def _claim_email(job: ComplianceReportJob) -> ComplianceReportJob | None:
    async with AsyncSessionLocal() as session:
        await _set_org(session, job.organization_id)
        row = (
            await session.execute(
                select(ComplianceReportJob)
                .where(ComplianceReportJob.id == job.id)
                .with_for_update()
            )
        ).scalar_one()
        if row.email_sent_at is not None or row.delivery_status in {"sent", "sending"}:
            return None
        if row.email_attempts >= settings.COMPLIANCE_REPORT_EMAIL_MAX_ATTEMPTS:
            row.delivery_status = "failed"
            row.updated_at = datetime.now(timezone.utc)
            await session.commit()
            return None
        row.delivery_status = "sending"
        row.email_attempts += 1
        row.updated_at = datetime.now(timezone.utc)
        await session.commit()
        return row


async def _record_email_failure(
    job: ComplianceReportJob,
    error: Exception,
    *,
    permanent: bool,
) -> bool:
    """Persist an email failure and return whether another attempt is allowed."""
    async with AsyncSessionLocal() as session:
        await _set_org(session, job.organization_id)
        row = (
            await session.execute(
                select(ComplianceReportJob)
                .where(ComplianceReportJob.id == job.id)
                .with_for_update()
            )
        ).scalar_one()
        retryable = (
            not permanent
            and row.email_attempts < settings.COMPLIANCE_REPORT_EMAIL_MAX_ATTEMPTS
        )
        row.delivery_status = "failed"
        row.error_delivery = truncate_error(str(error))
        row.updated_at = datetime.now(timezone.utc)
        await session.commit()
        return retryable


async def _deliver_email(
    job: ComplianceReportJob,
    download_url_factory: DownloadUrlFactory = build_signed_compliance_download_url,
) -> None:
    if job.email_sent_at is not None:
        return
    if not settings.COMPLIANCE_REPORT_EMAIL_ENABLED:
        await _mark_delivery_skipped(job)
        return
    if not job.recipients:
        await _mark_delivery_skipped(job)
        return

    claimed = await _claim_email(job)
    if claimed is None:
        return

    generated_at = claimed.completed_at or datetime.now(timezone.utc)
    expires_at = datetime.now(timezone.utc) + timedelta(
        minutes=settings.EXPORT_LINK_EXPIRE_MINUTES
    )
    download_url, expires_at = download_url_factory(
        claimed.id,
        claimed.organization_id,
        expires_at,
    )

    try:
        await send_compliance_report_email(
            claimed.recipients,
            claimed.framework,
            generated_at,
            download_url,
            expires_at,
            max_attempts=1,
        )
    except EmailConfigurationError as exc:
        await _record_email_failure(claimed, exc, permanent=True)
        return
    except Exception as exc:  # EmailDeliveryError and unexpected transport failures
        retryable = await _record_email_failure(claimed, exc, permanent=False)
        if retryable:
            raise RetryableComplianceReportError(str(exc)) from exc
        return

    async with AsyncSessionLocal() as session:
        await _set_org(session, claimed.organization_id)
        row = (
            await session.execute(
                select(ComplianceReportJob)
                .where(ComplianceReportJob.id == claimed.id)
                .with_for_update()
            )
        ).scalar_one()
        row.delivery_status = "sent"
        row.email_sent_at = datetime.now(timezone.utc)
        row.error_delivery = None
        row.updated_at = datetime.now(timezone.utc)
        await session.commit()


async def process_job(
    job_id: UUID,
    org_id: UUID,
    *,
    download_url_factory: DownloadUrlFactory = build_signed_compliance_download_url,
) -> None:
    """Generate at most one report file and attempt email delivery once per pass."""
    await recover_stale_jobs()
    existing = await _load_job(job_id, org_id)
    if existing is None:
        return
    if existing.report_status == "failed":
        return

    if existing.report_status == "completed" and _stored_file_is_valid(existing):
        job = existing
    else:
        if existing.report_status == "completed":
            await _reset_invalid_completed_job(job_id, org_id)
        job = await _claim_for_generation(job_id, org_id)
        if job is None:
            refreshed = await _load_job(job_id, org_id)
            if (
                refreshed
                and refreshed.report_status == "completed"
                and _stored_file_is_valid(refreshed)
            ):
                job = refreshed
            else:
                return

        if job.report_status != "completed":
            try:
                async with AsyncSessionLocal() as session:
                    metadata = await generate_and_store_report(
                        session,
                        job.organization_id,
                        job.id,
                        job.framework,
                        job.format,
                        job.requested_by,
                    )
                await _mark_report_completed(job, metadata)
                job = await _load_job(job_id, org_id)
                if job is None:
                    return
            except Exception as exc:  # noqa: BLE001
                retryable = await _record_generation_failure(
                    job_id,
                    org_id,
                    str(exc),
                )
                if retryable:
                    raise RetryableComplianceReportError(str(exc)) from exc
                return

    await _deliver_email(job, download_url_factory=download_url_factory)


def _validate_message(payload: dict) -> tuple[UUID, UUID]:
    if not isinstance(payload, dict):
        raise ValueError("Compliance report message must be a JSON object")
    if payload.get("schema_version") != MESSAGE_SCHEMA_VERSION:
        raise ValueError("Unsupported message schema version")
    return UUID(payload["job_id"]), UUID(payload["organization_id"])


async def handle_message(payload: dict) -> None:
    job_id, org_id = _validate_message(payload)
    max_attempts = max(
        settings.COMPLIANCE_REPORT_GENERATION_MAX_ATTEMPTS,
        settings.COMPLIANCE_REPORT_EMAIL_MAX_ATTEMPTS,
    )
    for attempt in range(1, max_attempts + 1):
        try:
            await process_job(job_id, org_id)
            return
        except RetryableComplianceReportError as exc:
            logger.warning(
                "compliance_report_job_retry",
                job_id=str(job_id),
                attempt=attempt,
                error=str(exc),
            )
            if attempt < max_attempts:
                await asyncio.sleep(5 * attempt)
    raise RuntimeError(f"Compliance report job {job_id} exhausted in-process retries")


async def run(max_messages: int | None = None) -> None:
    consumer = AIOKafkaConsumer(
        settings.REDPANDA_COMPLIANCE_REPORTS_TOPIC,
        bootstrap_servers=settings.REDPANDA_URL,
        group_id="omniusgrid-compliance-reports",
        value_deserializer=lambda value: __import__("json").loads(value.decode("utf-8")),
        enable_auto_commit=False,
        auto_offset_reset="earliest",
    )
    await consumer.start()
    try:
        await recover_stale_jobs()
        processed = 0
        async for message in consumer:
            try:
                await handle_message(message.value)
            except (KeyError, TypeError, ValueError) as exc:
                logger.error(
                    "compliance_report_message_rejected",
                    error=str(exc),
                )
            except Exception:
                logger.exception("compliance_report_worker_stopping_for_redelivery")
                raise
            await consumer.commit()
            processed += 1
            if max_messages is not None and processed >= max_messages:
                return
    finally:
        await consumer.stop()


if __name__ == "__main__":
    asyncio.run(run())

"""Async compliance report generation API (Task 7 — independent router)."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_active_user
from app.core.config import settings
from app.db.models import ComplianceReportJob, ScheduledComplianceReport, User
from app.middleware.rbac import require_admin, require_roles
from app.middleware.rate_limit import rate_limit
from app.middleware.tenant_isolation import get_tenant_db, get_tenant_org_id
from app.db.database import AsyncSessionLocal
from app.services.compliance_report_service import (
    SUPPORTED_FORMATS,
    SUPPORTED_FRAMEWORKS,
    absolute_report_path,
    report_file_matches_metadata,
)
from app.services.report_scheduler import SCHEDULE_FREQUENCIES
from app.services.report_download_audit import audit_compliance_report_download
from app.utils.signed_urls import (
    PURPOSE_COMPLIANCE_REPORT,
    SignedTokenError,
    verify_signed_download_token,
)

logger = structlog.get_logger()

router = APIRouter()
public_router = APIRouter()

INVALID_LINK_DETAIL = "Invalid or expired download link"


def _secure_file_response(path, media_type: str, filename: str) -> FileResponse:
    response = FileResponse(path, media_type=media_type, filename=filename)
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Pragma"] = "no-cache"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


class ComplianceReportEnqueueRequest(BaseModel):
    framework: Literal["all", "gdpr", "soc2", "iso27001"] = "all"
    format: Literal["json", "pdf"] = "json"


class ScheduledComplianceReportCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    framework: Literal["all", "gdpr", "soc2", "iso27001"]
    format: Literal["json", "pdf"]
    frequency: Literal["daily", "weekly", "monthly", "quarterly", "annually"]
    timezone: str = "UTC"
    next_run_at: datetime
    recipients: list[str] = Field(default_factory=list)
    is_active: bool = False


class ScheduledComplianceReportUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=255)
    framework: Literal["all", "gdpr", "soc2", "iso27001"] | None = None
    format: Literal["json", "pdf"] | None = None
    frequency: Literal["daily", "weekly", "monthly", "quarterly", "annually"] | None = None
    timezone: str | None = None
    next_run_at: datetime | None = None
    recipients: list[str] | None = None
    is_active: bool | None = None


class ScheduledComplianceReportResponse(BaseModel):
    id: UUID
    organization_id: UUID
    name: str
    framework: str
    format: str
    frequency: str
    timezone: str
    next_run_at: datetime
    recipients: list[str]
    is_active: bool
    last_run_at: datetime | None = None
    last_status: str
    created_by: UUID | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ComplianceReportJobResponse(BaseModel):
    job_id: UUID
    framework: str
    format: str
    report_status: str
    delivery_status: str
    filename: str | None = None
    media_type: str | None = None
    file_size: int | None = None
    error_report: str | None = None
    error_delivery: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    published_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    email_sent_at: datetime | None = None
    status_url: str
    download_url: str


def _job_response(job: ComplianceReportJob) -> ComplianceReportJobResponse:
    job_id = job.id
    return ComplianceReportJobResponse(
        job_id=job_id,
        framework=job.framework,
        format=job.format,
        report_status=job.report_status,
        delivery_status=job.delivery_status,
        filename=job.filename,
        media_type=job.media_type,
        file_size=job.file_size,
        error_report=job.error_report,
        error_delivery=job.error_delivery,
        created_at=job.created_at,
        updated_at=job.updated_at,
        published_at=job.published_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
        email_sent_at=job.email_sent_at,
        status_url=f"/api/v1/compliance/reports/{job_id}",
        download_url=f"/api/v1/compliance/reports/{job_id}/download",
    )


async def _get_owned_job(
    job_id: UUID,
    org_id: UUID,
    db: AsyncSession,
) -> ComplianceReportJob:
    job = (
        await db.execute(
            select(ComplianceReportJob).where(
                ComplianceReportJob.id == job_id,
                ComplianceReportJob.organization_id == org_id,
            )
        )
    ).scalar_one_or_none()
    if job is None:
        raise HTTPException(status_code=404, detail="Compliance report job not found")
    return job


@router.post(
    "/reports",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Enqueue async compliance report generation",
)
@rate_limit("10/hour")
@require_admin()
async def enqueue_compliance_report(
    request: Request,
    payload: ComplianceReportEnqueueRequest,
    current_user: User = Depends(get_current_active_user),
    org_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    if payload.framework not in SUPPORTED_FRAMEWORKS:
        raise HTTPException(status_code=422, detail=f"Unsupported framework '{payload.framework}'")
    if payload.format not in SUPPORTED_FORMATS:
        raise HTTPException(status_code=422, detail=f"Unsupported format '{payload.format}'")

    job = ComplianceReportJob(
        organization_id=org_id,
        requested_by=current_user.id,
        framework=payload.framework,
        format=payload.format,
        recipients=[current_user.email],
        report_status="queued",
        delivery_status="pending",
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)
    return _job_response(job)


def _schedule_response(schedule: ScheduledComplianceReport) -> ScheduledComplianceReportResponse:
    return ScheduledComplianceReportResponse(
        id=schedule.id,
        organization_id=schedule.organization_id,
        name=schedule.name,
        framework=schedule.framework,
        format=schedule.format,
        frequency=schedule.frequency,
        timezone=schedule.timezone,
        next_run_at=schedule.next_run_at,
        recipients=list(schedule.recipients or []),
        is_active=schedule.is_active,
        last_run_at=schedule.last_run_at,
        last_status=schedule.last_status,
        created_by=schedule.created_by,
        created_at=schedule.created_at,
        updated_at=schedule.updated_at,
    )


def _normalize_recipients(recipients: list[str]) -> list[str]:
    normalized: list[str] = []
    for recipient in recipients:
        value = recipient.strip().lower()
        if not value or "@" not in value or value.startswith("@") or value.endswith("@"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid recipient email '{recipient}'",
            )
        if value not in normalized:
            normalized.append(value)
    return normalized


def _validate_schedule_timezone(timezone_name: str) -> None:
    try:
        ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown IANA timezone '{timezone_name}'",
        )


def _validate_next_run_at_future(next_run_at: datetime) -> None:
    if next_run_at.tzinfo is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="next_run_at must include a timezone offset",
        )
    if next_run_at <= datetime.now(timezone.utc):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="next_run_at must be in the future",
        )


def _validate_active_schedule_requirements(
    *,
    is_active: bool,
    recipients: list[str],
    next_run_at: datetime,
) -> None:
    if is_active and not settings.COMPLIANCE_REPORT_EMAIL_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Compliance report email delivery is disabled",
        )
    if is_active and not settings.SMTP_HOST:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Company SMTP is not configured",
        )
    if is_active and not recipients:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one recipient is required for an active schedule",
        )
    if is_active and next_run_at <= datetime.now(timezone.utc):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="An active schedule cannot have next_run_at in the past",
        )


async def _validate_admin_recipients(
    db: AsyncSession,
    org_id: UUID,
    recipients: list[str],
) -> None:
    if not recipients:
        return
    admin_emails = set(
        (
            await db.execute(
                select(User.email).where(
                    User.organization_id == org_id,
                    User.role == "admin",
                    User.is_active == True,  # noqa: E712
                    User.email.in_(recipients),
                )
            )
        ).scalars().all()
    )
    missing = sorted(set(recipients) - admin_emails)
    if missing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Scheduled report recipients must be active admins in this "
                f"organization: {', '.join(missing)}"
            ),
        )


async def _audit_schedule_action(
    *,
    action: str,
    schedule: ScheduledComplianceReport,
    actor_id: UUID,
    details: dict | None = None,
) -> None:
    payload = {
        "framework": schedule.framework,
        "format": schedule.format,
        "frequency": schedule.frequency,
        "is_active": schedule.is_active,
    }
    if details:
        payload.update(details)
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(
                text("SELECT set_config('app.current_org_id', :org, true)"),
                {"org": str(schedule.organization_id)},
            )
            await session.execute(
                text(
                    """
                    INSERT INTO audit_logs
                        (id, timestamp, user_id, organization_id, action,
                         resource_type, resource_id, details)
                    VALUES
                        (:id, now(), :user_id, :organization_id, :action,
                         'compliance_report_schedule', :resource_id,
                         CAST(:details AS JSONB))
                    """
                ),
                {
                    "id": str(uuid.uuid4()),
                    "user_id": str(actor_id),
                    "organization_id": str(schedule.organization_id),
                    "action": action,
                    "resource_id": str(schedule.id),
                    "details": json.dumps(payload),
                },
            )
            await session.commit()
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "compliance_report_schedule_audit_failed",
            action=action,
            schedule_id=str(schedule.id),
            error=str(exc),
        )


async def _get_owned_schedule(
    schedule_id: UUID,
    org_id: UUID,
    db: AsyncSession,
) -> ScheduledComplianceReport:
    schedule = (
        await db.execute(
            select(ScheduledComplianceReport).where(
                ScheduledComplianceReport.id == schedule_id,
                ScheduledComplianceReport.organization_id == org_id,
            )
        )
    ).scalar_one_or_none()
    if schedule is None:
        raise HTTPException(status_code=404, detail="Compliance report schedule not found")
    return schedule


@router.get(
    "/reports/schedules",
    summary="List scheduled compliance report definitions",
)
@rate_limit("100/minute")
@require_admin()
async def list_compliance_report_schedules(
    request: Request,
    current_user: User = Depends(get_current_active_user),
    org_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    schedules = (
        await db.execute(
            select(ScheduledComplianceReport)
            .where(ScheduledComplianceReport.organization_id == org_id)
            .order_by(ScheduledComplianceReport.created_at.desc())
        )
    ).scalars().all()
    return {"items": [_schedule_response(schedule) for schedule in schedules]}


@router.post(
    "/reports/schedules",
    status_code=status.HTTP_201_CREATED,
    summary="Create a scheduled compliance report definition",
)
@rate_limit("20/hour")
@require_admin()
async def create_compliance_report_schedule(
    request: Request,
    payload: ScheduledComplianceReportCreate,
    current_user: User = Depends(get_current_active_user),
    org_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    if payload.framework not in SUPPORTED_FRAMEWORKS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"framework must be one of: {', '.join(sorted(SUPPORTED_FRAMEWORKS))}",
        )
    if payload.format not in SUPPORTED_FORMATS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"format must be one of: {', '.join(sorted(SUPPORTED_FORMATS))}",
        )
    if payload.frequency not in SCHEDULE_FREQUENCIES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"frequency must be one of: {', '.join(sorted(SCHEDULE_FREQUENCIES))}",
        )
    _validate_schedule_timezone(payload.timezone)
    _validate_next_run_at_future(payload.next_run_at)
    recipients = _normalize_recipients(payload.recipients)
    _validate_active_schedule_requirements(
        is_active=payload.is_active,
        recipients=recipients,
        next_run_at=payload.next_run_at,
    )
    await _validate_admin_recipients(db, org_id, recipients)

    schedule = ScheduledComplianceReport(
        organization_id=org_id,
        name=payload.name.strip(),
        framework=payload.framework,
        format=payload.format,
        frequency=payload.frequency,
        timezone=payload.timezone,
        next_run_at=payload.next_run_at,
        recipients=recipients,
        is_active=payload.is_active,
        created_by=current_user.id,
    )
    db.add(schedule)
    await db.commit()
    await db.refresh(schedule)
    await _audit_schedule_action(
        action="compliance_report_schedule_created",
        schedule=schedule,
        actor_id=current_user.id,
    )
    return _schedule_response(schedule)


@router.get(
    "/reports/schedules/{schedule_id}",
    summary="Get a scheduled compliance report definition",
)
@rate_limit("100/minute")
@require_admin()
async def get_compliance_report_schedule(
    schedule_id: UUID,
    request: Request,
    current_user: User = Depends(get_current_active_user),
    org_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    schedule = await _get_owned_schedule(schedule_id, org_id, db)
    return _schedule_response(schedule)


@router.put(
    "/reports/schedules/{schedule_id}",
    summary="Update a scheduled compliance report definition",
)
@rate_limit("20/hour")
@require_admin()
async def update_compliance_report_schedule(
    schedule_id: UUID,
    payload: ScheduledComplianceReportUpdate,
    request: Request,
    current_user: User = Depends(get_current_active_user),
    org_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    schedule = await _get_owned_schedule(schedule_id, org_id, db)
    updates = payload.model_dump(exclude_unset=True)

    framework = updates.get("framework", schedule.framework)
    report_format = updates.get("format", schedule.format)
    frequency = updates.get("frequency", schedule.frequency)
    timezone_name = updates.get("timezone", schedule.timezone)
    next_run_at = updates.get("next_run_at", schedule.next_run_at)
    recipients = updates.get("recipients", schedule.recipients or [])
    is_active = updates.get("is_active", schedule.is_active)

    if framework not in SUPPORTED_FRAMEWORKS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"framework must be one of: {', '.join(sorted(SUPPORTED_FRAMEWORKS))}",
        )
    if report_format not in SUPPORTED_FORMATS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"format must be one of: {', '.join(sorted(SUPPORTED_FORMATS))}",
        )
    if frequency not in SCHEDULE_FREQUENCIES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"frequency must be one of: {', '.join(sorted(SCHEDULE_FREQUENCIES))}",
        )
    _validate_schedule_timezone(timezone_name)
    if "next_run_at" in updates:
        _validate_next_run_at_future(next_run_at)
    recipients = _normalize_recipients(recipients)
    _validate_active_schedule_requirements(
        is_active=is_active,
        recipients=recipients,
        next_run_at=next_run_at,
    )
    await _validate_admin_recipients(db, org_id, recipients)

    if "name" in updates:
        schedule.name = updates["name"].strip()
    schedule.framework = framework
    schedule.format = report_format
    schedule.frequency = frequency
    schedule.timezone = timezone_name
    schedule.next_run_at = next_run_at
    schedule.recipients = recipients
    schedule.is_active = is_active
    schedule.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await _audit_schedule_action(
        action="compliance_report_schedule_updated",
        schedule=schedule,
        actor_id=current_user.id,
    )
    return _schedule_response(schedule)


@router.delete(
    "/reports/schedules/{schedule_id}",
    summary="Delete a scheduled compliance report definition",
)
@rate_limit("20/hour")
@require_admin()
async def delete_compliance_report_schedule(
    schedule_id: UUID,
    request: Request,
    current_user: User = Depends(get_current_active_user),
    org_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    schedule = await _get_owned_schedule(schedule_id, org_id, db)
    audit_schedule = ScheduledComplianceReport(
        id=schedule.id,
        organization_id=schedule.organization_id,
        name=schedule.name,
        framework=schedule.framework,
        format=schedule.format,
        frequency=schedule.frequency,
        timezone=schedule.timezone,
        next_run_at=schedule.next_run_at,
        recipients=list(schedule.recipients or []),
        is_active=schedule.is_active,
        last_run_at=schedule.last_run_at,
        last_status=schedule.last_status,
        created_by=schedule.created_by,
        created_at=schedule.created_at,
        updated_at=schedule.updated_at,
    )
    await db.delete(schedule)
    await db.commit()
    await _audit_schedule_action(
        action="compliance_report_schedule_deleted",
        schedule=audit_schedule,
        actor_id=current_user.id,
    )
    return {"deleted": str(schedule_id)}


@router.get(
    "/reports/{job_id}",
    summary="Get compliance report job status",
)
@rate_limit("100/minute")
@require_roles("admin", "viewer")
async def get_compliance_report_job(
    job_id: UUID,
    request: Request,
    current_user: User = Depends(get_current_active_user),
    org_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    job = await _get_owned_job(job_id, org_id, db)
    return _job_response(job)


@router.get(
    "/reports/{job_id}/download",
    summary="Download a completed compliance report",
)
@rate_limit("100/minute")
@require_roles("admin", "viewer")
async def download_compliance_report(
    job_id: UUID,
    request: Request,
    current_user: User = Depends(get_current_active_user),
    org_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    job = await _get_owned_job(job_id, org_id, db)
    if job.report_status != "completed":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Report is {job.report_status}, not ready",
        )
    if not job.file_path:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="Report file no longer available",
        )
    try:
        absolute = absolute_report_path(
            job.file_path,
            organization_id=org_id,
            job_id=job.id,
        )
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="Report file no longer available",
        )
    if not report_file_matches_metadata(
        absolute,
        expected_sha256=job.file_sha256,
        expected_size=job.file_size,
    ):
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="Report file no longer available or failed integrity validation",
        )
    return _secure_file_response(
        absolute,
        job.media_type or "application/octet-stream",
        job.filename or absolute.name,
    )


@public_router.get(
    "/reports/{job_id}/signed-download",
    summary="Download a compliance report via a time-limited signed link",
)
@rate_limit("10/minute")
async def download_compliance_report_signed(
    job_id: UUID,
    request: Request,
    token: str | None = Query(None),
):
    if not token:
        await audit_compliance_report_download(
            request=request,
            succeeded=False,
            job_id=job_id,
            organization_id=None,
            reason="missing_token",
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=INVALID_LINK_DETAIL,
        )

    verified = None
    rejection_reason = "invalid_signature_or_expired"
    try:
        verified = verify_signed_download_token(
            token,
            PURPOSE_COMPLIANCE_REPORT,
            job_id,
        )
    except SignedTokenError as exc:
        rejection_reason = exc.reason
        await audit_compliance_report_download(
            request=request,
            succeeded=False,
            job_id=job_id,
            organization_id=None,
            reason=rejection_reason,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=INVALID_LINK_DETAIL,
        )

    org_id = verified.organization_id
    async with AsyncSessionLocal() as session:
        async with session.begin():
            await session.execute(
                text("SELECT set_config('app.current_org_id', :org, true)"),
                {"org": str(org_id)},
            )
            job = (
                await session.execute(
                    select(ComplianceReportJob).where(
                        ComplianceReportJob.id == job_id,
                        ComplianceReportJob.organization_id == org_id,
                    )
                )
            ).scalar_one_or_none()

    if job is None:
        await audit_compliance_report_download(
            request=request,
            succeeded=False,
            job_id=job_id,
            organization_id=org_id,
            reason="job_not_found",
            token_version=verified.token_version,
            purpose=verified.purpose,
            token_id=verified.token_id,
        )
        raise HTTPException(status_code=404, detail="Compliance report job not found")

    if job.report_status != "completed":
        await audit_compliance_report_download(
            request=request,
            succeeded=False,
            job_id=job_id,
            organization_id=org_id,
            reason="report_not_complete",
            token_version=verified.token_version,
            purpose=verified.purpose,
            token_id=verified.token_id,
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Report is {job.report_status}, not ready",
        )

    if not job.file_path:
        await audit_compliance_report_download(
            request=request,
            succeeded=False,
            job_id=job_id,
            organization_id=org_id,
            reason="file_missing",
            token_version=verified.token_version,
            purpose=verified.purpose,
            token_id=verified.token_id,
        )
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="Report file no longer available",
        )

    try:
        absolute = absolute_report_path(
            job.file_path,
            organization_id=org_id,
            job_id=job.id,
        )
    except Exception:
        await audit_compliance_report_download(
            request=request,
            succeeded=False,
            job_id=job_id,
            organization_id=org_id,
            reason="unsafe_path",
            token_version=verified.token_version,
            purpose=verified.purpose,
            token_id=verified.token_id,
        )
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="Report file no longer available",
        )

    if not report_file_matches_metadata(
        absolute,
        expected_sha256=job.file_sha256,
        expected_size=job.file_size,
    ):
        await audit_compliance_report_download(
            request=request,
            succeeded=False,
            job_id=job_id,
            organization_id=org_id,
            reason="integrity_mismatch",
            token_version=verified.token_version,
            purpose=verified.purpose,
            token_id=verified.token_id,
        )
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="Report file no longer available",
        )

    await audit_compliance_report_download(
        request=request,
        succeeded=True,
        job_id=job_id,
        organization_id=org_id,
        reason="ok",
        token_version=verified.token_version,
        purpose=verified.purpose,
        token_id=verified.token_id,
    )
    return _secure_file_response(
        absolute,
        job.media_type or "application/octet-stream",
        job.filename or absolute.name,
    )

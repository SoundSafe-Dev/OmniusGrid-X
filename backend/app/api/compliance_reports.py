"""Async compliance report generation API (Task 7 — independent router)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_active_user
from app.db.models import ComplianceReportJob, User
from app.middleware.rbac import require_admin
from app.middleware.rate_limit import rate_limit
from app.middleware.tenant_isolation import get_tenant_db, get_tenant_org_id
from app.db.database import AsyncSessionLocal
from app.services.compliance_report_service import (
    SUPPORTED_FORMATS,
    SUPPORTED_FRAMEWORKS,
    absolute_report_path,
    report_file_matches_metadata,
)
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


@router.get(
    "/reports/{job_id}",
    summary="Get compliance report job status",
)
@rate_limit("100/minute")
@require_admin()
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
@require_admin()
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

"""Data export API (Task 5).

On-demand exports for the frontend ``ExportButton``:

  * ``GET /telemetry/{asset_id}``          - telemetry CSV, date-range filtered.
                                             Streams inline; switches to an async
                                             Redis job above ``SYNC_ROW_CAP`` rows.
  * ``GET /kanban/tasks``                  - Kanban tasks as Excel (.xlsx).
  * ``GET /registries``                    - registries as Excel (.xlsx).
  * ``GET /registries/{id}/items``         - one registry's items as Excel (.xlsx).
  * ``GET /oee/{asset_id}``                - single-asset OEE report (PDF).
  * ``GET /oee/summary``                   - fleet OEE summary (PDF).
  * ``GET /jobs/{job_id}``                 - async export job status/progress.
  * ``GET /jobs/{job_id}/download``        - download a finished async export.

Every endpoint accepts an optional ``columns`` query param (an ordered subset of
the resource's allowlist) — the on-demand half of "export templates with custom
column selection". Tenancy mirrors each domain's read endpoint; the organization is
always derived from the authenticated user, never client input.

Saved templates and daily/weekly/monthly schedules are persisted in Postgres. A
database outbox publishes due runs to Redpanda; the export worker generates the
file in shared storage and sends an authenticated, time-limited link via company
SMTP.
"""

import os
from pathlib import Path
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, status
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_active_user
from app.api.telemetry import _verify_asset_in_org
from app.core.config import settings
from app.core.tenant import get_tenant_db, get_tenant_org_id
from app.db.database import AsyncSessionLocal, get_db
from app.db.models import (
    ActionableRegistry,
    Asset,
    ExportDeliveryJob,
    ExportTemplate,
    ScheduledExport,
    User,
)
from app.middleware.rate_limit import rate_limit
from app.middleware.rbac import require_admin
from app.services.report_download_audit import audit_export_delivery_download
from app.utils.signed_urls import (
    PURPOSE_EXPORT,
    SignedTokenError,
    verify_signed_download_token,
)
from app.services.export_store import get_export_store, export_object_key
from app.services.export_processor import (
    EXPORT_DEFINITIONS,
    ExportError,
    MAX_EXPORT_ROWS,
    REGISTRY_COLUMNS,
    REGISTRY_ITEM_COLUMNS,
    SYNC_ROW_CAP,
    TASK_COLUMNS,
    TELEMETRY_COLUMNS,
    export_processor,
    select_columns,
    validate_export_configuration,
)
from app.services.oee_calculator import oee_calculator

logger = structlog.get_logger()

router = APIRouter(dependencies=[Depends(require_admin)])

# Signature-authorized routes: the time-limited signed link IS the credential, so
# these endpoints carry no bearer/admin dependency and work directly from an email
# client. Kept on a separate router so the admin dependency above can't apply.
public_router = APIRouter()

INVALID_LINK_DETAIL = "Invalid or expired download link"


_DOWNLOAD_SECURITY_HEADERS = {
    "Cache-Control": "private, no-store",
    "Pragma": "no-cache",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
}


def _secure_file_response(path, media_type: str, filename: str) -> FileResponse:
    response = FileResponse(path, media_type=media_type, filename=filename)
    response.headers.update(_DOWNLOAD_SECURITY_HEADERS)
    return response


def _secure_streaming_response(stream, media_type: str, filename: str) -> StreamingResponse:
    """Stream a download straight from object storage with the same hardening as
    the local file response (used when EXPORT_USE_S3 is on and the artifact lives
    in S3, not on this pod's disk)."""
    response = StreamingResponse(stream, media_type=media_type)
    response.headers.update(_DOWNLOAD_SECURITY_HEADERS)
    response.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


def _resolve_export_delivery_path(file_path: str, job_id: UUID) -> Path:
    root = Path(settings.EXPORT_STORAGE_PATH).resolve()
    absolute = Path(file_path).resolve()
    if not absolute.is_relative_to(root):
        raise ValueError("export path escapes storage root")
    if absolute.stem != str(job_id):
        raise ValueError("export path does not match job id")
    return absolute

XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
SCHEDULE_FREQUENCIES = {"daily", "weekly", "monthly"}


def _disposition(filename: str) -> dict:
    return {"Content-Disposition": f'attachment; filename="{filename}"'}


def _as_utc(dt: datetime) -> datetime:
    """Coerce a datetime to timezone-aware UTC.

    Query-string datetimes may arrive aware (``...+00:00``) or naive; mixing the
    two in a comparison raises ``TypeError``. Naive values are assumed UTC.
    """
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _stamp(dt: datetime) -> str:
    return dt.strftime("%Y%m%dT%H%M%S")


def _job_accepted(job: dict) -> dict:
    return {
        "job_id": job["job_id"],
        "type": job["type"],
        "status": job["status"],
        "total": job["total"],
        "status_url": f"/api/v1/exports/jobs/{job['job_id']}",
        "download_url": f"/api/v1/exports/jobs/{job['job_id']}/download",
    }


def _job_public(job: dict) -> dict:
    """Job view for the client — omits the server-side ``file_path``."""
    public = {
        k: job.get(k)
        for k in (
            "job_id", "type", "status", "total", "processed", "succeeded",
            "failed", "filename", "created_at", "updated_at",
        )
    }
    public["errors"] = job.get("errors", [])
    public["download_url"] = f"/api/v1/exports/jobs/{job['job_id']}/download"
    return public


async def _create_job_or_503(*args, **kwargs) -> dict:
    try:
        return await export_processor.create_job(*args, **kwargs)
    except Exception as exc:  # noqa: BLE001
        logger.error("export_job_store_unavailable", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Export job store unavailable",
        )


def _columns_or_400(allowlist, requested) -> list[str]:
    try:
        return select_columns(allowlist, requested)
    except ExportError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


class ExportTemplateCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    export_type: str
    export_format: str
    columns: list[str] = Field(default_factory=list)
    filters: dict[str, Any] = Field(default_factory=dict)


class ExportTemplateUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    export_type: Optional[str] = None
    export_format: Optional[str] = None
    columns: Optional[list[str]] = None
    filters: Optional[dict[str, Any]] = None


class ScheduledExportCreate(BaseModel):
    template_id: UUID
    name: str = Field(..., min_length=1, max_length=255)
    frequency: str
    timezone: str = "UTC"
    next_run_at: datetime
    recipients: list[str] = Field(default_factory=list)
    is_active: bool = False


class ScheduledExportUpdate(BaseModel):
    template_id: Optional[UUID] = None
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    frequency: Optional[str] = None
    timezone: Optional[str] = None
    next_run_at: Optional[datetime] = None
    recipients: Optional[list[str]] = None
    is_active: Optional[bool] = None


def _template_dict(template: ExportTemplate) -> dict[str, Any]:
    return {
        "id": str(template.id),
        "organization_id": str(template.organization_id),
        "name": template.name,
        "description": template.description,
        "export_type": template.export_type,
        "export_format": template.export_format,
        "columns": template.columns or [],
        "filters": template.filters or {},
        "created_by": str(template.created_by) if template.created_by else None,
        "created_at": template.created_at,
        "updated_at": template.updated_at,
    }


def _schedule_dict(schedule: ScheduledExport) -> dict[str, Any]:
    return {
        "id": str(schedule.id),
        "organization_id": str(schedule.organization_id),
        "template_id": str(schedule.template_id),
        "name": schedule.name,
        "frequency": schedule.frequency,
        "timezone": schedule.timezone,
        "next_run_at": schedule.next_run_at,
        "recipients": schedule.recipients or [],
        "is_active": schedule.is_active,
        "last_run_at": schedule.last_run_at,
        "last_status": schedule.last_status,
        "created_by": str(schedule.created_by) if schedule.created_by else None,
        "created_at": schedule.created_at,
        "updated_at": schedule.updated_at,
    }


def _validated_template_config(
    export_type: str,
    export_format: str,
    columns: Optional[list[str]],
    filters: Optional[dict[str, Any]],
) -> tuple[list[str], dict[str, Any]]:
    try:
        return validate_export_configuration(
            export_type, export_format, columns, filters
        )
    except ExportError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


def _validate_schedule_fields(
    frequency: str,
    timezone_name: str,
    next_run_at: datetime,
    recipients: list[str],
    is_active: bool,
) -> list[str]:
    if frequency not in SCHEDULE_FREQUENCIES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"frequency must be one of: {', '.join(sorted(SCHEDULE_FREQUENCIES))}",
        )
    try:
        ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown IANA timezone '{timezone_name}'",
        )
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
    normalized = []
    for recipient in recipients:
        value = recipient.strip().lower()
        if not value or "@" not in value or value.startswith("@") or value.endswith("@"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid recipient email '{recipient}'",
            )
        if value not in normalized:
            normalized.append(value)
    if is_active and not settings.SMTP_HOST:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Company SMTP is not configured",
        )
    if is_active and not normalized:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one recipient is required for an active schedule",
        )
    return normalized


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


# --- Saved templates ----------------------------------------------------------
@router.get("/definitions", summary="List supported export template definitions")
async def list_export_definitions(
    _: User = Depends(get_current_active_user),
):
    return {
        key: {
            "format": value["format"],
            "columns": value["columns"],
            "filters": sorted(value["filters"]),
            "required_filters": sorted(value["required_filters"]),
        }
        for key, value in EXPORT_DEFINITIONS.items()
    }


@router.get("/templates", summary="List saved export templates")
async def list_export_templates(
    org_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    result = await db.execute(
        select(ExportTemplate)
        .where(ExportTemplate.organization_id == org_id)
        .order_by(ExportTemplate.name.asc())
    )
    items = [_template_dict(item) for item in result.scalars().all()]
    return {"items": items, "total": len(items)}


@router.post(
    "/templates",
    status_code=status.HTTP_201_CREATED,
    summary="Create a saved export template",
)
async def create_export_template(
    payload: ExportTemplateCreate,
    org_id: UUID = Depends(get_tenant_org_id),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_tenant_db),
):
    columns, filters = _validated_template_config(
        payload.export_type,
        payload.export_format,
        payload.columns,
        payload.filters,
    )
    template = ExportTemplate(
        organization_id=org_id,
        name=payload.name.strip(),
        description=payload.description,
        export_type=payload.export_type,
        export_format=payload.export_format,
        columns=columns,
        filters=filters,
        created_by=current_user.id,
    )
    db.add(template)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"An export template named '{template.name}' already exists",
        )
    await db.refresh(template)
    return _template_dict(template)


@router.get("/templates/{template_id}", summary="Get a saved export template")
async def get_export_template(
    template_id: UUID,
    org_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    template = (
        await db.execute(
            select(ExportTemplate).where(
                ExportTemplate.id == template_id,
                ExportTemplate.organization_id == org_id,
            )
        )
    ).scalar_one_or_none()
    if template is None:
        raise HTTPException(status_code=404, detail="Export template not found")
    return _template_dict(template)


@router.put("/templates/{template_id}", summary="Update a saved export template")
async def update_export_template(
    template_id: UUID,
    payload: ExportTemplateUpdate,
    org_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    template = (
        await db.execute(
            select(ExportTemplate).where(
                ExportTemplate.id == template_id,
                ExportTemplate.organization_id == org_id,
            )
        )
    ).scalar_one_or_none()
    if template is None:
        raise HTTPException(status_code=404, detail="Export template not found")

    updates = payload.model_dump(exclude_unset=True)
    export_type = updates.get("export_type", template.export_type)
    export_format = updates.get("export_format", template.export_format)
    columns = updates.get("columns", template.columns)
    filters = updates.get("filters", template.filters)
    columns, filters = _validated_template_config(
        export_type, export_format, columns, filters
    )

    if "name" in updates:
        template.name = updates["name"].strip()
    if "description" in updates:
        template.description = updates["description"]
    template.export_type = export_type
    template.export_format = export_format
    template.columns = columns
    template.filters = filters
    template.updated_at = datetime.now(timezone.utc)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"An export template named '{template.name}' already exists",
        )
    await db.refresh(template)
    return _template_dict(template)


@router.delete("/templates/{template_id}", summary="Delete a saved export template")
async def delete_export_template(
    template_id: UUID,
    org_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    template = (
        await db.execute(
            select(ExportTemplate).where(
                ExportTemplate.id == template_id,
                ExportTemplate.organization_id == org_id,
            )
        )
    ).scalar_one_or_none()
    if template is None:
        raise HTTPException(status_code=404, detail="Export template not found")
    schedules = (
        await db.execute(
            select(ScheduledExport).where(
                ScheduledExport.template_id == template_id,
                ScheduledExport.organization_id == org_id,
            )
        )
    ).scalars().all()
    for schedule in schedules:
        await db.delete(schedule)
    await db.flush()
    await db.delete(template)
    await db.commit()
    return {"deleted": str(template_id)}


# --- Schedule definitions -----------------------------------------------------
@router.get("/schedules", summary="List scheduled export definitions")
async def list_scheduled_exports(
    org_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    result = await db.execute(
        select(ScheduledExport)
        .where(ScheduledExport.organization_id == org_id)
        .order_by(ScheduledExport.next_run_at.asc())
    )
    items = [_schedule_dict(item) for item in result.scalars().all()]
    return {
        "items": items,
        "total": len(items),
        "delivery_configured": bool(settings.SMTP_HOST),
    }


@router.post(
    "/schedules",
    status_code=status.HTTP_201_CREATED,
    summary="Create a scheduled export definition",
)
async def create_scheduled_export(
    payload: ScheduledExportCreate,
    org_id: UUID = Depends(get_tenant_org_id),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_tenant_db),
):
    template = (
        await db.execute(
            select(ExportTemplate).where(
                ExportTemplate.id == payload.template_id,
                ExportTemplate.organization_id == org_id,
            )
        )
    ).scalar_one_or_none()
    if template is None:
        raise HTTPException(status_code=404, detail="Export template not found")
    recipients = _validate_schedule_fields(
        payload.frequency,
        payload.timezone,
        payload.next_run_at,
        payload.recipients,
        payload.is_active,
    )
    await _validate_admin_recipients(db, org_id, recipients)
    schedule = ScheduledExport(
        organization_id=org_id,
        template_id=payload.template_id,
        name=payload.name.strip(),
        frequency=payload.frequency,
        timezone=payload.timezone,
        next_run_at=payload.next_run_at,
        recipients=recipients,
        is_active=payload.is_active,
        last_status="never_run",
        created_by=current_user.id,
    )
    db.add(schedule)
    await db.commit()
    return _schedule_dict(schedule)


@router.get("/schedules/{schedule_id}", summary="Get a scheduled export definition")
async def get_scheduled_export(
    schedule_id: UUID,
    org_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    schedule = (
        await db.execute(
            select(ScheduledExport).where(
                ScheduledExport.id == schedule_id,
                ScheduledExport.organization_id == org_id,
            )
        )
    ).scalar_one_or_none()
    if schedule is None:
        raise HTTPException(status_code=404, detail="Scheduled export not found")
    return _schedule_dict(schedule)


@router.put("/schedules/{schedule_id}", summary="Update a scheduled export definition")
async def update_scheduled_export(
    schedule_id: UUID,
    payload: ScheduledExportUpdate,
    org_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    schedule = (
        await db.execute(
            select(ScheduledExport).where(
                ScheduledExport.id == schedule_id,
                ScheduledExport.organization_id == org_id,
            )
        )
    ).scalar_one_or_none()
    if schedule is None:
        raise HTTPException(status_code=404, detail="Scheduled export not found")

    updates = payload.model_dump(exclude_unset=True)
    template_id = updates.get("template_id", schedule.template_id)
    template = (
        await db.execute(
            select(ExportTemplate).where(
                ExportTemplate.id == template_id,
                ExportTemplate.organization_id == org_id,
            )
        )
    ).scalar_one_or_none()
    if template is None:
        raise HTTPException(status_code=404, detail="Export template not found")

    frequency = updates.get("frequency", schedule.frequency)
    timezone_name = updates.get("timezone", schedule.timezone)
    next_run_at = updates.get("next_run_at", schedule.next_run_at)
    recipients = updates.get("recipients", schedule.recipients or [])
    is_active = updates.get("is_active", schedule.is_active)
    recipients = _validate_schedule_fields(
        frequency, timezone_name, next_run_at, recipients, is_active
    )
    await _validate_admin_recipients(db, org_id, recipients)

    schedule.template_id = template_id
    if "name" in updates:
        schedule.name = updates["name"].strip()
    schedule.frequency = frequency
    schedule.timezone = timezone_name
    schedule.next_run_at = next_run_at
    schedule.recipients = recipients
    schedule.is_active = is_active
    schedule.updated_at = datetime.now(timezone.utc)
    await db.commit()
    return _schedule_dict(schedule)


@router.delete("/schedules/{schedule_id}", summary="Delete a scheduled export definition")
async def delete_scheduled_export(
    schedule_id: UUID,
    org_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    schedule = (
        await db.execute(
            select(ScheduledExport).where(
                ScheduledExport.id == schedule_id,
                ScheduledExport.organization_id == org_id,
            )
        )
    ).scalar_one_or_none()
    if schedule is None:
        raise HTTPException(status_code=404, detail="Scheduled export not found")
    await db.delete(schedule)
    await db.commit()
    return {"deleted": str(schedule_id)}


# --- Telemetry (CSV) ----------------------------------------------------------
@router.get("/telemetry/{asset_id}", responses={200: {"content": {"text/csv": {}}}}, summary="Export telemetry as CSV (date-range filtered)")
async def export_telemetry_csv(
    asset_id: UUID,
    background_tasks: BackgroundTasks,
    metric_name: Optional[str] = Query(None, description="Restrict to one metric"),
    start_time: Optional[datetime] = Query(None),
    end_time: Optional[datetime] = Query(None),
    columns: Optional[str] = Query(None, description="Ordered subset of telemetry columns"),
    org_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
    current_user: User = Depends(get_current_active_user),
):
    """Stream an asset's telemetry as CSV (defaults to the last 24h).

    Streams inline for normal ranges; for a range exceeding ``SYNC_ROW_CAP`` rows it
    returns ``202`` with a job id to poll, then downloaded from ``/jobs/{id}/download``.
    """
    # Normalize to aware UTC up front: the bounds may arrive aware (with an
    # offset) or naive, and comparing the two (or the naive utcnow default
    # against an aware bound) raises TypeError.
    now = datetime.now(timezone.utc)
    end_time = _as_utc(end_time) if end_time else now
    start_time = _as_utc(start_time) if start_time else end_time - timedelta(hours=24)
    if start_time > end_time:
        raise HTTPException(status_code=400, detail="start_time must be <= end_time")

    await _verify_asset_in_org(db, asset_id, org_id)
    cols = _columns_or_400(TELEMETRY_COLUMNS, columns)

    count = await export_processor.count_telemetry(
        db, asset_id, start_time, end_time, metric_name
    )
    if count > MAX_EXPORT_ROWS:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=(
                f"Export contains {count} rows; maximum is {MAX_EXPORT_ROWS}. "
                "Use a narrower date range or metric filter."
            ),
        )
    filename = f"telemetry_{asset_id}_{_stamp(start_time)}_{_stamp(end_time)}.csv"

    if count > SYNC_ROW_CAP:
        job = await _create_job_or_503(
            "export_telemetry", total=count, organization_id=org_id, actor_id=current_user.id
        )
        background_tasks.add_task(
            export_processor.run_telemetry_export,
            job["job_id"], org_id, asset_id, start_time, end_time, metric_name, cols,
            filename, current_user.id,
        )
        return JSONResponse(status_code=status.HTTP_202_ACCEPTED, content=_job_accepted(job))

    await export_processor.audit_sync_export("export_telemetry", org_id, current_user.id, count)
    return StreamingResponse(
        export_processor.stream_telemetry_csv(
            org_id, asset_id, start_time, end_time, metric_name, cols
        ),
        media_type="text/csv",
        headers=_disposition(filename),
    )


# --- Kanban tasks (Excel) -----------------------------------------------------
@router.get("/kanban/tasks", responses={200: {"content": {XLSX_MEDIA_TYPE: {}}}}, summary="Export Kanban tasks as Excel")
async def export_kanban_tasks(
    task_status: Optional[str] = Query(None, alias="status", description="Filter by task status"),
    columns: Optional[str] = Query(None, description="Ordered subset of task columns"),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_tenant_db),
):
    cols = _columns_or_400(TASK_COLUMNS, columns)
    content, n = await export_processor.export_tasks_xlsx(
        db, current_user.organization_id, cols, task_status
    )
    await export_processor.audit_sync_export(
        "export_kanban_tasks", current_user.organization_id, current_user.id, n
    )
    return Response(
        content=content, media_type=XLSX_MEDIA_TYPE,
        headers=_disposition(f"kanban_tasks_{_stamp(datetime.now(timezone.utc))}.xlsx"),
    )


# --- Registries (Excel) -------------------------------------------------------
@router.get("/registries", responses={200: {"content": {XLSX_MEDIA_TYPE: {}}}}, summary="Export registries as Excel")
async def export_registries(
    registry_type: Optional[str] = Query(None),
    columns: Optional[str] = Query(None, description="Ordered subset of registry columns"),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_tenant_db),
):
    cols = _columns_or_400(REGISTRY_COLUMNS, columns)
    content, n = await export_processor.export_registries_xlsx(
        db, current_user.organization_id, cols, registry_type
    )
    await export_processor.audit_sync_export(
        "export_registries", current_user.organization_id, current_user.id, n
    )
    return Response(
        content=content, media_type=XLSX_MEDIA_TYPE,
        headers=_disposition(f"registries_{_stamp(datetime.now(timezone.utc))}.xlsx"),
    )


@router.get("/registries/{registry_id}/items", responses={200: {"content": {XLSX_MEDIA_TYPE: {}}}}, summary="Export a registry's items as Excel")
async def export_registry_items(
    registry_id: UUID,
    columns: Optional[str] = Query(None, description="Ordered subset of registry-item columns"),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_tenant_db),
):
    registry = (
        await db.execute(
            select(ActionableRegistry).where(
                ActionableRegistry.id == registry_id,
                ActionableRegistry.organization_id == current_user.organization_id,
            )
        )
    ).scalar_one_or_none()
    if registry is None:
        raise HTTPException(status_code=404, detail="Registry not found")

    cols = _columns_or_400(REGISTRY_ITEM_COLUMNS, columns)
    content, n = await export_processor.export_registry_items_xlsx(db, registry_id, cols)
    await export_processor.audit_sync_export(
        "export_registry_items", current_user.organization_id, current_user.id, n
    )
    return Response(
        content=content, media_type=XLSX_MEDIA_TYPE,
        headers=_disposition(f"registry_{registry_id}_items.xlsx"),
    )


# --- OEE (PDF) ----------------------------------------------------------------
@router.get("/oee/summary", responses={200: {"content": {"application/pdf": {}}}}, summary="Export a fleet OEE summary as PDF")
async def export_oee_summary(
    time_window_hours: float = Query(24.0, ge=0.5, le=24),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_tenant_db),
):
    result = await db.execute(
        select(Asset).where(
            Asset.organization_id == current_user.organization_id,
            Asset.is_active == True,  # noqa: E712 - SQL boolean, not Python identity
        )
    )
    assets = result.scalars().all()
    rows = []
    for asset in assets:
        try:
            m = await oee_calculator.calculate_oee(
                str(asset.id), time_window_hours=time_window_hours
            )
            rows.append({
                "asset_name": asset.name,
                "oee": m.oee, "availability": m.availability,
                "performance": m.performance, "quality": m.quality,
                "runtime_minutes": m.runtime_minutes,
                "status": "healthy" if m.oee > 60 else "at_risk" if m.oee > 40 else "critical",
            })
        except Exception:  # noqa: BLE001 - one bad asset shouldn't fail the report
            # NOT ZEROS. This is a PDF someone files, prints or forwards, and a row
            # reading "0, 0, 0, 0" states that the machine produced nothing in the
            # window — a total outage — when the truth is that the calculation failed.
            # The status column said "no_data", but a reader scanning four numeric
            # columns has already drawn the conclusion. None renders as an em dash.
            # Same defect as /oee/dashboard/summary; found by sweeping for the shape
            # after fixing that one (method rule 18).
            rows.append({
                "asset_name": asset.name, "oee": None, "availability": None,
                "performance": None, "quality": None, "runtime_minutes": None,
                "status": "unavailable",
            })
    content = export_processor.build_oee_summary_pdf(rows)
    await export_processor.audit_sync_export(
        "export_oee_summary", current_user.organization_id, current_user.id, len(rows)
    )
    return Response(
        content=content, media_type="application/pdf",
        headers=_disposition(f"oee_summary_{_stamp(datetime.now(timezone.utc))}.pdf"),
    )


@router.get("/oee/{asset_id}", responses={200: {"content": {"application/pdf": {}}}}, summary="Export a single asset's OEE report as PDF")
async def export_oee_report(
    asset_id: UUID,
    time_window_hours: float = Query(1.0, ge=0.5, le=24),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_tenant_db),
):
    asset = (
        await db.execute(select(Asset).where(Asset.id == asset_id))
    ).scalar_one_or_none()
    if not asset or asset.organization_id != current_user.organization_id:
        raise HTTPException(status_code=404, detail="Asset not found")

    m = await oee_calculator.calculate_oee(str(asset_id), time_window_hours)
    content = export_processor.build_oee_pdf(asset.name, str(asset_id), time_window_hours, m)
    await export_processor.audit_sync_export(
        "export_oee", current_user.organization_id, current_user.id, 1
    )
    return Response(
        content=content, media_type="application/pdf",
        headers=_disposition(f"oee_{asset_id}.pdf"),
    )


# --- Async export jobs --------------------------------------------------------
async def _get_owned_job(job_id: str, current_user: User) -> dict:
    try:
        job = await export_processor.get_job(job_id)
    except Exception as exc:  # noqa: BLE001
        logger.error("export_job_store_unavailable", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Export job store unavailable",
        )
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found or expired")
    job_org = job.get("organization_id")
    user_org = str(current_user.organization_id) if current_user.organization_id else None
    if job_org and job_org != user_org:
        raise HTTPException(status_code=404, detail="Job not found or expired")
    return job


@router.get("/jobs/{job_id}", responses={200: {"content": {"text/csv": {}}}}, summary="Get an export job's status/progress")
async def get_export_job(job_id: str, current_user: User = Depends(get_current_active_user)):
    return _job_public(await _get_owned_job(job_id, current_user))


@router.get("/jobs/{job_id}/download", responses={200: {"content": {"text/csv": {}}}}, summary="Download a finished async export")
async def download_export_job(job_id: str, current_user: User = Depends(get_current_active_user)):
    job = await _get_owned_job(job_id, current_user)
    if job.get("status") != "completed":
        raise HTTPException(status_code=409, detail=f"Export is {job.get('status')}, not ready")
    path = job.get("file_path")
    if not path:
        raise HTTPException(status_code=410, detail="Export file no longer available")
    filename = job.get("filename") or "export.csv"
    # These async jobs are telemetry CSVs. When object storage is on, the file is
    # in S3 (a different pod generated it), so stream it from there.
    store = get_export_store()
    if store.enabled:
        key = export_object_key(str(job_id), filename.rsplit(".", 1)[-1] or "csv")
        if await store.exists(key):
            return _secure_streaming_response(store.download_stream(key), "text/csv", filename)
        raise HTTPException(status_code=410, detail="Export file no longer available")
    if not os.path.exists(path):
        raise HTTPException(status_code=410, detail="Export file no longer available")
    return FileResponse(path, media_type="text/csv", filename=filename)


@router.get("/deliveries", summary="List scheduled export delivery jobs")
async def list_export_deliveries(
    limit: int = Query(50, ge=1, le=200),
    org_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    jobs = (
        await db.execute(
            select(ExportDeliveryJob)
            .where(ExportDeliveryJob.organization_id == org_id)
            .order_by(ExportDeliveryJob.created_at.desc())
            .limit(limit)
        )
    ).scalars().all()
    return {
        "items": [
            {
                "id": str(job.id),
                "schedule_id": str(job.schedule_id),
                "status": job.status,
                "filename": job.filename,
                "error": job.error,
                "scheduled_for": job.scheduled_for,
                "completed_at": job.completed_at,
            }
            for job in jobs
        ]
    }


@public_router.get(
    "/deliveries/{job_id}/download",
    summary="Download a scheduled report via a time-limited signed link",
)
@rate_limit("10/minute")
async def download_scheduled_export(
    job_id: UUID,
    request: Request,
    signature: str | None = Query(None),
):
    """Capability-style download: the time-limited signature *is* the credential."""
    if not signature:
        await audit_export_delivery_download(
            request=request,
            succeeded=False,
            job_id=job_id,
            organization_id=None,
            reason="missing_signature",
        )
        raise HTTPException(status_code=403, detail=INVALID_LINK_DETAIL)

    verified = None
    rejection_reason = "invalid_signature_or_expired"
    try:
        verified = verify_signed_download_token(signature, PURPOSE_EXPORT, job_id)
    except SignedTokenError as exc:
        rejection_reason = exc.reason
        await audit_export_delivery_download(
            request=request,
            succeeded=False,
            job_id=job_id,
            organization_id=None,
            reason=rejection_reason,
        )
        raise HTTPException(status_code=403, detail=INVALID_LINK_DETAIL)

    org_id = verified.organization_id
    async with AsyncSessionLocal() as session:
        async with session.begin():
            await session.execute(
                text("SELECT set_config('app.current_org_id', :org, true)"),
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

    if job is None:
        await audit_export_delivery_download(
            request=request,
            succeeded=False,
            job_id=job_id,
            organization_id=org_id,
            reason="job_not_found",
            token_version=verified.token_version,
            purpose=verified.purpose,
            token_id=verified.token_id,
        )
        raise HTTPException(status_code=404, detail="Scheduled export not found")
    if job.status != "completed":
        await audit_export_delivery_download(
            request=request,
            succeeded=False,
            job_id=job_id,
            organization_id=org_id,
            reason="export_not_complete",
            token_version=verified.token_version,
            purpose=verified.purpose,
            token_id=verified.token_id,
        )
        raise HTTPException(status_code=409, detail=f"Export is {job.status}, not ready")
    if not job.file_path:
        await audit_export_delivery_download(
            request=request,
            succeeded=False,
            job_id=job_id,
            organization_id=org_id,
            reason="file_missing",
            token_version=verified.token_version,
            purpose=verified.purpose,
            token_id=verified.token_id,
        )
        raise HTTPException(status_code=410, detail="Export file no longer available")
    media_types = {
        "csv": "text/csv",
        "xlsx": XLSX_MEDIA_TYPE,
        "pdf": "application/pdf",
    }
    extension = (job.filename or job.file_path or "").rsplit(".", 1)[-1] or "csv"
    media_type = media_types.get(extension, "application/octet-stream")

    async def _audit(succeeded: bool, reason: str):
        await audit_export_delivery_download(
            request=request,
            succeeded=succeeded,
            job_id=job_id,
            organization_id=org_id,
            reason=reason,
            token_version=verified.token_version,
            purpose=verified.purpose,
            token_id=verified.token_id,
        )

    # Object-store path: the worker that generated this ran on a different pod,
    # so the artifact is in S3, not on this API pod's disk. Stream it from there.
    store = get_export_store()
    if store.enabled:
        key = export_object_key(str(job_id), extension)
        if not await store.exists(key):
            await _audit(False, "file_missing")
            raise HTTPException(status_code=410, detail="Export file no longer available")
        await _audit(True, "ok")
        return _secure_streaming_response(
            store.download_stream(key), media_type, job.filename or "report"
        )

    # Local-disk path (single-node / EXPORT_USE_S3 off).
    try:
        absolute = _resolve_export_delivery_path(job.file_path, job_id)
    except ValueError:
        await _audit(False, "unsafe_path")
        raise HTTPException(status_code=410, detail="Export file no longer available")
    if not absolute.is_file():
        await _audit(False, "file_missing")
        raise HTTPException(status_code=410, detail="Export file no longer available")
    await _audit(True, "ok")
    return _secure_file_response(absolute, media_type, job.filename or "report")

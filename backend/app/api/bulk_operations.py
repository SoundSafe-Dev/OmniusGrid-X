"""Bulk operations API (Task 7).

Comprehensive bulk operations with async job processing and progress tracking:
  * ``POST /assets/import``               - bulk create/update assets from CSV
  * ``POST /kanban/tasks/{operation}``    - bulk move/delete/assign Kanban tasks
  * ``POST /alarms/acknowledge``          - bulk acknowledge alarms
  * ``POST /registries/{id}/items``       - bulk create registry items
  * ``GET  /jobs/{job_id}``               - poll a job's status/progress

Each mutating endpoint validates its input synchronously (fast-fail on a bad
payload), creates a Redis-tracked job, schedules the work on a FastAPI
``BackgroundTask``, and returns ``202 Accepted`` with the job id. Progress and
per-row errors are then polled from the jobs endpoint.

Tenancy follows each domain's existing single-record endpoint (see
``bulk_processor`` for details); the organization is always derived from the
authenticated user, never from client input.
"""

from typing import Optional
from uuid import UUID

import structlog
from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    HTTPException,
    UploadFile,
    status,
)
from pydantic import BaseModel, Field

from app.api.auth import get_current_active_user
from app.core.tenant import get_tenant_org_id
from app.db.models import User
from app.services.bulk_processor import (
    BulkOperationError,
    bulk_processor,
    parse_asset_csv,
)

logger = structlog.get_logger()

router = APIRouter()

MAX_CSV_BYTES = 5 * 1024 * 1024  # 5 MB upload cap
MAX_ITEMS = 5000  # rows / ids / items per bulk request
KANBAN_OPERATIONS = {"move", "delete", "assign"}


def _job_accepted(job: dict) -> dict:
    """Shape the 202 response so the client knows where to poll."""
    return {
        "job_id": job["job_id"],
        "type": job["type"],
        "status": job["status"],
        "total": job["total"],
        "status_url": f"/api/v1/bulk/jobs/{job['job_id']}",
    }


async def _create_job_or_503(*args, **kwargs) -> dict:
    """Create a job, mapping a Redis outage to a clean 503 rather than a raw 500."""
    try:
        return await bulk_processor.create_job(*args, **kwargs)
    except Exception as exc:
        logger.error("bulk_job_store_unavailable", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Bulk job store unavailable",
        )


# --- Request models -----------------------------------------------------------
class KanbanBulkRequest(BaseModel):
    task_ids: list[str] = Field(..., min_length=1, description="Task ids to operate on")
    # move
    target_column_id: Optional[str] = Field(None, description="Target column (move)")
    position: Optional[int] = Field(None, description="Optional position in target column (move)")
    # assign
    assigned_to: Optional[str] = Field(None, description="User id to assign (assign)")


class AlarmBulkAckRequest(BaseModel):
    alarm_ids: list[str] = Field(..., min_length=1)
    comment: Optional[str] = None


class RegistryItemIn(BaseModel):
    item_code: str = Field(..., min_length=1)
    item_name: str = Field(..., min_length=1)
    item_description: Optional[str] = None
    severity_level: Optional[str] = None
    is_required: Optional[bool] = None
    is_active: Optional[bool] = None
    completion_criteria: Optional[str] = None
    verification_method: Optional[str] = None
    estimated_effort_minutes: Optional[int] = None
    completion_frequency: Optional[str] = None


class RegistryItemsBulkRequest(BaseModel):
    items: list[RegistryItemIn] = Field(..., min_length=1)


# --- Endpoints ----------------------------------------------------------------
@router.post(
    "/assets/import",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Bulk create/update assets from a CSV upload",
)
async def bulk_import_assets(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    org_id: UUID = Depends(get_tenant_org_id),
    current_user: User = Depends(get_current_active_user),
):
    """Upload a CSV to create or update assets in the caller's organization.

    Columns: ``id`` (present = update, absent = create), ``name``,
    ``serial_number``, ``vendor``, ``model``, ``is_active``, and the asset type /
    workcell as either a name (``asset_type`` / ``workcell``) or an id
    (``asset_type_id`` / ``workcell_id`` — id wins when both are given).
    """
    # Read at most the cap (+1) so an oversized upload is rejected without
    # buffering the whole body into memory first.
    raw = await file.read(MAX_CSV_BYTES + 1)
    if len(raw) > MAX_CSV_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"CSV exceeds the {MAX_CSV_BYTES // (1024 * 1024)} MB limit",
        )
    try:
        rows = parse_asset_csv(raw)
    except BulkOperationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    if len(rows) > MAX_ITEMS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Too many rows ({len(rows)}); max {MAX_ITEMS} per upload",
        )

    job = await _create_job_or_503(
        "asset_import", total=len(rows), organization_id=org_id, actor_id=current_user.id
    )
    background_tasks.add_task(
        bulk_processor.run_asset_import, job["job_id"], rows, org_id, current_user.id
    )
    return _job_accepted(job)


@router.post(
    "/kanban/tasks/{operation}",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Bulk Kanban task operations (move / delete / assign)",
)
async def bulk_kanban_tasks(
    operation: str,
    payload: KanbanBulkRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_active_user),
):
    if operation not in KANBAN_OPERATIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"operation must be one of: {', '.join(sorted(KANBAN_OPERATIONS))}",
        )
    if len(payload.task_ids) > MAX_ITEMS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Too many task_ids ({len(payload.task_ids)}); max {MAX_ITEMS}",
        )
    if operation == "move" and not payload.target_column_id:
        raise HTTPException(status_code=400, detail="target_column_id is required for move")
    if operation == "assign" and not payload.assigned_to:
        raise HTTPException(status_code=400, detail="assigned_to is required for assign")

    params = {
        "target_column_id": payload.target_column_id,
        "position": payload.position,
        "assigned_to": payload.assigned_to,
    }
    job = await _create_job_or_503(
        f"kanban_{operation}",
        total=len(payload.task_ids),
        organization_id=current_user.organization_id,
        actor_id=current_user.id,
    )
    background_tasks.add_task(
        bulk_processor.run_kanban_bulk,
        job["job_id"],
        operation,
        payload.task_ids,
        params,
        current_user.id,
        current_user.organization_id,
    )
    return _job_accepted(job)


@router.post(
    "/alarms/acknowledge",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Bulk acknowledge alarms",
)
async def bulk_acknowledge_alarms(
    payload: AlarmBulkAckRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_active_user),
):
    if len(payload.alarm_ids) > MAX_ITEMS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Too many alarm_ids ({len(payload.alarm_ids)}); max {MAX_ITEMS}",
        )
    job = await _create_job_or_503(
        "alarm_acknowledge",
        total=len(payload.alarm_ids),
        organization_id=current_user.organization_id,
        actor_id=current_user.id,
    )
    background_tasks.add_task(
        bulk_processor.run_alarm_acknowledge,
        job["job_id"],
        payload.alarm_ids,
        payload.comment,
        current_user.id,
        current_user.organization_id,
    )
    return _job_accepted(job)


@router.post(
    "/registries/{registry_id}/items",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Bulk create registry items",
)
async def bulk_create_registry_items(
    registry_id: UUID,
    payload: RegistryItemsBulkRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_active_user),
):
    if len(payload.items) > MAX_ITEMS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Too many items ({len(payload.items)}); max {MAX_ITEMS}",
        )
    items = [item.model_dump(exclude_none=True) for item in payload.items]
    job = await _create_job_or_503(
        "registry_items",
        total=len(items),
        organization_id=current_user.organization_id,
        actor_id=current_user.id,
    )
    background_tasks.add_task(
        bulk_processor.run_registry_items,
        job["job_id"],
        registry_id,
        items,
        current_user.id,
        current_user.organization_id,
    )
    return _job_accepted(job)


@router.get("/jobs/{job_id}", summary="Get bulk job status and progress")
async def get_bulk_job(
    job_id: str,
    current_user: User = Depends(get_current_active_user),
):
    try:
        job = await bulk_processor.get_job(job_id)
    except Exception as exc:
        logger.error("bulk_job_store_unavailable", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Bulk job store unavailable",
        )
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found or expired")
    # Scope visibility to the caller's organization.
    job_org = job.get("organization_id")
    user_org = str(current_user.organization_id) if current_user.organization_id else None
    if job_org and job_org != user_org:
        raise HTTPException(status_code=404, detail="Job not found or expired")
    return job

"""Operations API Routes (Job/Process Tracking)"""

from typing import Any, Dict, List, Optional
from uuid import UUID
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, and_, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.pagination import PageParams, PaginatedResponse, paginate
from app.db.database import get_db
from app.db.models import Operation, Asset, PackMLState
from app.models.schemas import OperationCreate, OperationResponse

from app.api.auth import get_current_active_user
from app.middleware.rbac import require_operator_or_admin

router = APIRouter(dependencies=[Depends(get_current_active_user)])


# ---- Small response schemas for stable dict-shaped endpoints (FS-100). ----
# Shapes are unchanged; these only document/type what the handlers already return.

class ActiveOperationItem(BaseModel):
    id: str
    asset_id: str
    asset_name: Optional[str] = None
    operation_name: Optional[str] = None
    job_id: Optional[str] = None
    started_at: Optional[str] = None
    progress: Optional[Any] = None


class ActiveOperationsResponse(BaseModel):
    count: int
    operations: List[ActiveOperationItem]


class PackMLStateSlice(BaseModel):
    seconds: float
    percentage: float


class PackMLSummaryResponse(BaseModel):
    operation_id: str
    operation_name: Optional[str] = None
    status: Optional[str] = None
    total_duration_seconds: float
    state_breakdown: Dict[str, PackMLStateSlice]
    productive_time_seconds: float
    productive_percentage: float


@router.get("/", response_model=PaginatedResponse[OperationResponse])
async def list_operations(
    asset_id: Optional[UUID] = None,
    status: Optional[str] = None,
    job_id: Optional[str] = None,
    start_time: Optional[datetime] = None,
    end_time: Optional[datetime] = None,
    page: PageParams = Depends(),
    db: AsyncSession = Depends(get_db)
):
    """List operations with filtering (paginated).

    Returns a PaginatedResponse envelope (items + meta). operations has no
    frontend client, so this is the reference rollout of app.core.pagination;
    consumer-facing unowned routers (yard, transportation) follow the same
    one-line pattern once the generated SDK replaces their hand-written clients.
    """
    filters = []
    if asset_id:
        filters.append(Operation.asset_id == asset_id)
    if status:
        filters.append(Operation.status == status)
    if job_id:
        filters.append(Operation.job_id == job_id)
    if start_time:
        filters.append(Operation.started_at >= start_time)
    if end_time:
        filters.append(Operation.started_at <= end_time)

    where = and_(*filters) if filters else None

    total_q = select(func.count()).select_from(Operation)
    list_q = select(Operation)
    if where is not None:
        total_q = total_q.where(where)
        list_q = list_q.where(where)

    total = (await db.execute(total_q)).scalar_one()
    list_q = list_q.order_by(Operation.started_at.desc()).offset(page.skip).limit(page.limit)
    operations = (await db.execute(list_q)).scalars().all()

    return paginate(operations, total, page)


@router.get("/active", response_model=ActiveOperationsResponse)
async def get_active_operations(
    organization_id: Optional[UUID] = None,
    workcell_id: Optional[UUID] = None,
    db: AsyncSession = Depends(get_db)
):
    """Get currently running operations"""
    query = select(Operation).where(Operation.status == 'running')
    
    if organization_id or workcell_id:
        query = query.join(Asset)
        if organization_id:
            query = query.where(Asset.organization_id == organization_id)
        if workcell_id:
            query = query.where(Asset.workcell_id == workcell_id)
    
    result = await db.execute(query)
    operations = result.scalars().all()
    
    return {
        "count": len(operations),
        "operations": [
            {
                "id": str(op.id),
                "asset_id": str(op.asset_id),
                "asset_name": op.asset.name if hasattr(op, 'asset') else None,
                "operation_name": op.operation_name,
                "job_id": op.job_id,
                "started_at": op.started_at.isoformat() if op.started_at else None,
                # NB: the JSON column is meta_data ("metadata" is SQLAlchemy's
                # reserved Base.metadata — op.metadata is a MetaData object and
                # .get() on it 500'd this route whenever an operation was running).
                "progress": op.meta_data.get('progress') if op.meta_data else None
            }
            for op in operations
        ]
    }


@router.get("/{operation_id}", response_model=OperationResponse)
async def get_operation(
    operation_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """Get a single operation by ID"""
    result = await db.execute(
        select(Operation).where(Operation.id == operation_id)
    )
    operation = result.scalar_one_or_none()
    
    if not operation:
        raise HTTPException(status_code=404, detail="Operation not found")
    
    return operation


@router.post("/", response_model=OperationResponse, dependencies=[Depends(require_operator_or_admin)])
async def create_operation(
    operation_data: OperationCreate,
    db: AsyncSession = Depends(get_db)
):
    """Start a new operation"""
    # Verify asset exists
    result = await db.execute(
        select(Asset).where(Asset.id == operation_data.asset_id)
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Asset not found")
    
    operation = Operation(
        **operation_data.model_dump(),
        status='running',
        started_at=datetime.now(timezone.utc)
    )
    db.add(operation)
    await db.commit()
    await db.refresh(operation)
    
    return operation


@router.post("/{operation_id}/complete", response_model=OperationResponse, dependencies=[Depends(require_operator_or_admin)])
async def complete_operation(
    operation_id: UUID,
    success: bool = True,
    metadata: Optional[dict] = None,
    db: AsyncSession = Depends(get_db)
):
    """Mark an operation as completed"""
    result = await db.execute(
        select(Operation).where(Operation.id == operation_id)
    )
    operation = result.scalar_one_or_none()
    
    if not operation:
        raise HTTPException(status_code=404, detail="Operation not found")
    
    if operation.status != 'running':
        raise HTTPException(status_code=400, detail=f"Operation is {operation.status}, not running")
    
    # Calculate actual duration
    completed_at = datetime.now(timezone.utc)
    actual_duration = None
    if operation.started_at:
        started_at = operation.started_at
        if started_at.tzinfo is None:
            # SQLite hands back naive datetimes, PG aware — coerce before the
            # aware-`completed_at` subtraction (naive-vs-aware raises TypeError).
            started_at = started_at.replace(tzinfo=timezone.utc)
        actual_duration = int((completed_at - started_at).total_seconds())
    
    operation.status = 'completed' if success else 'failed'
    operation.completed_at = completed_at
    operation.actual_duration = actual_duration
    
    if metadata:
        # meta_data, not metadata — see note in get_active_operations.
        current_metadata = dict(operation.meta_data or {})
        current_metadata.update(metadata)
        operation.meta_data = current_metadata
    
    # Calculate PackML state durations for this operation
    await _calculate_state_durations(operation, db)
    
    await db.commit()
    await db.refresh(operation)
    
    return operation


async def _calculate_state_durations(operation: Operation, db: AsyncSession):
    """Calculate time spent in each PackML state during operation"""
    if not operation.started_at or not operation.completed_at:
        return
    
    result = await db.execute(
        select(
            PackMLState.state,
            PackMLState.duration_seconds
        )
        .where(
            and_(
                PackMLState.asset_id == operation.asset_id,
                PackMLState.state_entered_at >= operation.started_at,
                PackMLState.state_entered_at <= operation.completed_at
            )
        )
    )
    
    state_durations = {}
    for state, duration in result.all():
        if state not in state_durations:
            state_durations[state] = 0
        state_durations[state] += float(duration) if duration else 0
    
    operation.packml_state_durations = state_durations


@router.get("/{operation_id}/packml-summary", response_model=PackMLSummaryResponse)
async def get_operation_packml_summary(
    operation_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """Get PackML state breakdown for an operation"""
    result = await db.execute(
        select(Operation).where(Operation.id == operation_id)
    )
    operation = result.scalar_one_or_none()
    
    if not operation:
        raise HTTPException(status_code=404, detail="Operation not found")
    
    durations = operation.packml_state_durations or {}
    total_duration = sum(durations.values())
    
    # Calculate percentages
    breakdown = {}
    for state, duration in durations.items():
        breakdown[state] = {
            'seconds': duration,
            'percentage': round((duration / total_duration * 100), 2) if total_duration > 0 else 0
        }
    
    return {
        "operation_id": str(operation_id),
        "operation_name": operation.operation_name,
        "status": operation.status,
        "total_duration_seconds": total_duration,
        "state_breakdown": breakdown,
        "productive_time_seconds": durations.get('Execute', 0),
        "productive_percentage": round(
            (durations.get('Execute', 0) / total_duration * 100), 2
        ) if total_duration > 0 else 0
    }

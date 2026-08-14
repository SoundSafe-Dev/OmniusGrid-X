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
from app.core.tenant import get_tenant_db, get_tenant_org_id
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


#: The state the edge agent emits for a vendor string its mapping does not cover (FS-462).
#: Mirrors `PackMLState.UNDEFINED` in `edge-agent/opsgrid_agent/packml.py`; kept as a plain
#: literal because the backend does not import from the agent package.
UNMAPPED_STATE = "Undefined"


class PackMLSummaryResponse(BaseModel):
    operation_id: str
    operation_name: Optional[str] = None
    status: Optional[str] = None
    total_duration_seconds: float
    state_breakdown: Dict[str, PackMLStateSlice]
    productive_time_seconds: float
    #: Productive time over the duration that could be INTERPRETED — total minus time the
    #: edge agent's PackML mapper could not translate (FS-462). Dividing by the raw total
    #: dilutes the figure with time nobody could read, which reports a running machine as
    #: less productive the more of its states are unmapped.
    productive_percentage: float
    #: Seconds spent in states the agent could not map. Reported rather than folded away,
    #: because a large value here means the answer above rests on a small sample.
    unmeasured_seconds: float = 0.0


def _own_operation(operation_id: UUID, organization_id: UUID):
    """One operation, by id, ONLY if the caller's organisation owns the asset it ran on.

    `operations` carries no `organization_id` column, so it has no RLS policy and
    `get_tenant_db` does nothing for it: a `select(Operation).where(Operation.id == …)`
    reaches every tenant's rows. Three handlers were written that way — read one, read its
    PackML summary, and COMPLETE it — so an authenticated operator could finish another
    organisation's production run by id and the row would record their outcome.

    `/active` already joined `assets` for this reason, under a comment saying the join "is
    no longer optional" after the same defect was fixed there. It was fixed on one handler
    of five. This helper exists so the next handler cannot forget: there is no shorter way
    to select an operation here than the correct one.

    BOTH the join and the explicit organisation predicate, and the second one is not noise.
    `assets` is FORCE RLS, so on a `get_tenant_db` session the join alone already scopes
    this — proven by mutation: deleting the predicate alone changes no test. It is kept
    because that protection is a property of the SESSION, not of the query, and the whole
    reason this defect existed is that someone reasonably assumed the session was doing the
    work. A handler that ever moves to `get_db` still returns the right rows.
    """
    return (
        select(Operation)
        .join(Asset)
        .where(Operation.id == operation_id, Asset.organization_id == organization_id)
    )


@router.get("/", response_model=PaginatedResponse[OperationResponse])
async def list_operations(
    asset_id: Optional[UUID] = None,
    status: Optional[str] = None,
    job_id: Optional[str] = None,
    start_time: Optional[datetime] = None,
    end_time: Optional[datetime] = None,
    page: PageParams = Depends(),
    organization_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db)
):
    """List operations with filtering (paginated).

    Returns a PaginatedResponse envelope (items + meta). operations has no
    frontend client, so this is the reference rollout of app.core.pagination;
    consumer-facing unowned routers (yard, transportation) follow the same
    one-line pattern once the generated SDK replaces their hand-written clients.

    THE TENANT JOIN IS THE FIRST FILTER, not an optional one. `operations` has NO
    `organization_id` column and therefore no RLS policy — the tenant of an operation is
    whoever owns its asset — so `get_tenant_db` protects this table not at all and a bare
    `select(Operation)` returned EVERY organisation's operations to any authenticated
    caller. `/active` had already been fixed for exactly this (see the note below it) and
    the other four handlers in this file were left on the unscoped shape.
    """
    filters = [Asset.organization_id == organization_id]
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

    where = and_(*filters)

    # The count is joined too: a total taken across all tenants would report a page of 20
    # out of every organisation's operations, which is the denominator lying (rule 165).
    total_q = select(func.count()).select_from(Operation).join(Asset)
    list_q = select(Operation).join(Asset)
    total_q = total_q.where(where)
    list_q = list_q.where(where)

    total = (await db.execute(total_q)).scalar_one()
    list_q = list_q.order_by(Operation.started_at.desc()).offset(page.skip).limit(page.limit)
    operations = (await db.execute(list_q)).scalars().all()

    return paginate(operations, total, page)


@router.get("/active", response_model=ActiveOperationsResponse)
async def get_active_operations(
    workcell_id: Optional[UUID] = None,
    organization_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db)
):
    """Get currently running operations"""
    # THE TENANT JOIN IS NO LONGER OPTIONAL. `organization_id` was a client-supplied query
    # parameter — the IDOR shape — and the join that applied it only happened when the caller
    # sent one, so a bare `GET /operations/active` filtered by nothing at all. `operations`
    # carries a policy, so RLS was doing the work; the request was asking the caller which
    # tenant to use and being saved by the database.
    query = (
        select(Operation)
        .join(Asset)
        .where(Operation.status == 'running', Asset.organization_id == organization_id)
    )
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
    organization_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db)
):
    """Get a single operation by ID"""
    result = await db.execute(_own_operation(operation_id, organization_id))
    operation = result.scalar_one_or_none()
    
    if not operation:
        raise HTTPException(status_code=404, detail="Operation not found")
    
    return operation


@router.post("/", response_model=OperationResponse, dependencies=[Depends(require_operator_or_admin)])
async def create_operation(
    operation_data: OperationCreate,
    db: AsyncSession = Depends(get_tenant_db)
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


class OperationCompletion(BaseModel):
    """The whole of what completing an operation takes, in ONE place.

    It was two bare parameters — `success: bool = True` and `metadata: Optional[dict]` — and
    FastAPI reads those from two different places: a non-Pydantic scalar with no `Body(...)`
    marker is a QUERY parameter, while a `dict` is a body. So the route took `success` from
    the query string and `metadata` from the JSON body.

    A client cannot post one document to that. The natural call —
    `api.post(url, {"success": False, "metadata": {...}})` — sends both in the body; the
    body-side field arrives, `success` silently falls back to its default `True`, and the
    route records a FAILED operation as **completed**, with a 200 and no warning.

    That is the quiet form of a class this repository has been bitten by three times already
    (FS-379, FS-420, FS-658). Those were loud: every query parameter was required, so the
    natural client got 422 on every call and the feature visibly never worked. Here the
    parameter has a default, so the same mistake produces a wrong terminal state instead of
    an error — and the operation's duration and PackML state rollups are computed and stored
    against it.

    Nothing calls this route today — no frontend, no test, no e2e, no doc — so moving the
    contract costs no caller. The three earlier instances were fixed on the CLIENT side
    precisely because clients existed; that reasoning does not apply when there are none.
    """

    success: bool = True
    metadata: Optional[Dict[str, Any]] = None


@router.post("/{operation_id}/complete", response_model=OperationResponse, dependencies=[Depends(require_operator_or_admin)])
async def complete_operation(
    operation_id: UUID,
    completion: OperationCompletion = OperationCompletion(),
    organization_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db)
):
    """Mark an operation as completed"""
    result = await db.execute(_own_operation(operation_id, organization_id))
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
    
    operation.status = 'completed' if completion.success else 'failed'
    operation.completed_at = completed_at
    operation.actual_duration = actual_duration
    
    if completion.metadata:
        # meta_data, not metadata — see note in get_active_operations.
        current_metadata = dict(operation.meta_data or {})
        current_metadata.update(completion.metadata)
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
    organization_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db)
):
    """Get PackML state breakdown for an operation"""
    result = await db.execute(_own_operation(operation_id, organization_id))
    operation = result.scalar_one_or_none()
    
    if not operation:
        raise HTTPException(status_code=404, detail="Operation not found")
    
    durations = operation.packml_state_durations or {}
    total_duration = sum(durations.values())
    
    # TIME NOBODY COULD READ IS NOT TIME THE MACHINE WAS UNPRODUCTIVE (FS-462).
    #
    # The edge agent emits `Undefined` for a vendor state its PackML mapping does not
    # cover — it used to emit `Idle`, which made a running machine look stopped. Now that
    # the absence is honest, this endpoint has to treat it as an absence: dividing Execute
    # time by a total that includes unmapped time reports a machine as less productive the
    # more of its states are unrecognised, which is a property of the CONFIG, not the
    # machine. The same fix as `calculate_availability` on the agent, one boundary out.
    unmeasured = durations.get(UNMAPPED_STATE, 0)
    measured_duration = total_duration - unmeasured
    
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
            (durations.get('Execute', 0) / measured_duration * 100), 2
        ) if measured_duration > 0 else 0,
        "unmeasured_seconds": unmeasured,
    }

"""Shop-floor events: issue a part, clock time, report a problem, log downtime (FS-405).

Each endpoint does two things and reports both separately:

  1. records what happened on the floor
  2. creates the posting ledger for every system of record that needs to hear about it

THE RESPONSE NEVER SAYS "SYNCED". It returns a per-target breakdown, because "issuing a
part ties into inventory, purchasing and accounting" is three claims and they can differ.
A caller gets `fully_posted: false` with `awaiting_a_person` naming exactly which target
needs a human and what to tell them — the analog path, made legible instead of silently
dropped.

WHY POSTINGS START AS `pending` RATHER THAN BEING PUSHED INLINE. A part issue must be
recorded even when the ERP is unreachable; blocking the floor on a third-party's
availability is how operators learn to work around the system. The ledger records the
obligation immediately and a poster drains it, so an outage delays a posting instead of
losing an event.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from uuid import UUID
from typing import Any, List, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_active_user
from app.middleware.rbac import require_operator_or_admin
from app.core.datetime_utils import utcnow
from app.core.tenant import get_tenant_db, get_tenant_org_id
from app.db.models import Asset, User
from app.db.shop_floor_models import (
    DowntimeEvent, EventType, LaborEntry, PartIssue, PostingStatus, QualityEvent,
    SystemOfRecordPosting, TargetSystem,
)
from app.services.posting_drainer import drain
from app.services.shop_floor_fanout import (
    ROUTING, acknowledge_manual, fan_out,
)

logger = structlog.get_logger()

router = APIRouter(dependencies=[Depends(get_current_active_user)])


# ------------------------------------------------------------------------------- schemas
class PostingOut(BaseModel):
    """One (event, target system) obligation and what became of it."""

    id: str
    target_system: str
    status: str
    external_ref: Optional[str] = None
    instruction: Optional[str] = None
    attempts: int
    last_error: Optional[str] = None
    acknowledged_at: Optional[datetime] = None
    posted_at: Optional[datetime] = None


class FanoutOut(BaseModel):
    """The honest summary. `fully_posted` is the only field that means "it all landed",
    and it is computed from the postings rather than assumed from a 201."""

    event_type: str
    event_id: str
    targets: int
    by_status: dict
    fully_posted: bool
    awaiting_a_person: List[dict]


class PartIssueCreate(BaseModel):
    part_number: str = Field(..., min_length=1, max_length=100)
    quantity: float = Field(..., gt=0)
    unit_of_measure: str = Field("each", max_length=20)
    description: Optional[str] = None
    asset_id: Optional[UUID] = None
    work_order_ref: Optional[str] = Field(None, max_length=100)
    #: Optional, and NOT defaulted to zero. See the column comment: "free" and "not priced
    #: yet" are different statements to an accounting system.
    unit_cost: Optional[float] = Field(None, ge=0)
    currency: Optional[str] = Field(None, min_length=3, max_length=3)
    reason: str = Field("production", max_length=50)
    notes: Optional[str] = None


class PartIssueOut(BaseModel):
    id: str
    part_number: str
    quantity: float
    unit_of_measure: str
    description: Optional[str] = None
    asset_id: Optional[str] = None
    work_order_ref: Optional[str] = None
    unit_cost: Optional[float] = None
    #: quantity x unit_cost, or null when the cost is not known. Never 0 as a stand-in.
    extended_cost: Optional[float] = None
    currency: Optional[str] = None
    reason: str
    issued_at: datetime
    fanout: FanoutOut


class ClockInRequest(BaseModel):
    operator_ref: Optional[str] = Field(None, max_length=100)
    asset_id: Optional[UUID] = None
    work_order_ref: Optional[str] = Field(None, max_length=100)
    labor_category: str = Field("direct", max_length=50)
    notes: Optional[str] = None


class ClockOutRequest(BaseModel):
    notes: Optional[str] = None


class LaborEntryOut(BaseModel):
    id: str
    user_id: Optional[str] = None
    operator_ref: Optional[str] = None
    asset_id: Optional[str] = None
    work_order_ref: Optional[str] = None
    clock_in_at: datetime
    clock_out_at: Optional[datetime] = None
    duration_minutes: Optional[float] = None
    labor_category: str
    #: Absent while the clock is running: an open entry has not produced hours yet, so
    #: there is nothing to post and claiming otherwise would put a running shift into
    #: payroll.
    fanout: Optional[FanoutOut] = None


class QualityEventCreate(BaseModel):
    description: str = Field(..., min_length=1)
    event_type: str = Field("defect", max_length=50)
    severity: str = Field("minor", max_length=20)
    #: `UUID`, like its three siblings. This one was missed on the first pass because the
    #: probe that found the others sent a body this model rejects for a different reason —
    #: `description` is required here — so it answered 422 and looked fixed. The ownership
    #: check reached it (a foreign asset is a 404) while a malformed id still reached
    #: Postgres and came back 500.
    asset_id: Optional[UUID] = None
    work_order_ref: Optional[str] = Field(None, max_length=100)
    part_number: Optional[str] = Field(None, max_length=100)
    quantity_affected: Optional[float] = Field(None, ge=0)
    scrap_quantity: Optional[float] = Field(None, ge=0)
    disposition: Optional[str] = Field(None, max_length=50)

    @model_validator(mode="after")
    def scrap_cannot_exceed_affected(self):
        if (
            self.scrap_quantity is not None
            and self.quantity_affected is not None
            and self.scrap_quantity > self.quantity_affected
        ):
            raise ValueError("scrap_quantity cannot exceed quantity_affected")
        return self


class QualityEventOut(BaseModel):
    id: str
    event_type: str
    severity: str
    description: str
    asset_id: Optional[str] = None
    work_order_ref: Optional[str] = None
    part_number: Optional[str] = None
    quantity_affected: Optional[float] = None
    scrap_quantity: Optional[float] = None
    disposition: Optional[str] = None
    occurred_at: datetime
    fanout: FanoutOut


class DowntimeStartRequest(BaseModel):
    asset_id: UUID
    downtime_type: str = Field("unplanned", max_length=30)
    reason_code: Optional[str] = Field(None, max_length=50)
    description: Optional[str] = None
    maintenance_ref: Optional[str] = Field(None, max_length=100)


class DowntimeEndRequest(BaseModel):
    reason_code: Optional[str] = Field(None, max_length=50)
    description: Optional[str] = None


class DowntimeEventOut(BaseModel):
    id: str
    asset_id: str
    downtime_type: str
    reason_code: Optional[str] = None
    description: Optional[str] = None
    started_at: datetime
    ended_at: Optional[datetime] = None
    duration_minutes: Optional[float] = None
    maintenance_ref: Optional[str] = None
    #: Absent while the machine is still down, for the same reason an open labour entry has
    #: none: the duration that scheduling and accounting need does not exist yet.
    fanout: Optional[FanoutOut] = None


class PartIssuePage(BaseModel):
    """A page of part issues, with the count it was drawn from.

    NOT A BARE ARRAY. A capped list with no total cannot distinguish "these are all of them"
    from "these are the first 50 of 900" — defect class 22, twelve instances found across
    this API. `total` is counted before the limit is applied, so `truncated` is a fact rather
    than a guess.
    """

    items: List[PartIssueOut]
    total: int
    limit: int
    truncated: bool


class PostingPage(BaseModel):
    """A page of the posting ledger. Same contract as PartIssuePage, and it matters more
    here: an operator reading `outstanding_only` needs to know whether the list they are
    working through is the whole backlog."""

    items: List[PostingOut]
    total: int
    limit: int
    truncated: bool


class DrainOut(BaseModel):
    """What a drain attempt did, counted per outcome.

    NOT one number. "3 posted" and "3 handed to a person" are both progress and they mean
    completely different things to whoever reads this next.
    """

    considered: int
    posted: int
    failed: int
    handed_to_a_person: int
    orphaned: int
    note: str


class RoutingOut(BaseModel):
    """The declared mandate: which systems each event type must reach.

    Served so the UI, and a person auditing the deployment, can read the routing from the
    running system rather than from a document that may not match it.
    """

    routing: dict
    target_systems: List[str]
    #: Declared because the handler returns it. A response model that omits a field the
    #: handler produces silently deletes it from the wire — the FS-394/FS-398 class, where a
    #: panel rendered blank because the model dropped what the endpoint actually sent.
    posting_statuses: dict


class AcknowledgeRequest(BaseModel):
    """A person confirming they did the analog step.

    `external_ref` is what makes this a POSTING rather than an acknowledgement. Saying "I
    told the stores clerk" and "the stores system has a record" are different facts; supply
    the requisition number and it becomes the second.
    """

    external_ref: Optional[str] = Field(None, max_length=200)


def _fanout_out(result) -> FanoutOut:
    return FanoutOut(**result.summary())


def _posting_out(p: SystemOfRecordPosting) -> PostingOut:
    return PostingOut(
        id=str(p.id), target_system=p.target_system, status=p.status,
        external_ref=p.external_ref, instruction=p.instruction,
        attempts=p.attempts or 0, last_error=p.last_error,
        acknowledged_at=p.acknowledged_at, posted_at=p.posted_at,
    )


# --------------------------------------------------------------------------- part issues
async def _own_asset_id(
    db: AsyncSession, asset_id: Optional[UUID]
) -> Optional[str]:
    """Return the asset id as a string, having proved the CALLER can see the asset.

    TWO DEFECTS IN ONE LINE OF SIGNATURE, both found by driving these routes with the input
    the contract gate generates.

    `asset_id` was a bare `str` on three write models. Anything non-UUID reached Postgres
    and came back as a 500 — `POST /shop-floor/downtime/start`, `/part-issues` and
    `/labor/clock-in` all did, where the contract promises a 4xx. Typing it as `UUID` moves
    that to a 422 at the door.

    And nothing checked whose asset it was. `downtime_events.asset_id` is a FOREIGN KEY to
    `assets`, and a foreign-key check is performed by the database at a level RLS does not
    filter — so a valid id belonging to ANOTHER ORGANISATION was accepted, and org B could
    log downtime against org A's machine and get a 201. The row lands in org B's own
    tenancy, so this is not a read of someone else's data; it is a write that references
    it, and `/downtime/open` then returns an event whose asset the caller cannot resolve.
    Downtime is also an OEE input, so the figure it feeds is computed against a machine the
    tenant does not own.

    The lookup itself is one statement and RLS does the work: on a `get_tenant_db` session,
    another organisation's asset simply is not there. That is the same shape as
    `_own_operation` in `api/operations.py` — where the table had no policy and the join had
    to be written by hand — and the reason both exist is the same: the next handler will not
    remember.
    """
    if asset_id is None:
        return None
    found = (
        await db.execute(select(Asset.id).where(Asset.id == asset_id))
    ).scalar_one_or_none()
    if found is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"asset {asset_id} not found",
        )
    return str(asset_id)


@router.post("/part-issues", dependencies=[Depends(require_operator_or_admin)], response_model=PartIssueOut, status_code=status.HTTP_201_CREATED)
async def issue_part(
    payload: PartIssueCreate,
    org_id=Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
    current_user: User = Depends(get_current_active_user),
):
    """Issue a part to a job or a machine, and route it to inventory, purchasing and
    accounting."""
    issue = PartIssue(
        id=str(uuid.uuid4()),
        organization_id=str(org_id),
        part_number=payload.part_number,
        description=payload.description,
        quantity=payload.quantity,
        unit_of_measure=payload.unit_of_measure,
        asset_id=await _own_asset_id(db, payload.asset_id),
        work_order_ref=payload.work_order_ref,
        unit_cost=payload.unit_cost,
        currency=payload.currency,
        issued_by=str(current_user.id),
        issued_at=utcnow(),
        reason=payload.reason,
        notes=payload.notes,
        meta_data={},
    )
    db.add(issue)
    await db.flush()

    result = await fan_out(db, str(org_id), issue, EventType.PART_ISSUE)
    await db.commit()

    return PartIssueOut(
        id=str(issue.id), part_number=issue.part_number, quantity=float(issue.quantity),
        unit_of_measure=issue.unit_of_measure, description=issue.description,
        asset_id=str(issue.asset_id) if issue.asset_id else None,
        work_order_ref=issue.work_order_ref,
        unit_cost=float(issue.unit_cost) if issue.unit_cost is not None else None,
        extended_cost=issue.extended_cost, currency=issue.currency,
        reason=issue.reason, issued_at=issue.issued_at, fanout=_fanout_out(result),
    )


@router.get("/part-issues", response_model=PartIssuePage)
async def list_part_issues(
    limit: int = Query(50, ge=1, le=500),
    work_order_ref: Optional[str] = None,
    org_id=Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    query = select(PartIssue).where(PartIssue.organization_id == str(org_id))
    if work_order_ref:
        query = query.where(PartIssue.work_order_ref == work_order_ref)
    # Counted before the limit, so `truncated` is measured rather than inferred from the
    # page being exactly `limit` long — which is wrong whenever the set is exactly that size.
    total = (
        await db.execute(select(func.count()).select_from(query.subquery()))
    ).scalar() or 0
    rows = (
        await db.execute(query.order_by(PartIssue.issued_at.desc()).limit(limit))
    ).scalars().all()

    out = []
    for issue in rows:
        result = await _existing_fanout(db, EventType.PART_ISSUE, str(issue.id))
        out.append(PartIssueOut(
            id=str(issue.id), part_number=issue.part_number,
            quantity=float(issue.quantity), unit_of_measure=issue.unit_of_measure,
            description=issue.description,
            asset_id=str(issue.asset_id) if issue.asset_id else None,
            work_order_ref=issue.work_order_ref,
            unit_cost=float(issue.unit_cost) if issue.unit_cost is not None else None,
            extended_cost=issue.extended_cost, currency=issue.currency,
            reason=issue.reason, issued_at=issue.issued_at, fanout=result,
        ))
    return PartIssuePage(items=out, total=total, limit=limit, truncated=total > len(out))


# ------------------------------------------------------------------------- labour / clock
@router.post("/labor/clock-in", dependencies=[Depends(require_operator_or_admin)], response_model=LaborEntryOut, status_code=status.HTTP_201_CREATED)
async def clock_in(
    payload: ClockInRequest,
    org_id=Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
    current_user: User = Depends(get_current_active_user),
):
    """Start a labour span.

    REFUSES A SECOND OPEN ENTRY for the same person. Two open clocks would produce
    overlapping hours, and payroll cannot tell which is real — better to reject the second
    than to post both.
    """
    existing = (
        await db.execute(
            select(LaborEntry).where(
                LaborEntry.organization_id == str(org_id),
                LaborEntry.user_id == str(current_user.id),
                LaborEntry.clock_out_at.is_(None),
            )
        )
    ).scalars().first()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"already clocked in since {existing.clock_in_at.isoformat()} "
                f"(entry {existing.id}); clock out before starting another"
            ),
        )

    entry = LaborEntry(
        id=str(uuid.uuid4()),
        organization_id=str(org_id),
        user_id=str(current_user.id),
        operator_ref=payload.operator_ref,
        asset_id=await _own_asset_id(db, payload.asset_id),
        work_order_ref=payload.work_order_ref,
        clock_in_at=utcnow(),
        labor_category=payload.labor_category,
        notes=payload.notes,
        meta_data={},
    )
    db.add(entry)
    await db.commit()

    # No fanout: an open entry has produced no hours, so there is nothing to post yet.
    return LaborEntryOut(
        id=str(entry.id), user_id=str(entry.user_id), operator_ref=entry.operator_ref,
        asset_id=str(entry.asset_id) if entry.asset_id else None,
        work_order_ref=entry.work_order_ref, clock_in_at=entry.clock_in_at,
        labor_category=entry.labor_category, fanout=None,
    )


@router.post("/labor/clock-out", dependencies=[Depends(require_operator_or_admin)], response_model=LaborEntryOut)
async def clock_out(
    payload: ClockOutRequest,
    org_id=Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
    current_user: User = Depends(get_current_active_user),
):
    """Close the open labour span and route the hours to production and accounting."""
    entry = (
        await db.execute(
            select(LaborEntry).where(
                LaborEntry.organization_id == str(org_id),
                LaborEntry.user_id == str(current_user.id),
                LaborEntry.clock_out_at.is_(None),
            ).order_by(LaborEntry.clock_in_at.desc())
        )
    ).scalars().first()
    if entry is None:
        raise HTTPException(status_code=404, detail="no open labour entry to close")

    entry.clock_out_at = utcnow()
    started = entry.clock_in_at
    if started.tzinfo is None:
        # SQLite hands these back naive; comparing against an aware `now` raises. Same
        # class as FS-391/FS-400 — assume UTC, because that is what was written.
        from datetime import timezone
        started = started.replace(tzinfo=timezone.utc)
    entry.duration_minutes = round((entry.clock_out_at - started).total_seconds() / 60, 2)
    if payload.notes:
        entry.notes = f"{entry.notes}\n{payload.notes}" if entry.notes else payload.notes
    await db.flush()

    result = await fan_out(db, str(org_id), entry, EventType.LABOR_ENTRY)
    await db.commit()

    return LaborEntryOut(
        id=str(entry.id), user_id=str(entry.user_id), operator_ref=entry.operator_ref,
        asset_id=str(entry.asset_id) if entry.asset_id else None,
        work_order_ref=entry.work_order_ref, clock_in_at=entry.clock_in_at,
        clock_out_at=entry.clock_out_at, duration_minutes=float(entry.duration_minutes),
        labor_category=entry.labor_category, fanout=_fanout_out(result),
    )


@router.get("/labor/open", response_model=Optional[LaborEntryOut])
async def open_labor_entry(
    org_id=Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
    current_user: User = Depends(get_current_active_user),
):
    """The caller's running clock, or null. Null is a real answer here, not an empty list
    pretending to be one."""
    entry = (
        await db.execute(
            select(LaborEntry).where(
                LaborEntry.organization_id == str(org_id),
                LaborEntry.user_id == str(current_user.id),
                LaborEntry.clock_out_at.is_(None),
            ).order_by(LaborEntry.clock_in_at.desc())
        )
    ).scalars().first()
    if entry is None:
        return None
    return LaborEntryOut(
        id=str(entry.id), user_id=str(entry.user_id), operator_ref=entry.operator_ref,
        asset_id=str(entry.asset_id) if entry.asset_id else None,
        work_order_ref=entry.work_order_ref, clock_in_at=entry.clock_in_at,
        labor_category=entry.labor_category, fanout=None,
    )


# ------------------------------------------------------------------------- quality events
@router.post("/quality-events", dependencies=[Depends(require_operator_or_admin)], response_model=QualityEventOut, status_code=status.HTTP_201_CREATED)
async def report_problem(
    payload: QualityEventCreate,
    org_id=Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
    current_user: User = Depends(get_current_active_user),
):
    """Report a problem, and route it to quality, inventory, production and accounting."""
    event = QualityEvent(
        id=str(uuid.uuid4()),
        organization_id=str(org_id),
        asset_id=await _own_asset_id(db, payload.asset_id),
        work_order_ref=payload.work_order_ref,
        part_number=payload.part_number,
        event_type=payload.event_type,
        severity=payload.severity,
        description=payload.description,
        quantity_affected=payload.quantity_affected,
        scrap_quantity=payload.scrap_quantity,
        disposition=payload.disposition,
        reported_by=str(current_user.id),
        occurred_at=utcnow(),
        meta_data={},
    )
    db.add(event)
    await db.flush()

    result = await fan_out(db, str(org_id), event, EventType.QUALITY_EVENT)
    await db.commit()

    return QualityEventOut(
        id=str(event.id), event_type=event.event_type, severity=event.severity,
        description=event.description,
        asset_id=str(event.asset_id) if event.asset_id else None,
        work_order_ref=event.work_order_ref, part_number=event.part_number,
        quantity_affected=float(event.quantity_affected) if event.quantity_affected is not None else None,
        scrap_quantity=float(event.scrap_quantity) if event.scrap_quantity is not None else None,
        disposition=event.disposition, occurred_at=event.occurred_at,
        fanout=_fanout_out(result),
    )


# ------------------------------------------------------------------------ downtime events
@router.get("/downtime/open", response_model=List[DowntimeEventOut])
async def open_downtime_events(
    org_id=Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    """Every downtime event still running for this organization (P5, page-enhancement
    review).

    The Machine Down card held its open event id in COMPONENT STATE, so a page reload
    stranded an in-progress downtime: the machine stayed recorded as down, the operator
    who started it could not end it, and no other operator could see it existed. Open
    downtime is org-visible state, not a browser tab's — the machine is down for
    everyone, so anyone on the floor must be able to close it. A list rather than the
    labour clock's `Optional` single: labour is per-user by construction, but several
    machines can be down at once.
    """
    events = (
        await db.execute(
            select(DowntimeEvent).where(
                DowntimeEvent.organization_id == str(org_id),
                DowntimeEvent.ended_at.is_(None),
            ).order_by(DowntimeEvent.started_at.desc())
        )
    ).scalars().all()
    return [
        DowntimeEventOut(
            id=str(event.id), asset_id=str(event.asset_id),
            downtime_type=event.downtime_type, reason_code=event.reason_code,
            description=event.description, started_at=event.started_at,
            ended_at=None, duration_minutes=None,
            maintenance_ref=event.maintenance_ref, fanout=None,
        )
        for event in events
    ]


@router.post("/downtime/start", dependencies=[Depends(require_operator_or_admin)], response_model=DowntimeEventOut, status_code=status.HTTP_201_CREATED)
async def start_downtime(
    payload: DowntimeStartRequest,
    org_id=Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
    current_user: User = Depends(get_current_active_user),
):
    """Log a machine going down.

    REFUSES A SECOND OPEN EVENT for the same asset, for the same reason as the labour
    clock: two overlapping downtime spans make the OEE denominator meaningless.
    """
    existing = (
        await db.execute(
            select(DowntimeEvent).where(
                DowntimeEvent.organization_id == str(org_id),
                DowntimeEvent.asset_id == await _own_asset_id(db, payload.asset_id),
                DowntimeEvent.ended_at.is_(None),
            )
        )
    ).scalars().first()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"asset already down since {existing.started_at.isoformat()} "
                f"(event {existing.id}); end that before starting another"
            ),
        )

    event = DowntimeEvent(
        id=str(uuid.uuid4()),
        organization_id=str(org_id),
        asset_id=await _own_asset_id(db, payload.asset_id),
        downtime_type=payload.downtime_type,
        reason_code=payload.reason_code,
        description=payload.description,
        maintenance_ref=payload.maintenance_ref,
        started_at=utcnow(),
        reported_by=str(current_user.id),
        meta_data={},
    )
    db.add(event)
    await db.commit()

    return DowntimeEventOut(
        id=str(event.id), asset_id=str(event.asset_id), downtime_type=event.downtime_type,
        reason_code=event.reason_code, description=event.description,
        started_at=event.started_at, maintenance_ref=event.maintenance_ref, fanout=None,
    )


@router.post("/downtime/{event_id}/end", dependencies=[Depends(require_operator_or_admin)], response_model=DowntimeEventOut)
async def end_downtime(
    event_id: UUID,
    payload: DowntimeEndRequest,
    org_id=Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    """Close a downtime span and route it to scheduling, production, quality and
    accounting."""
    event = (
        await db.execute(
            select(DowntimeEvent).where(
                DowntimeEvent.organization_id == str(org_id),
                DowntimeEvent.id == str(event_id),
            )
        )
    ).scalars().first()
    if event is None:
        raise HTTPException(status_code=404, detail="downtime event not found")
    if event.ended_at is not None:
        raise HTTPException(status_code=400, detail="downtime event already ended")

    event.ended_at = utcnow()
    started = event.started_at
    if started.tzinfo is None:
        from datetime import timezone
        started = started.replace(tzinfo=timezone.utc)
    event.duration_minutes = round((event.ended_at - started).total_seconds() / 60, 2)
    if payload.reason_code:
        event.reason_code = payload.reason_code
    if payload.description:
        event.description = payload.description
    await db.flush()

    result = await fan_out(db, str(org_id), event, EventType.DOWNTIME_EVENT)
    await db.commit()

    return DowntimeEventOut(
        id=str(event.id), asset_id=str(event.asset_id), downtime_type=event.downtime_type,
        reason_code=event.reason_code, description=event.description,
        started_at=event.started_at, ended_at=event.ended_at,
        duration_minutes=float(event.duration_minutes),
        maintenance_ref=event.maintenance_ref, fanout=_fanout_out(result),
    )


# -------------------------------------------------------------------------- the ledger
@router.get("/postings", response_model=PostingPage)
async def list_postings(
    status_filter: Optional[str] = Query(None, alias="status"),
    outstanding_only: bool = Query(False),
    limit: int = Query(100, ge=1, le=500),
    org_id=Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    """Every obligation and its state.

    `outstanding_only` is the operator's view: what still needs somebody to do something —
    pending, failed, or waiting on a person.
    """
    if status_filter and status_filter not in PostingStatus.ALL:
        raise HTTPException(
            status_code=422,
            detail=f"unknown status {status_filter!r}; expected one of {list(PostingStatus.ALL)}",
        )
    query = select(SystemOfRecordPosting).where(
        SystemOfRecordPosting.organization_id == str(org_id)
    )
    if status_filter:
        query = query.where(SystemOfRecordPosting.status == status_filter)
    elif outstanding_only:
        query = query.where(SystemOfRecordPosting.status.in_(PostingStatus.OUTSTANDING))

    total = (
        await db.execute(select(func.count()).select_from(query.subquery()))
    ).scalar() or 0
    rows = (
        await db.execute(query.order_by(SystemOfRecordPosting.created_at.desc()).limit(limit))
    ).scalars().all()
    return PostingPage(
        items=[_posting_out(p) for p in rows], total=total, limit=limit,
        truncated=total > len(rows),
    )


@router.post("/postings/{posting_id}/acknowledge", dependencies=[Depends(require_operator_or_admin)], response_model=PostingOut)
async def acknowledge_posting(
    posting_id: UUID,
    payload: AcknowledgeRequest,
    org_id=Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
    current_user: User = Depends(get_current_active_user),
):
    """Confirm the analog step was done — the "I told them" button.

    WITHOUT an `external_ref` this records WHO acted and WHEN, and the posting stays
    `manual_required`, because telling somebody is not the same as the far system having a
    record. WITH one, it becomes `posted` and that reference is its evidence.
    """
    posting = (
        await db.execute(
            select(SystemOfRecordPosting).where(
                SystemOfRecordPosting.organization_id == str(org_id),
                SystemOfRecordPosting.id == str(posting_id),
            )
        )
    ).scalars().first()
    if posting is None:
        raise HTTPException(status_code=404, detail="posting not found")
    if posting.status not in (PostingStatus.MANUAL_REQUIRED, PostingStatus.FAILED):
        raise HTTPException(
            status_code=400,
            detail=(
                f"posting is {posting.status}; only a manual_required or failed posting is "
                "acknowledged by a person"
            ),
        )

    await acknowledge_manual(db, posting, str(current_user.id), payload.external_ref)
    await db.commit()
    return _posting_out(posting)


@router.post(
    "/postings/drain",
    dependencies=[Depends(require_operator_or_admin)],
    response_model=DrainOut,
)
async def drain_postings(
    limit: int = Query(50, ge=1, le=500),
    org_id=Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    """Attempt every queued posting against its ERP.

    WHAT THIS HONESTLY DOES TODAY: no connector in this repository has a verified write
    path, so most attempts end in a refusal and the posting becomes `manual_required` with
    an instruction. That is the point — it converts "queued behind an integration that will
    never take it" into "somebody has to enter this, and here is what to tell them".
    """
    result = await drain(db, str(org_id), limit=limit)
    await db.commit()
    return DrainOut(
        **result.summary(),
        note=(
            "postings that could not be written are now manual_required with an "
            "instruction, rather than left queued behind a write path that does not exist"
        ),
    )


@router.get("/routing", response_model=RoutingOut)
async def routing_mandate():
    """Which systems each event type must reach.

    Exposed so the mandate is inspectable rather than buried in a service — a reader can
    check the four claims against the requirement without tracing call sites.
    """
    return {
        "routing": {event: list(targets) for event, targets in ROUTING.items()},
        "target_systems": list(TargetSystem.ALL),
        "posting_statuses": {
            "pending": "an integration exists and has not taken it yet",
            "posted": "the target system accepted it and returned an identifier",
            "failed": "the target system was tried and refused",
            "manual_required": "no integration for this target — a person must be told",
            "not_applicable": "this deployment deliberately does not route here",
        },
    }


async def _existing_fanout(db: AsyncSession, event_type: str, event_id: str) -> FanoutOut:
    """Rebuild the summary for an event that was fanned out earlier."""
    rows = (
        await db.execute(
            select(SystemOfRecordPosting).where(
                SystemOfRecordPosting.event_type == event_type,
                SystemOfRecordPosting.event_id == event_id,
            )
        )
    ).scalars().all()
    counts: dict[str, int] = {}
    for p in rows:
        counts[p.status] = counts.get(p.status, 0) + 1
    return FanoutOut(
        event_type=event_type, event_id=event_id, targets=len(rows), by_status=counts,
        fully_posted=bool(rows) and all(p.status == PostingStatus.POSTED for p in rows),
        awaiting_a_person=[
            {"target": p.target_system, "instruction": p.instruction}
            for p in rows if p.status == PostingStatus.MANUAL_REQUIRED
        ],
    )

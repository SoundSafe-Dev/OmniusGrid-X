"""Activate a correlation-AI recommendation (FS-406), at `/api/v1/insights`.

Three verbs, and the middle one is the reason the surface exists:

    POST /activations                        issue it — Kanban task + posting ledger
    GET  /activations                        what has been issued and where it stands
    GET  /activations/{id}                   one, with its task and every posting
    POST /activations/{id}/confirm           validate: REFUSES while anything is outstanding
    POST /activations/{id}/reject            decline it, with a reason
    POST /activations/{id}/postings/{pid}/acknowledge
                                             a person did the analog step
    GET  /domain-routing                     which systems each domain reaches

WHAT ACTIVATION RETURNS. Never "dispatched". It returns the task it created (or the reason
it could not), and one line per external system with that system's own status — including
`awaiting_a_person`, naming the target and the sentence to read out. A shop whose purchasing
is a phone call is not a broken deployment, and the honest response is a script for the
supervisor plus a record of whether they used it.

CONFIRM IS A GATE, NOT A BUTTON. It returns 409 with the list of blockers while the task is
unfinished or any posting lacks evidence. A confirm that always succeeds is decoration, and
the UI already had one of those.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, List, Optional
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.responses import conflict_response
from app.api.auth import get_current_active_user
from app.core.tenant import get_tenant_db, get_tenant_org_id
from app.db.insight_models import ActivationSource, ActivationStatus, InsightActivation
from app.db.models import Task, User
from app.db.shop_floor_models import PostingStatus, SystemOfRecordPosting, TargetSystem
from app.middleware.rbac import require_operator_or_admin
from app.services.insight_activation import (
    DEFAULT_TARGETS, DOMAIN_TARGETS, activate, confirm, outstanding_blockers, postings_for,
    reject, targets_for_domain,
)
from app.services.shop_floor_fanout import acknowledge_manual

logger = structlog.get_logger()

router = APIRouter(dependencies=[Depends(get_current_active_user)])


# ------------------------------------------------------------------------------- schemas
class ActivationPostingOut(BaseModel):
    """One external system this activation has to reach, and where that stands."""

    id: str
    target_system: str
    status: str
    external_ref: Optional[str] = None
    #: Present only for `manual_required` — the sentence to give a person.
    instruction: Optional[str] = None
    acknowledged_at: Optional[datetime] = None
    posted_at: Optional[datetime] = None
    last_error: Optional[str] = None


class ActivationTaskOut(BaseModel):
    """The Kanban task, as much of it as this surface needs to speak about."""

    id: str
    title: str
    task_type: str
    status: str
    priority: str
    board_id: Optional[str] = None
    column_id: Optional[str] = None


class ActivationOut(BaseModel):
    id: str
    title: str
    description: Optional[str] = None
    domain: Optional[str] = None
    priority: str
    source: str
    session_id: Optional[str] = None
    message_id: Optional[str] = None
    action_index: Optional[int] = None
    status: str
    issued_at: Optional[datetime] = None
    confirmed_at: Optional[datetime] = None
    rejected_at: Optional[datetime] = None
    rejection_reason: Optional[str] = None

    #: Null when no task could be created. `task_blocked_reason` then says why, instead of
    #: leaving a caller to guess that a missing task means a missing board.
    task: Optional[ActivationTaskOut] = None
    task_blocked_reason: Optional[str] = None

    postings: List[ActivationPostingOut]
    #: True only when every posting carries evidence AND the task is finished. Computed, not
    #: stored — a stored flag drifts from the postings it claims to summarise.
    ready_to_confirm: bool
    #: What stands in the way, in words an operator can act on.
    blockers: List[dict] = Field(default_factory=list)
    #: The postings still needing a human, with the line to read out.
    awaiting_a_person: List[dict] = Field(default_factory=list)
    #: The snapshot confirmation was granted on. Null until confirmed.
    validation: Optional[dict] = None
    #: True when this call matched an existing activation instead of creating one — a retry
    #: or a double click. Reported so the UI does not narrate a second dispatch.
    already_existed: bool = False


class ActivationPage(BaseModel):
    items: List[ActivationOut]
    total: int
    limit: int
    truncated: bool


class ActivateRequest(BaseModel):
    """One recommendation to act on.

    `session_id`/`message_id`/`action_index` identify WHICH recommendation, and together with
    the title they form the fingerprint that makes this idempotent. Omitting them is allowed
    — a manually entered action is legitimate — but then only the title distinguishes it.
    """

    title: str = Field(..., min_length=1, max_length=500)
    description: Optional[str] = None
    domain: Optional[str] = Field(None, max_length=100)
    priority: str = Field("medium", pattern="^(low|medium|high|critical|emergency)$")
    source: str = Field(ActivationSource.ANALYSIS_SESSION, max_length=40)
    session_id: Optional[UUID] = None
    message_id: Optional[UUID] = None
    action_index: Optional[int] = Field(None, ge=0)
    asset_id: Optional[UUID] = None
    #: Override the domain-derived fan-out. Rare, and validated: a caller naming a system
    #: this deployment does not have would otherwise create a posting nobody can ever clear.
    targets: Optional[List[str]] = None


class RejectRequest(BaseModel):
    #: Required. A rejected recommendation is training data; a deleted one is nothing.
    reason: str = Field(..., min_length=1)


class AcknowledgeRequest(BaseModel):
    """A person confirming they did the analog step.

    With an `external_ref` — the requisition number they wrote down — the posting becomes
    `posted` and that reference is its evidence. Without one it records who acted and when,
    and stays `manual_required`, because telling somebody is not the same as the far system
    having a record.
    """

    external_ref: Optional[str] = Field(None, max_length=200)


class DomainRoutingOut(BaseModel):
    """Which systems of record each correlation domain reaches."""

    routing: dict
    default_targets: List[str]
    default_reason: str
    target_systems: List[str]


# ------------------------------------------------------------------------------- helpers
def _posting_out(p: SystemOfRecordPosting) -> ActivationPostingOut:
    return ActivationPostingOut(
        id=str(p.id), target_system=p.target_system, status=p.status,
        external_ref=p.external_ref, instruction=p.instruction,
        acknowledged_at=p.acknowledged_at, posted_at=p.posted_at, last_error=p.last_error,
    )


def _task_out(task: Optional[Task]) -> Optional[ActivationTaskOut]:
    if task is None:
        return None
    return ActivationTaskOut(
        id=str(task.id), title=task.title, task_type=task.task_type,
        status=task.status, priority=task.priority,
        board_id=str(task.board_id) if task.board_id else None,
        column_id=str(task.column_id) if task.column_id else None,
    )


async def _render(
    db: AsyncSession,
    activation: InsightActivation,
    *,
    task: Optional[Task] = None,
    postings: Optional[List[SystemOfRecordPosting]] = None,
    already_existed: bool = False,
    task_blocked_reason: Optional[str] = None,
) -> ActivationOut:
    if postings is None:
        postings = await postings_for(db, activation.id)
    if task is None and activation.task_id:
        task = await db.get(Task, activation.task_id)

    blockers = (
        await outstanding_blockers(db, activation)
        if activation.status == ActivationStatus.ISSUED
        else []
    )
    return ActivationOut(
        id=str(activation.id), title=activation.title, description=activation.description,
        domain=activation.domain, priority=activation.priority, source=activation.source,
        session_id=str(activation.session_id) if activation.session_id else None,
        message_id=str(activation.message_id) if activation.message_id else None,
        action_index=activation.action_index, status=activation.status,
        issued_at=activation.issued_at, confirmed_at=activation.confirmed_at,
        rejected_at=activation.rejected_at, rejection_reason=activation.rejection_reason,
        task=_task_out(task),
        task_blocked_reason=(
            task_blocked_reason
            or (None if task or activation.task_id else "no Kanban task was created")
        ),
        postings=[_posting_out(p) for p in postings],
        ready_to_confirm=(activation.status == ActivationStatus.ISSUED and not blockers),
        blockers=blockers,
        awaiting_a_person=[
            {"target": p.target_system, "instruction": p.instruction, "posting_id": str(p.id)}
            for p in postings
            if p.status == PostingStatus.MANUAL_REQUIRED and not p.acknowledged_at
        ],
        validation=activation.validation,
        already_existed=already_existed,
    )


async def _load(db: AsyncSession, org_id: Any, activation_id: UUID) -> InsightActivation:
    activation = (
        await db.execute(
            select(InsightActivation).where(
                and_(
                    InsightActivation.organization_id == str(org_id),
                    InsightActivation.id == str(activation_id),
                )
            )
        )
    ).scalars().first()
    if activation is None:
        raise HTTPException(status_code=404, detail="activation not found")
    return activation


# -------------------------------------------------------------------------------- routes
@router.post(
    "/activations",
    dependencies=[Depends(require_operator_or_admin)],
    response_model=ActivationOut,
    status_code=status.HTTP_201_CREATED,
)
async def activate_insight(
    payload: ActivateRequest,
    org_id=Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
    current_user: User = Depends(get_current_active_user),
):
    """Turn one recommended action into a Kanban task and postings to the systems of record.

    The response says what was created and what each external system's state is. It does not
    say the action is done — at this moment nothing has been done, and the postings say so.
    """
    if payload.targets:
        unknown = [t for t in payload.targets if t not in TargetSystem.ALL]
        if unknown:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"unknown target system(s) {unknown}; expected any of "
                    f"{list(TargetSystem.ALL)}"
                ),
            )

    result = await activate(
        db,
        organization_id=str(org_id),
        user_id=str(current_user.id),
        title=payload.title,
        description=payload.description,
        domain=payload.domain,
        priority=payload.priority,
        source=payload.source,
        session_ref=str(payload.session_id) if payload.session_id else None,
        message_ref=str(payload.message_id) if payload.message_id else None,
        action_index=payload.action_index,
        asset_id=str(payload.asset_id) if payload.asset_id else None,
        targets=tuple(payload.targets) if payload.targets else None,
    )
    await db.commit()

    return await _render(
        db, result.activation, task=result.task, postings=result.postings,
        already_existed=result.already_existed,
        task_blocked_reason=result.task_blocked_reason,
    )


@router.get("/activations", response_model=ActivationPage)
async def list_activations(
    status_filter: Optional[str] = Query(None, alias="status"),
    session_id: Optional[UUID] = None,
    limit: int = Query(50, ge=1, le=200),
    org_id=Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    """Issued insights and where each one stands."""
    if status_filter and status_filter not in ActivationStatus.ALL:
        raise HTTPException(
            status_code=422,
            detail=(
                f"unknown status {status_filter!r}; expected one of "
                f"{list(ActivationStatus.ALL)}"
            ),
        )
    query = select(InsightActivation).where(
        InsightActivation.organization_id == str(org_id)
    )
    if status_filter:
        query = query.where(InsightActivation.status == status_filter)
    if session_id:
        query = query.where(InsightActivation.session_id == str(session_id))

    from sqlalchemy import func

    total = (
        await db.execute(select(func.count()).select_from(query.subquery()))
    ).scalar() or 0
    rows = (
        await db.execute(query.order_by(InsightActivation.issued_at.desc()).limit(limit))
    ).scalars().all()

    items = [await _render(db, a) for a in rows]
    return ActivationPage(
        items=items, total=total, limit=limit, truncated=total > len(items)
    )


@router.get("/activations/{activation_id}", response_model=ActivationOut)
async def get_activation(
    activation_id: UUID,
    org_id=Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    return await _render(db, await _load(db, org_id, activation_id))


@router.post(
    "/activations/{activation_id}/confirm",
    dependencies=[Depends(require_operator_or_admin)],
    response_model=ActivationOut,
    responses={**conflict_response},
)
async def confirm_activation(
    activation_id: UUID,
    org_id=Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
    current_user: User = Depends(get_current_active_user),
):
    """Validate and confirm.

    409 WITH THE BLOCKERS while the task is unfinished or a posting lacks evidence. The
    refusal is the feature: it is what makes a confirmation mean something when it succeeds.
    """
    activation = await _load(db, org_id, activation_id)
    confirmed, blockers = await confirm(db, activation, str(current_user.id))
    if not confirmed:
        await db.rollback()
        raise HTTPException(
            status_code=409,
            detail={
                "message": (
                    "this activation cannot be confirmed yet — the work is not finished or a "
                    "system of record has no evidence it received anything"
                ),
                "blockers": blockers,
            },
        )
    await db.commit()
    return await _render(db, activation)


@router.post(
    "/activations/{activation_id}/reject",
    dependencies=[Depends(require_operator_or_admin)],
    response_model=ActivationOut,
    responses={**conflict_response},
)
async def reject_activation(
    activation_id: UUID,
    payload: RejectRequest,
    org_id=Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
    current_user: User = Depends(get_current_active_user),
):
    """Decline a recommendation. The reason is required and is kept."""
    activation = await _load(db, org_id, activation_id)
    if activation.status == ActivationStatus.CONFIRMED:
        raise HTTPException(
            status_code=409,
            detail="this activation was already confirmed and cannot be rejected",
        )
    try:
        await reject(db, activation, str(current_user.id), payload.reason)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    await db.commit()
    return await _render(db, activation)


@router.post(
    "/activations/{activation_id}/postings/{posting_id}/acknowledge",
    dependencies=[Depends(require_operator_or_admin)],
    response_model=ActivationOut,
)
async def acknowledge_activation_posting(
    activation_id: UUID,
    posting_id: UUID,
    payload: AcknowledgeRequest,
    org_id=Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
    current_user: User = Depends(get_current_active_user),
):
    """The analog path: "I told them, and here is the reference they gave me".

    Returns the whole activation rather than the one posting, because the thing the operator
    needs to know next is whether that was the last outstanding item.
    """
    activation = await _load(db, org_id, activation_id)
    posting = (
        await db.execute(
            select(SystemOfRecordPosting).where(
                and_(
                    SystemOfRecordPosting.organization_id == str(org_id),
                    SystemOfRecordPosting.id == str(posting_id),
                    SystemOfRecordPosting.event_id == str(activation.id),
                )
            )
        )
    ).scalars().first()
    if posting is None:
        raise HTTPException(
            status_code=404, detail="posting not found on this activation"
        )
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
    return await _render(db, activation)


@router.get("/domain-routing", response_model=DomainRoutingOut)
async def domain_routing():
    """Which systems of record each correlation domain reaches.

    Served so the mapping is inspectable from the running system. `default_reason` is
    included because a one-target fan-out for an unmapped domain looks like a routing
    decision, and a reader should be able to tell that it is a fallback.
    """
    _, _used_default = targets_for_domain(None)
    return DomainRoutingOut(
        routing={domain: list(targets) for domain, targets in DOMAIN_TARGETS.items()},
        default_targets=list(DEFAULT_TARGETS),
        default_reason=(
            "a domain nobody has mapped reaches production only — fanning an unclassified "
            "recommendation out to accounting would post money movements no one asked for"
        ),
        target_systems=list(TargetSystem.ALL),
    )

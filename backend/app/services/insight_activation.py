"""Activate a correlation-AI recommendation: Kanban task + systems of record (FS-406).

WHAT THIS REPLACES. `CorrelationAIPane` renders each recommended action as a bullet with a
green tick and no control. The only way to act on one was an "Auto-integrate" checkbox that
handed the whole analysis to a background job; the job could create nothing and the user
would never learn that. So the product's central promise — an insight becomes dispatched
work in the Kanban and in the ERP — had no path a person could take, and no evidence when
the automatic path was taken for them.

THE THREE VERBS.

  issue      `activate()` creates the Kanban task AND the posting ledger for every external
             system the insight's domain implies. It returns what it made. It does NOT
             report success: at that moment nothing has been done, and saying otherwise is
             the exact failure the posting ledger was built to stop.
  confirm    `confirm()` REFUSES while any part is still outstanding, and names what is
             missing. Confirmation writes the snapshot it was granted on.
  reject     `reject()` requires a reason, because a rejected recommendation is training
             data and a deleted one is nothing.

IDEMPOTENCY IS A CORRECTNESS PROPERTY HERE, NOT A NICETY. Activate is a button on a slow
network in a noisy building. Without the fingerprint, a double click issues two work orders
and posts twice to purchasing, and the second one is indistinguishable from a real
requirement. `activate()` returns the existing activation instead, unchanged.

WHERE THE TARGETS COME FROM. An insight is not one of the four floor events, so it has no
row in `ROUTING`. Its targets are derived from its correlation domain — a maintenance
recommendation reaches scheduling, production and maintenance; a quality one reaches quality
and production. A domain nobody has mapped falls back to `production` alone, and says so in
`meta_data`, because inventing a fan-out to accounting for an unrecognised domain would post
money movements nobody asked for.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Optional

import structlog
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.datetime_utils import utcnow
from app.db.insight_models import ActivationSource, ActivationStatus, InsightActivation
from app.db.models import Task, TaskBoard, TaskColumn
from app.db.shop_floor_models import EventType, PostingStatus, SystemOfRecordPosting, TargetSystem
from app.services.shop_floor_fanout import fan_out

logger = structlog.get_logger()

_T = TargetSystem

#: Which systems of record an insight must reach, by correlation domain.
#:
#: Read against `DOMAIN_REGISTRY_MAPPING` in correlation_registry_integration.py, which names
#: the domains the analysis engine emits. Domains absent here are not an oversight — see
#: DEFAULT_TARGETS.
DOMAIN_TARGETS: dict[str, tuple[str, ...]] = {
    # Material and stock movement
    "WAREHOUSE_MANAGEMENT": (_T.INVENTORY, _T.PRODUCTION),
    "MATERIAL_REPLENISHMENT": (_T.INVENTORY, _T.PURCHASING),
    "SPARE_PARTS": (_T.INVENTORY, _T.PURCHASING, _T.MAINTENANCE),
    "INVENTORY_OPTIMIZATION": (_T.INVENTORY, _T.PURCHASING, _T.ACCOUNTING),
    "SUPPLY_CHAIN": (_T.PURCHASING, _T.INVENTORY, _T.SCHEDULING),
    "SUPPLIER_RELATIONSHIP": (_T.PURCHASING, _T.QUALITY),
    "DISTRIBUTION": (_T.SCHEDULING, _T.INVENTORY),
    "LOGISTICS_FLEET": (_T.SCHEDULING, _T.MAINTENANCE),
    "PACKAGING": (_T.PRODUCTION, _T.INVENTORY),

    # Making things
    "PRODUCTION_OEE": (_T.PRODUCTION, _T.SCHEDULING),
    "PRODUCTION_OUTPUT": (_T.PRODUCTION, _T.SCHEDULING, _T.ACCOUNTING),
    "MANUFACTURING_EXECUTION_SYSTEM": (_T.PRODUCTION, _T.SCHEDULING),
    "PROCESS_OPTIMIZATION": (_T.PRODUCTION, _T.QUALITY),
    "PRODUCT_LIFECYCLE": (_T.PRODUCTION, _T.QUALITY),

    # Keeping machines running — the four-system tie-in the downtime event also uses
    "MAINTENANCE": (_T.MAINTENANCE, _T.SCHEDULING, _T.PRODUCTION),
    "ASSET_LIFECYCLE": (_T.MAINTENANCE, _T.ACCOUNTING),
    "TOOL_MANAGEMENT": (_T.MAINTENANCE, _T.INVENTORY),
    "CALIBRATION": (_T.MAINTENANCE, _T.QUALITY),
    "FACILITIES_MANAGEMENT": (_T.MAINTENANCE, _T.SCHEDULING),
    "ENERGY_MANAGEMENT": (_T.PRODUCTION, _T.ACCOUNTING),

    # Conformance
    "QUALITY_CONTROL": (_T.QUALITY, _T.PRODUCTION),
    "REGULATORY_AUDIT": (_T.QUALITY,),
    "COMPLIANCE_REGISTRIES": (_T.QUALITY,),
    "SAFETY": (_T.QUALITY, _T.MAINTENANCE),
    "ENVIRONMENTAL": (_T.QUALITY,),
    "ESG": (_T.QUALITY, _T.ACCOUNTING),
    "RISK_MANAGEMENT": (_T.QUALITY, _T.SCHEDULING),

    # People and money
    "WORKFORCE_MANAGEMENT": (_T.SCHEDULING, _T.PRODUCTION),
    "HR_ORGANIZATIONAL": (_T.SCHEDULING,),
    "FINANCE": (_T.ACCOUNTING,),
    "CONTRACT_MANAGEMENT": (_T.ACCOUNTING, _T.PURCHASING),
    "PROJECT_MANAGEMENT": (_T.SCHEDULING,),
    "CHANGE_MANAGEMENT": (_T.SCHEDULING, _T.PRODUCTION),
    "CONTINUOUS_IMPROVEMENT": (_T.PRODUCTION, _T.QUALITY),
}

#: An unmapped domain gets production and nothing else.
#:
#: The tempting default is "everything", and it is wrong. A fan-out to accounting is a claim
#: that a finance system needs to hear about this, and manufacturing that claim for a domain
#: nobody has classified would fill an accounts queue with items no one can act on — the
#: analog path made worse, since a person then has to be told about each one. Production is
#: the one system that plausibly cares about any operational recommendation, and the
#: activation records that the default was used so it is visible rather than assumed.
DEFAULT_TARGETS: tuple[str, ...] = (_T.PRODUCTION,)

#: Recommendation title -> Kanban task_type, extending the correlation service's own mapping
#: with the verbs that actually appear in session recommendations. Anything unmatched becomes
#: `custom`, which is the schema's honest value for "we do not know what kind of work this is".
_TASK_TYPE_HINTS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("preventive", "pm ", "inspect bearing", "lubricat"), "maintenance_pm"),
    (("repair", "replace", "corrective", "fix ", "rebuild"), "maintenance_cm"),
    (("inspect", "quality", "defect", "scrap", "non-conform", "nonconform"), "quality_inspection"),
    (("safety", "lockout", "hazard", "ppe"), "safety_check"),
    (("schedule", "reschedule", "shift ", "changeover"), "changeover"),
    (("order", "reorder", "requisition", "purchase", "restock"), "material_request"),
    (("alarm", "alert", "escalate"), "alarm_response"),
    (("run ", "execute", "start "), "command_execution"),
)


def _task_type_for(title: str) -> str:
    lowered = (title or "").lower()
    for needles, task_type in _TASK_TYPE_HINTS:
        if any(needle in lowered for needle in needles):
            return task_type
    return "custom"


def targets_for_domain(domain: Optional[str]) -> tuple[tuple[str, ...], bool]:
    """(targets, used_default). The flag is returned rather than inferred by the caller so
    the activation can record that nobody had classified this domain."""
    key = (domain or "").strip().upper()
    mapped = DOMAIN_TARGETS.get(key)
    if mapped:
        return mapped, False
    return DEFAULT_TARGETS, True


def action_fingerprint(
    *,
    source: str,
    session_id: Optional[str],
    message_id: Optional[str],
    action_index: Optional[int],
    title: str,
) -> str:
    """Stable identity for one recommendation.

    Title is included alongside the index because a regenerated message can shift positions;
    index alone would let a different recommendation inherit an earlier one's activation, and
    title alone would block two genuinely distinct steps that happen to be worded the same.
    """
    parts = [
        source or "",
        str(session_id or ""),
        str(message_id or ""),
        "" if action_index is None else str(action_index),
        (title or "").strip().lower(),
    ]
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ActivationResult:
    """What activation produced, and whether it produced it now or had already."""

    activation: InsightActivation
    task: Optional[Task]
    postings: list[SystemOfRecordPosting]
    #: True when the fingerprint already existed. The caller returns 200 rather than 201 and
    #: says so, instead of letting a retry look like a second dispatch.
    already_existed: bool
    #: Set when no Kanban task could be created, naming the reason. The activation still
    #: exists — an insight that reached the ERP but has no task is a real state and hiding it
    #: would leave the work invisible on the board.
    task_blocked_reason: Optional[str] = None


async def _pick_board_and_column(
    session: AsyncSession, organization_id: str
) -> tuple[Optional[TaskBoard], Optional[TaskColumn], Optional[str]]:
    """Where a new activated task lands: the org's active board, triage column, else backlog.

    Returns a reason string instead of a bare None so the API can tell an operator "this
    organisation has no active task board" rather than silently producing an activation with
    no task — the behaviour of the existing correlation integration, which returns None from
    three different places with no way to tell them apart.
    """
    board = (
        await session.execute(
            select(TaskBoard).where(
                and_(TaskBoard.organization_id == organization_id, TaskBoard.is_active.is_(True))
            ).limit(1)
        )
    ).scalars().first()
    if board is None:
        return None, None, "this organisation has no active task board"

    column = (
        await session.execute(
            select(TaskColumn)
            .where(and_(TaskColumn.board_id == board.id, TaskColumn.column_type == "triage"))
            .limit(1)
        )
    ).scalars().first()
    if column is None:
        column = (
            await session.execute(
                select(TaskColumn)
                .where(and_(TaskColumn.board_id == board.id, TaskColumn.column_type == "backlog"))
                .limit(1)
            )
        ).scalars().first()
    if column is None:
        return board, None, f"board {board.id} has no triage or backlog column"
    return board, column, None


async def activate(
    session: AsyncSession,
    *,
    organization_id: str,
    user_id: str,
    title: str,
    description: Optional[str] = None,
    domain: Optional[str] = None,
    priority: str = "medium",
    source: str = ActivationSource.ANALYSIS_SESSION,
    session_ref: Optional[str] = None,
    message_ref: Optional[str] = None,
    action_index: Optional[int] = None,
    asset_id: Optional[str] = None,
    targets: Optional[tuple[str, ...]] = None,
) -> ActivationResult:
    """Issue one recommendation as real work. See the module docstring for the contract."""
    fingerprint = action_fingerprint(
        source=source,
        session_id=session_ref,
        message_id=message_ref,
        action_index=action_index,
        title=title,
    )

    existing = (
        await session.execute(
            select(InsightActivation).where(
                and_(
                    InsightActivation.organization_id == organization_id,
                    InsightActivation.action_fingerprint == fingerprint,
                )
            )
        )
    ).scalars().first()
    if existing is not None:
        postings = await postings_for(session, existing.id)
        task = (
            await session.get(Task, existing.task_id) if existing.task_id else None
        )
        return ActivationResult(
            activation=existing, task=task, postings=postings, already_existed=True
        )

    resolved_targets, used_default = (
        (tuple(targets), False) if targets else targets_for_domain(domain)
    )

    activation = InsightActivation(
        organization_id=organization_id,
        session_id=session_ref,
        message_id=message_ref,
        source=source,
        action_index=action_index,
        action_fingerprint=fingerprint,
        title=title[:500],
        description=description,
        domain=domain,
        priority=priority,
        status=ActivationStatus.ISSUED,
        issued_by=user_id,
        issued_at=utcnow(),
        meta_data={
            "targets": list(resolved_targets),
            # Recorded, not inferred: a reader can see that no one had classified this domain
            # rather than reading the narrow fan-out as a deliberate routing decision.
            "used_default_targets": used_default,
            "asset_id": asset_id,
        },
    )
    session.add(activation)
    await session.flush()

    board, column, task_blocked = await _pick_board_and_column(session, organization_id)
    task: Optional[Task] = None
    if column is not None and board is not None:
        max_position = (
            await session.execute(
                select(func.max(Task.position)).where(Task.column_id == column.id)
            )
        ).scalar() or 0
        task = Task(
            board_id=board.id,
            column_id=column.id,
            position=max_position + 1,
            title=title[:500],
            description=description,
            task_type=_task_type_for(title),
            priority=priority,
            status="ready",
            asset_id=asset_id,
            tags=["correlation_ai", "activated_insight"],
            custom_fields={
                "source": source,
                "domain": domain,
                "activation_id": str(activation.id),
                "session_id": str(session_ref) if session_ref else None,
            },
            # A person clicked Activate, so a person approved it — unlike the existing
            # correlation path, which stamps `approved` on tasks nobody looked at.
            approval_status="approved",
            approved_by=user_id,
            approved_at=utcnow(),
            created_by=user_id,
            created_at=utcnow(),
        )
        session.add(task)
        await session.flush()
        activation.task_id = task.id

    fanout = await fan_out(
        session,
        organization_id,
        activation,
        EventType.INSIGHT_ACTIVATION,
        targets=resolved_targets,
    )
    await session.flush()

    logger.info(
        "insight_activated",
        activation_id=str(activation.id),
        organization_id=organization_id,
        domain=domain,
        task_created=task is not None,
        task_blocked_reason=task_blocked,
        targets=list(resolved_targets),
    )
    return ActivationResult(
        activation=activation,
        task=task,
        postings=fanout.postings,
        already_existed=False,
        task_blocked_reason=task_blocked if task is None else None,
    )


async def postings_for(
    session: AsyncSession, activation_id: Any
) -> list[SystemOfRecordPosting]:
    return list(
        (
            await session.execute(
                select(SystemOfRecordPosting).where(
                    and_(
                        SystemOfRecordPosting.event_type == EventType.INSIGHT_ACTIVATION,
                        SystemOfRecordPosting.event_id == str(activation_id),
                    )
                ).order_by(SystemOfRecordPosting.target_system)
            )
        ).scalars().all()
    )


async def outstanding_blockers(
    session: AsyncSession, activation: InsightActivation
) -> list[dict[str, Any]]:
    """Everything that stands between this activation and an honest confirmation.

    Returned as a list of reasons rather than a boolean so the UI can show a person exactly
    what is left — "purchasing still needs a requisition number" is actionable; "cannot
    confirm" is not.
    """
    blockers: list[dict[str, Any]] = []

    if activation.task_id:
        task = await session.get(Task, activation.task_id)
        if task is None:
            blockers.append({
                "kind": "task",
                "reason": "the Kanban task this activation created no longer exists",
            })
        elif task.status not in ("completed", "cancelled"):
            blockers.append({
                "kind": "task",
                "task_id": str(task.id),
                "status": task.status,
                "reason": f"the Kanban task is {task.status}, not completed",
            })
    else:
        blockers.append({
            "kind": "task",
            "reason": "no Kanban task was created for this activation",
        })

    for posting in await postings_for(session, activation.id):
        if posting.status == PostingStatus.POSTED:
            continue
        if posting.status == PostingStatus.NOT_APPLICABLE:
            continue
        if posting.status == PostingStatus.MANUAL_REQUIRED and posting.acknowledged_at:
            # Someone has said they did the analog step. That is weaker than a reference from
            # the far system, and the validation snapshot records which kind of evidence this
            # was — but a person's acknowledgement is evidence, so it does not block.
            continue
        blockers.append({
            "kind": "posting",
            "posting_id": str(posting.id),
            "target": posting.target_system,
            "status": posting.status,
            "reason": _posting_blocker_reason(posting),
        })
    return blockers


def _posting_blocker_reason(posting: SystemOfRecordPosting) -> str:
    if posting.status == PostingStatus.MANUAL_REQUIRED:
        return (
            f"{posting.target_system} has no integration and nobody has confirmed the manual "
            f"step yet"
        )
    if posting.status == PostingStatus.FAILED:
        return f"the posting to {posting.target_system} failed: {posting.last_error or 'no detail'}"
    return f"the posting to {posting.target_system} has not been sent yet"


async def confirm(
    session: AsyncSession, activation: InsightActivation, user_id: str
) -> tuple[bool, list[dict[str, Any]]]:
    """Validate and confirm. Returns (confirmed, blockers).

    REFUSES rather than confirms when anything is outstanding. This is the whole point: a
    confirm button that always succeeds is a decoration, and the product already had one of
    those in the "Auto-integrate" checkbox.
    """
    if activation.status == ActivationStatus.CONFIRMED:
        return True, []
    if activation.status in (ActivationStatus.REJECTED, ActivationStatus.CANCELLED):
        return False, [{
            "kind": "status",
            "reason": f"this activation was {activation.status} and cannot be confirmed",
        }]

    blockers = await outstanding_blockers(session, activation)
    if blockers:
        return False, blockers

    postings = await postings_for(session, activation.id)
    task = await session.get(Task, activation.task_id) if activation.task_id else None
    activation.status = ActivationStatus.CONFIRMED
    activation.confirmed_by = user_id
    activation.confirmed_at = utcnow()
    activation.validation = {
        "confirmed_at": activation.confirmed_at.isoformat(),
        "task": {
            "id": str(task.id),
            "status": task.status,
            "completed_at": task.completed_at.isoformat() if task and task.completed_at else None,
        } if task else None,
        "postings": [
            {
                "target": p.target_system,
                "status": p.status,
                "external_ref": p.external_ref,
                # Which kind of evidence this was. A far system's identifier and a person
                # saying they phoned it through are both acceptable and are not the same
                # thing, so the snapshot keeps them apart.
                "evidence": (
                    "external_reference" if p.external_ref
                    else "human_acknowledgement" if p.acknowledged_at
                    else "none"
                ),
            }
            for p in postings
        ],
    }
    await session.flush()
    logger.info(
        "insight_activation_confirmed",
        activation_id=str(activation.id),
        targets=[p.target_system for p in postings],
    )
    return True, []


async def reject(
    session: AsyncSession, activation: InsightActivation, user_id: str, reason: str
) -> InsightActivation:
    """Decline a recommendation, with a reason the database insists on."""
    if not (reason or "").strip():
        raise ValueError(
            "a rejection needs a reason — a recommendation that keeps being rejected is a "
            "bad recommendation, and that is only learnable if the reason is recorded"
        )
    activation.status = ActivationStatus.REJECTED
    activation.rejected_by = user_id
    activation.rejected_at = utcnow()
    activation.rejection_reason = reason.strip()
    await session.flush()
    return activation

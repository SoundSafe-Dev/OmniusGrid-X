"""Route a shop-floor event to the systems of record that need it (FS-405).

    a part is issued        -> inventory, purchasing, accounting
    time is clocked         -> production, accounting
    a problem is found      -> quality, inventory, production, accounting
    a machine goes down     -> scheduling, production, quality, accounting

WHAT THIS DELIBERATELY DOES NOT DO: claim a side effect it did not perform.

Every arrow above becomes a row in `system_of_record_postings` with its own status, and the
status is decided by what actually happened to THAT target. An event is never "synced". It
is posted to inventory, queued for accounting, and awaiting a human for purchasing — three
different facts about three different systems, which a boolean could not hold and which the
caller can now read individually.

THREE OUTCOMES, AND THE THIRD IS THE INTERESTING ONE.

  posted           an integration accepted it and returned an identifier. The identifier is
                   stored, and the database refuses `posted` without one — evidence, not
                   assertion.
  pending/failed   there is an integration and it has not taken it yet, or it refused.
                   Separate statuses because "not tried" and "tried and rejected" are a
                   queue to drain and an incident to investigate.
  manual_required  THERE IS NO INTEGRATION FOR THIS TARGET, so a person has to be told. The
                   posting carries the sentence to tell them.

That last one is the analog path, and it is a feature rather than a fallback. A shop whose
purchasing runs on a phone call is not a broken deployment, and the honest thing is to hand
a supervisor a line to read out and then record whether they did. Silently dropping it — or
worse, marking it done — is exactly the failure this repository keeps finding.

CONFIGURATION IS NOT INVENTED. Whether a target has an integration is read from the
organisation's `integration_configurations`; nothing here guesses. If a shop has decided an
event does not go somewhere, that is `not_applicable`, which is a decision someone made and
not the same as nobody having looked.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Iterable, Optional

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.datetime_utils import utcnow
from app.db.models import IntegrationConfiguration
from app.db.shop_floor_models import (
    DowntimeEvent, EventType, LaborEntry, PartIssue, PostingStatus, QualityEvent,
    SystemOfRecordPosting, TargetSystem,
)

logger = structlog.get_logger()


#: Which systems each event must reach. This is the mandate in one place, so a reader can
#: check it against the requirement without tracing four call sites.
#:
#: Ordered most-specific first only for readability; nothing depends on the order.
ROUTING: dict[str, tuple[str, ...]] = {
    EventType.PART_ISSUE: (
        TargetSystem.INVENTORY,    # stock goes down
        TargetSystem.PURCHASING,   # it may need reordering
        TargetSystem.ACCOUNTING,   # it costs money
    ),
    EventType.LABOR_ENTRY: (
        TargetSystem.PRODUCTION,   # the job consumed hours
        TargetSystem.ACCOUNTING,   # the hours are payroll and job cost
    ),
    EventType.QUALITY_EVENT: (
        TargetSystem.QUALITY,      # the non-conformance record
        TargetSystem.INVENTORY,    # scrap removes stock
        TargetSystem.PRODUCTION,   # the order is short
        TargetSystem.ACCOUNTING,   # somebody pays for the scrap
    ),
    EventType.DOWNTIME_EVENT: (
        TargetSystem.SCHEDULING,   # the plan has to move
        TargetSystem.PRODUCTION,   # the order is late
        TargetSystem.QUALITY,      # a stop is a quality signal
        TargetSystem.ACCOUNTING,   # lost capacity and repair cost
    ),
}


@dataclass(frozen=True)
class FanoutResult:
    """What happened, per target. Returned so a caller can tell an operator the truth."""

    event_type: str
    event_id: str
    postings: list[SystemOfRecordPosting]

    def by_status(self, status: str) -> list[SystemOfRecordPosting]:
        return [p for p in self.postings if p.status == status]

    @property
    def needs_a_human(self) -> list[SystemOfRecordPosting]:
        return self.by_status(PostingStatus.MANUAL_REQUIRED)

    def summary(self) -> dict[str, Any]:
        counts: dict[str, int] = {}
        for posting in self.postings:
            counts[posting.status] = counts.get(posting.status, 0) + 1
        return {
            "event_type": self.event_type,
            "event_id": self.event_id,
            "targets": len(self.postings),
            "by_status": counts,
            # Named explicitly rather than left for the caller to derive: the whole point is
            # that "it went everywhere" must not be the default reading.
            "fully_posted": all(p.status == PostingStatus.POSTED for p in self.postings),
            "awaiting_a_person": [
                {"target": p.target_system, "instruction": p.instruction}
                for p in self.needs_a_human
            ],
        }


def _describe(event: Any, event_type: str) -> str:
    """One sentence a human can act on, for the manual path.

    This is read aloud or pasted into a message, so it names the thing, the quantity and
    the where — the three questions a stores clerk or a scheduler asks back.
    """
    if event_type == EventType.PART_ISSUE:
        where = f" to {event.work_order_ref}" if event.work_order_ref else ""
        return (
            f"Issue {event.quantity} {event.unit_of_measure} of part {event.part_number}"
            f"{where} — recorded at {event.issued_at:%Y-%m-%d %H:%M} and NOT yet entered "
            f"in this system."
        )
    if event_type == EventType.LABOR_ENTRY:
        who = event.operator_ref or (str(event.user_id) if event.user_id else "operator")
        # `is not None`, NOT truthiness: a shift can legitimately be 0.0 minutes long — a
        # clock-in corrected seconds later — and `if event.duration_minutes` reports that
        # closed entry to a payroll clerk as "an open shift", which is a different and
        # wrong instruction. Found by driving the running app, not by the tests.
        span = (
            f"{event.duration_minutes} min" if event.duration_minutes is not None
            else "an open shift"
        )
        where = f" on {event.work_order_ref}" if event.work_order_ref else ""
        return f"Record {span} of labour for {who}{where} — not yet entered in this system."
    if event_type == EventType.QUALITY_EVENT:
        qty = f" ({event.quantity_affected} affected)" if event.quantity_affected else ""
        return (
            f"Raise a {event.severity} {event.event_type} against "
            f"{event.part_number or 'the job'}{qty}: {event.description} — not yet entered "
            f"in this system."
        )
    if event_type == EventType.DOWNTIME_EVENT:
        # Same falsy-zero trap as the labour entry above: a stop of under a minute rounds
        # to 0.0, and telling a scheduler the machine is "ongoing" down when it is back up
        # sends them to look at a running machine.
        span = (
            f"{event.duration_minutes} min" if event.duration_minutes is not None
            else "ongoing"
        )
        return (
            f"Machine {event.asset_id} is down ({event.downtime_type}, {span}"
            f"{', ' + event.reason_code if event.reason_code else ''}) — not yet entered in "
            f"this system."
        )
    return "A shop-floor event needs entering by hand; see the event record."


async def _integrations_by_capability(
    session: AsyncSession, organization_id: str
) -> dict[str, IntegrationConfiguration]:
    """{target system -> the integration that serves it}, read from configuration.

    NOTHING IS GUESSED. A target absent from this map has no integration, which is what
    produces `manual_required` rather than a silent success.

    The mapping lives in each integration's config under `serves_systems`. An integration
    that does not declare it serves nothing here — deliberately, because assuming an ERP
    handles accounting merely because it is an ERP is how a posting ends up claimed against
    a system that never received it.
    """
    rows = (
        await session.execute(
            select(IntegrationConfiguration).where(
                IntegrationConfiguration.organization_id == organization_id,
                IntegrationConfiguration.is_active.is_(True),
            )
        )
    ).scalars().all()

    serves: dict[str, IntegrationConfiguration] = {}
    for row in rows:
        # The column is `configuration`, not `config` — the first version of this read
        # `row.config`, which does not exist, so every target silently fell through to
        # manual. Caught by the integrated-stack test rather than by review.
        config = row.configuration if isinstance(row.configuration, dict) else {}
        for target in config.get("serves_systems") or []:
            if target in TargetSystem.ALL and target not in serves:
                serves[target] = row
    return serves


async def fan_out(
    session: AsyncSession,
    organization_id: str,
    event: Any,
    event_type: str,
    *,
    targets: Optional[Iterable[str]] = None,
) -> FanoutResult:
    """Create the posting ledger for one floor event.

    Postings start as `pending` where an integration exists and `manual_required` where one
    does not. Nothing is marked `posted` here — that only happens when a far system returns
    an identifier, and this function does not talk to one. Separating "what must happen"
    from "what happened" is what stops the ledger from being written optimistically.
    """
    required = tuple(targets) if targets is not None else ROUTING.get(event_type, ())
    if not required:
        raise ValueError(f"no routing defined for event type {event_type!r}")

    serves = await _integrations_by_capability(session, organization_id)
    instruction = _describe(event, event_type)

    postings: list[SystemOfRecordPosting] = []
    for target in required:
        integration = serves.get(target)
        posting = SystemOfRecordPosting(
            id=str(uuid.uuid4()),
            organization_id=organization_id,
            event_type=event_type,
            event_id=str(event.id),
            target_system=target,
            integration_id=str(integration.id) if integration else None,
            status=PostingStatus.PENDING if integration else PostingStatus.MANUAL_REQUIRED,
            # The instruction is attached to the manual ones only. On an integrated target
            # it would be noise, and worse, it would read as something a person still has
            # to do after the machine already did it.
            instruction=None if integration else instruction,
        )
        session.add(posting)
        postings.append(posting)

    await session.flush()

    logger.info(
        "shop_floor_event_fanned_out",
        event_type=event_type,
        event_id=str(event.id),
        organization_id=organization_id,
        integrated=[p.target_system for p in postings if p.integration_id],
        manual=[p.target_system for p in postings if not p.integration_id],
    )
    return FanoutResult(event_type=event_type, event_id=str(event.id), postings=postings)


async def record_posted(
    session: AsyncSession,
    posting: SystemOfRecordPosting,
    external_ref: str,
) -> SystemOfRecordPosting:
    """Mark a posting as landed. Requires the far system's identifier.

    The database enforces this too (`ck_posted_has_evidence`); the check is here as well so
    a caller gets a clear error rather than an IntegrityError from three layers down.
    """
    if not external_ref:
        raise ValueError(
            "a posting cannot be marked posted without the identifier the target system "
            "returned — that identifier is the only evidence it arrived"
        )
    posting.status = PostingStatus.POSTED
    posting.external_ref = external_ref
    posting.posted_at = utcnow()
    posting.attempts = (posting.attempts or 0) + 1
    posting.last_error = None
    posting.instruction = None
    await session.flush()
    return posting


async def record_failed(
    session: AsyncSession, posting: SystemOfRecordPosting, error: str
) -> SystemOfRecordPosting:
    posting.status = PostingStatus.FAILED
    posting.attempts = (posting.attempts or 0) + 1
    posting.last_error = (error or "")[:2000]
    await session.flush()
    return posting


async def acknowledge_manual(
    session: AsyncSession,
    posting: SystemOfRecordPosting,
    user_id: str,
    external_ref: Optional[str] = None,
) -> SystemOfRecordPosting:
    """A human says they did the analog step.

    THIS IS NOT `posted` UNLESS THEY SAY WHERE. Acknowledging that you told the stores clerk
    is a different fact from the stores system having a record, and collapsing them would
    reintroduce exactly the ambiguity the ledger removes. With a reference — the requisition
    number they wrote down — it becomes `posted` and carries that as its evidence. Without
    one it stays `manual_required` and simply records who acted and when.
    """
    posting.acknowledged_by = user_id
    posting.acknowledged_at = utcnow()
    if external_ref:
        posting.status = PostingStatus.POSTED
        posting.external_ref = external_ref
        posting.posted_at = utcnow()
    await session.flush()
    return posting

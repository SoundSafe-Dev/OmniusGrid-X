"""Drain the posting ledger: try each queued obligation against its ERP (FS-407).

WHY THIS EXISTS. `fan_out` creates a posting as `pending` when an integration claims the
target system, and as `manual_required` when none does. Without a drainer, `pending` is a
DEAD END: nothing ever moves it, so an integrated target can never be confirmed and an
operator watching the ledger sees a queue that never empties, with no way to tell "waiting"
from "abandoned". That is a worse state than having no integration at all, because at least
`manual_required` tells somebody to pick up the phone.

WHAT DRAINING ACTUALLY DOES TODAY, STATED PLAINLY. No connector in this repository has a
verified write path — `ERPConnectorBase` exposed `fetch_data`, `subscribe_to_events` and
`health_check`, and nothing else, for its whole life. So for every real vendor the attempt
ends in `ERPWriteNotSupported`, and this module converts the posting to `manual_required`
with an instruction for a person.

THAT CONVERSION IS THE POINT, not a consolation prize. It turns "queued behind an
integration that will never take it" into "somebody has to enter this, and here is what to
tell them" — which is true, actionable, and visible on the ledger. The alternative designs
are both lies: leaving it pending forever implies a write is coming, and marking it posted
would claim an ERP record that does not exist.

WHEN A CONNECTOR GAINS A REAL WRITE, nothing here changes. It overrides `post_event`,
returns the identifier its ERP hands back, and the posting becomes `posted` with that
reference as evidence — the same path the code below already takes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import IntegrationConfiguration
from app.db.shop_floor_models import PostingStatus, SystemOfRecordPosting
from app.services.erp_connector_base import ERPWriteNotSupported
from app.services.shop_floor_fanout import record_failed, record_posted

logger = structlog.get_logger()

#: A posting that has failed this many times stops being retried and is handed to a person.
#: Not infinite: a queue that retries forever is indistinguishable from one that is stuck,
#: and the operator needs the item to surface somewhere they will act on it.
MAX_ATTEMPTS = 3


@dataclass(frozen=True)
class DrainResult:
    """What the drain did. Counted per outcome, because they mean different things."""

    considered: int
    posted: int
    failed: int
    handed_to_a_person: int
    #: Postings whose integration row has vanished — nothing to try, nobody assigned.
    orphaned: int

    def summary(self) -> dict[str, Any]:
        return {
            "considered": self.considered,
            "posted": self.posted,
            "failed": self.failed,
            "handed_to_a_person": self.handed_to_a_person,
            "orphaned": self.orphaned,
        }


def _instruction_for(posting: SystemOfRecordPosting, reason: str) -> str:
    """What to tell the person now that the machine cannot do it.

    Carries the reason, because "the ERP cannot accept writes" and "the ERP refused this
    one" send a supervisor to two different people.
    """
    return (
        f"Enter this into {posting.target_system} by hand — {reason}. "
        f"Event {posting.event_type} {posting.event_id}."
    )


async def _connector_for(
    session: AsyncSession, posting: SystemOfRecordPosting
) -> Optional[Any]:
    """Build the connector for this posting's integration, or None if there isn't one.

    Import is local: `erp_connector_factory` pulls in every vendor connector, and this module
    is imported by an API router at startup.
    """
    if not posting.integration_id:
        return None
    integration = (
        await session.execute(
            select(IntegrationConfiguration).where(
                IntegrationConfiguration.id == str(posting.integration_id)
            )
        )
    ).scalars().first()
    if integration is None or not integration.is_active:
        return None

    from app.services.erp_connector_factory import ERPConnectorFactory

    return ERPConnectorFactory.create(integration)


async def drain(
    session: AsyncSession,
    organization_id: str,
    *,
    limit: int = 50,
) -> DrainResult:
    """Attempt every pending posting for one organisation.

    Failures are recorded against the posting, never raised: one unreachable ERP must not
    stop the rest of the queue, and the ledger is where an operator reads what happened.
    """
    rows = (
        await session.execute(
            select(SystemOfRecordPosting)
            .where(
                SystemOfRecordPosting.organization_id == organization_id,
                SystemOfRecordPosting.status == PostingStatus.PENDING,
            )
            .order_by(SystemOfRecordPosting.created_at)
            .limit(limit)
        )
    ).scalars().all()

    posted = failed = handed_over = orphaned = 0

    for posting in rows:
        try:
            connector = await _connector_for(session, posting)
        except Exception as exc:  # noqa: BLE001
            # A connector that cannot even be BUILT — an integration row missing `erp_type`,
            # an unknown vendor, a malformed config. This used to escape and 500 the whole
            # request, which broke this module's own contract: one bad integration must not
            # stop the queue. Found by draining a real ledger, not by the tests, because the
            # fixtures all build valid configs.
            logger.warning(
                "posting_drain_connector_unbuildable",
                posting_id=str(posting.id),
                integration_id=str(posting.integration_id),
                error=f"{type(exc).__name__}: {exc}",
            )
            posting.status = PostingStatus.MANUAL_REQUIRED
            posting.instruction = _instruction_for(
                posting,
                f"its integration is not usable ({type(exc).__name__}: {exc})",
            )
            posting.last_error = f"{type(exc).__name__}: {exc}"
            orphaned += 1
            continue

        if connector is None:
            # The integration was deleted or deactivated after the posting was created.
            # Leaving it pending would queue it behind something that no longer exists.
            posting.status = PostingStatus.MANUAL_REQUIRED
            posting.instruction = _instruction_for(
                posting, "the integration it was queued for is gone or switched off"
            )
            orphaned += 1
            continue

        try:
            external_ref = await connector.post_event(
                posting.event_type,
                {
                    "event_type": posting.event_type,
                    "event_id": str(posting.event_id),
                    "target_system": posting.target_system,
                    "organization_id": organization_id,
                },
            )
            if not external_ref:
                # A connector that writes but returns nothing has given us no evidence.
                # Treated as a failure rather than a success, because `posted` without a
                # reference is exactly the unverifiable claim the ledger exists to prevent.
                raise ERPWriteNotSupported(
                    "the connector returned no identifier, so there is nothing to verify "
                    "the write against"
                )
            await record_posted(session, posting, str(external_ref))
            posted += 1

        except ERPWriteNotSupported as exc:
            # THE EXPECTED PATH TODAY. Not an error: the connector correctly declined rather
            # than inventing a reference.
            posting.status = PostingStatus.MANUAL_REQUIRED
            posting.instruction = _instruction_for(posting, str(exc))
            posting.attempts = (posting.attempts or 0) + 1
            handed_over += 1

        except Exception as exc:  # noqa: BLE001 - one bad ERP must not stop the queue
            await record_failed(session, posting, f"{type(exc).__name__}: {exc}")
            if (posting.attempts or 0) >= MAX_ATTEMPTS:
                # Out of retries. Hand it to a person instead of leaving it to cycle.
                posting.status = PostingStatus.MANUAL_REQUIRED
                posting.instruction = _instruction_for(
                    posting,
                    f"{MAX_ATTEMPTS} attempts failed, last error: {posting.last_error}",
                )
                handed_over += 1
            else:
                failed += 1
        finally:
            close = getattr(connector, "close", None) if connector is not None else None
            if close is not None:
                try:
                    await close()
                except Exception:  # noqa: BLE001 - closing must not mask the outcome
                    pass

    await session.flush()
    result = DrainResult(
        considered=len(rows),
        posted=posted,
        failed=failed,
        handed_to_a_person=handed_over,
        orphaned=orphaned,
    )
    logger.info("posting_ledger_drained", organization_id=organization_id, **result.summary())
    return result

"""Drain the posting ledger on a timer, per organisation (FS-427).

WHY THIS EXISTS. `POST /shop-floor/postings/drain` was the only thing that moved a `pending`
posting, and it is a button on one page. So an obligation raised by a part issue at 03:00
sat untouched until somebody opened the Shop Floor screen and pressed it — which makes the
ledger a thing you have to remember rather than a thing that runs. A queue nobody drains is
the state the drainer was written to remove; leaving the drainer manual only moved the
problem from "nothing tries" to "nothing tries unless asked".

WHAT IT DOES NOT DO. It does not retry forever and it does not decide anything the drainer
does not already decide: `drain()` owns the outcomes, this owns the schedule. A posting that
cannot be written ends up `manual_required` with an instruction — the same result the button
produces, arriving without anyone asking.

TENANCY. One session per organisation with `app.current_org_id` set, following
`rollout_orchestrator`. `system_of_record_postings` has FORCE RLS, so a session without the
GUC sees nothing and this would report a clean drain over an empty read — the failure this
codebase has hit repeatedly, where absence arrives as a good result.

DISABLED BY DEFAULT IN TESTS via the same settings gate the other schedulers use. A
background task that starts during a test suite writes to whatever database the fixture
happens to hold.
"""

from __future__ import annotations

import asyncio
from typing import Any, Optional

import structlog
from sqlalchemy import select, text

from app.core.config import settings
from app.db.database import AsyncSessionLocal
from app.db.models import Organization
from app.services.posting_drainer import drain

logger = structlog.get_logger()


class PostingDrainScheduler:
    """Periodically attempt every queued posting, for every organisation."""

    def __init__(self) -> None:
        self._task: Optional[asyncio.Task] = None
        self._running = False

    async def start(self) -> None:
        if not settings.POSTING_DRAIN_ENABLED or self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._run())
        logger.info(
            "posting_drain_scheduler_started",
            interval_seconds=settings.POSTING_DRAIN_INTERVAL_SECONDS,
        )

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("posting_drain_scheduler_stopped")

    async def _run(self) -> None:
        while self._running:
            try:
                await self.drain_all_organizations()
            except Exception as exc:  # noqa: BLE001 - one bad pass must not end the loop
                logger.error("posting_drain_iteration_failed", error=str(exc))
            await asyncio.sleep(settings.POSTING_DRAIN_INTERVAL_SECONDS)

    async def _set_org(self, session: Any, org_id: Any) -> None:
        await session.execute(
            text("SELECT set_config('app.current_org_id', :org_id, true)"),
            {"org_id": str(org_id)},
        )

    async def drain_all_organizations(self) -> dict[str, int]:
        """One pass. Returns the totals, so a caller can assert on them.

        Per-organisation failures are logged and skipped rather than raised: one tenant with
        an unreachable ERP must not stop every other tenant's ledger from draining.
        """
        async with AsyncSessionLocal() as session:
            org_ids = (await session.execute(select(Organization.id))).scalars().all()

        totals = {"considered": 0, "posted": 0, "failed": 0,
                  "handed_to_a_person": 0, "orphaned": 0, "organizations": 0}
        for org_id in org_ids:
            try:
                async with AsyncSessionLocal() as session:
                    await self._set_org(session, org_id)
                    result = await drain(
                        session, str(org_id), limit=settings.POSTING_DRAIN_BATCH_SIZE
                    )
                    await session.commit()
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "posting_drain_failed_for_organization",
                    organization_id=str(org_id), error=str(exc),
                )
                continue
            totals["organizations"] += 1
            for key, value in result.summary().items():
                totals[key] += value

        # Logged only when it did something. A scheduler that reports every idle pass
        # trains readers to skip its lines, and the interesting event here is movement.
        if totals["considered"]:
            logger.info("posting_drain_pass_complete", **totals)
        return totals


posting_drain_scheduler = PostingDrainScheduler()

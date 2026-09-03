"""Periodic DB-backed refresh of the fleet liveness gauges (FS-704).

WHY A SWEEP EXISTS AT ALL. The heartbeat ingest path writes `edge_agent_up` and
`edge_agent_last_heartbeat` when a heartbeat ARRIVES — which means it can only ever record
arrivals. Two gaps follow, both found in this arc:

  * FS-695: nothing wrote `edge_agent_up = 0`; an agent that stopped heartbeating froze at
    1. The alert moved to the last-heartbeat timestamp's age, which self-advances.
  * The recorded remainder: gauges live in backend memory, so after a backend restart an
    ALREADY-DEAD agent has no series at all — `time() - <absent>` evaluates to nothing,
    and the agent that has been broken since before the restart is precisely the one that
    cannot alert.

This sweep closes the remainder: every interval it re-derives both gauges for every agent
the DATABASE knows, from `edge_agent_status.last_seen` — which survives restarts. It also
finally makes `edge_agent_up = 0` a value production writes, for stale and offline agents.

TENANCY IS THE TRAP HERE. `edge_agent_status` is FORCE row-level-security (migration 057),
so an untenanted `AsyncSessionLocal` reads **zero rows and no error** — the sweep would
report a healthy empty fleet forever, which is rule 165's worst case (a sweep that
examined nothing printing the same thing as a fleet with nothing wrong). Orgs are
enumerated first (the `organizations` table is readable untenanted) and the GUC is set per
org, the same shape `posting_drain_scheduler` uses for the same reason.

Per FS-693's own rule, a new background loop arrives WITH its failure accounting: the
consecutive-failure counter below is read by `_check_fleet_sweep` in `api/health.py`, and
the service joins `EXPECTED_STARTED` — it is never on the unwatched register at all.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Optional

import structlog
from sqlalchemy import select, text

from app.core.config import settings
from app.db.database import AsyncSessionLocal
from app.db.edge_fleet_models import EdgeAgentStatus
from app.db.models import Asset, Organization
from app.services.edge_fleet import (
    agent_liveness,
    edge_agent_last_heartbeat,
    edge_agent_up,
    opsgrid_asset_last_seen_timestamp_seconds,
)

logger = structlog.get_logger()


class EdgeFleetSweep:
    """Re-derives fleet liveness gauges from the database on a timer."""

    def __init__(self) -> None:
        self._task: Optional[asyncio.Task] = None
        self._running = False
        #: Consecutive failed sweeps (FS-693's pattern, present from birth). The loop
        #: swallows to survive; whether it is working is a question only this can answer.
        self._consecutive_failures = 0

    async def start(self) -> None:
        if not settings.EDGE_FLEET_SWEEP_ENABLED or self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._run())
        logger.info(
            "edge_fleet_sweep_started",
            interval_seconds=settings.EDGE_FLEET_SWEEP_INTERVAL_SECONDS,
        )

    async def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("edge_fleet_sweep_stopped")

    async def _run(self) -> None:
        while self._running:
            try:
                await self.sweep_once()
                self._consecutive_failures = 0
            except Exception as exc:  # noqa: BLE001 - one bad pass must not end the loop
                self._consecutive_failures += 1
                logger.error("edge_fleet_sweep_failed", error=str(exc))
            await asyncio.sleep(settings.EDGE_FLEET_SWEEP_INTERVAL_SECONDS)

    async def sweep_once(self) -> int:
        """One pass over every org's agents. Returns how many agents were refreshed —
        the caller and the tests assert on the denominator, not on silence."""
        async with AsyncSessionLocal() as session:
            org_ids = (await session.execute(select(Organization.id))).scalars().all()

        refreshed = 0
        now = datetime.now(timezone.utc)
        for org_id in org_ids:
            # One session per org, not two. Each org used to open a fresh
            # AsyncSessionLocal for the agent query and a second for the asset
            # query below — a fresh pool connection for the same GUC twice —
            # which is direct pressure on the pool ceiling FS-839 sized against
            # maxReplicas. Both reads share one org-scoped session instead.
            async with AsyncSessionLocal() as session:
                await session.execute(
                    text("SELECT set_config('app.current_org_id', :org_id, true)"),
                    {"org_id": str(org_id)},
                )
                rows = (await session.execute(select(EdgeAgentStatus))).scalars().all()

                # FS-774. The same question asked of ASSETS rather than agents, and for
                # the alert that had no series at all. One agent serves many assets, so
                # an online agent whose PLC stopped answering is invisible to every
                # `edge_agent_*` gauge — which is the failure an operator most needs told.
                #
                # Inactive assets are skipped deliberately: a decommissioned machine has
                # a last_seen that only ages, and publishing it would page forever.
                assets = (
                    await session.execute(
                        select(Asset).where(
                            Asset.is_active.is_(True), Asset.last_seen.isnot(None)
                        )
                    )
                ).scalars().all()
            for row in rows:
                live = agent_liveness(row.last_seen, now)
                edge_agent_up.labels(agent_id=row.agent_id).set(1 if live == "online" else 0)
                if row.last_seen is not None:
                    last_seen = (
                        row.last_seen
                        if row.last_seen.tzinfo
                        else row.last_seen.replace(tzinfo=timezone.utc)
                    )
                    edge_agent_last_heartbeat.labels(agent_id=row.agent_id).set(
                        last_seen.timestamp()
                    )
                refreshed += 1

            for asset in assets:
                seen = (
                    asset.last_seen
                    if asset.last_seen.tzinfo
                    else asset.last_seen.replace(tzinfo=timezone.utc)
                )
                opsgrid_asset_last_seen_timestamp_seconds.labels(
                    asset_id=str(asset.id), asset_name=asset.name
                ).set(seen.timestamp())
        return refreshed


edge_fleet_sweep = EdgeFleetSweep()

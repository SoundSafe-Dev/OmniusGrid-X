"""The fleet sweep re-derives liveness gauges from the database (FS-704).

THE GAP IT CLOSES, left recorded in FS-695's alert comment: gauges live in backend memory,
so after a backend restart an already-dead agent has no `edge_agent_last_heartbeat` series
at all — `time() - <absent>` evaluates to nothing, and the agent broken since before the
restart is precisely the one that cannot fire `EdgeAgentOffline`. The database's
`edge_agent_status.last_seen` survives restarts; the sweep republishes both gauges from it
every interval. It also makes `edge_agent_up = 0` a value production finally writes —
FS-695 documented that nothing did.

THE TRAP THESE TESTS PIN: `edge_agent_status` is FORCE row-level-security (migration 057),
so an untenanted session reads zero rows and no error. A sweep written without the per-org
GUC would pass a survives-and-counts test perfectly while refreshing nothing, forever —
rule 165's worst case. Hence every assertion here goes through the DENOMINATOR
(`sweep_once` returns how many agents it refreshed) and real seeded rows.

FIXTURE NOTE: the DB-touching tests request `app` even though they never issue an HTTP
request — that fixture is where conftest sweeps `AsyncSessionLocal` across every app
module onto the ephemeral tenant-scoped engine. Without it the sweep connects to the
placeholder URL and fails on `role "placeholder"`, which at least fails loudly; the
subtler point is that the tenant engine is NOSUPERUSER NOBYPASSRLS (FS-307), so RLS is
genuinely enforced here and the per-org GUC is genuinely what admits the rows.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
import pytest_asyncio

from app.services.edge_fleet import edge_agent_last_heartbeat, edge_agent_up
from app.services.edge_fleet_sweep import EdgeFleetSweep

pytestmark = pytest.mark.asyncio


def _gauge_value(gauge, agent_id: str):
    for metric in gauge.collect():
        for sample in metric.samples:
            if sample.labels.get("agent_id") == agent_id:
                return sample.value
    return None


@pytest_asyncio.fixture
async def two_agents(admin_sync_url, seeded_orgs):
    """One agent that heartbeated seconds ago, one that died forty minutes ago."""
    import psycopg2

    conn = psycopg2.connect(admin_sync_url)
    conn.autocommit = True
    now = datetime.now(timezone.utc)
    ids = {"live": f"agent-live-{uuid4().hex[:8]}", "dead": f"agent-dead-{uuid4().hex[:8]}"}
    org = str(seeded_orgs["org_a_id"])
    with conn.cursor() as cur:
        for agent_id, last_seen in (
            (ids["live"], now - timedelta(seconds=5)),
            (ids["dead"], now - timedelta(minutes=40)),
        ):
            cur.execute(
                "INSERT INTO edge_agent_status (agent_id, organization_id, last_seen) "
                "VALUES (%s, %s, %s)",
                (agent_id, org, last_seen),
            )
    yield ids
    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM edge_agent_status WHERE agent_id IN (%s, %s)",
            (ids["live"], ids["dead"]),
        )
    conn.close()


class TestTheSweepReadsThroughRls:
    async def test_the_denominator_is_not_zero(self, app, two_agents):
        """THE RULE-165 CONTROL, first. FORCE RLS on an untenanted session returns zero
        rows and no error — a sweep missing the per-org GUC refreshes nothing and looks
        healthy. The count is the difference between 'swept nothing' and 'nothing to
        sweep', and everything else in this file is meaningless if this fails."""
        refreshed = await EdgeFleetSweep().sweep_once()
        assert refreshed >= 2, (
            f"the sweep refreshed {refreshed} agents while at least two exist — the "
            f"tenant GUC is not being set and RLS is silently filtering every row"
        )


class TestADeadAgentAlertsAfterARestart:
    async def test_the_dead_agents_timestamp_series_is_rematerialized(self, app, two_agents):
        """THE PROPERTY. Simulate the restart by removing the label child (a fresh
        process has none), then sweep: the series must come back from the DATABASE, with
        the old last_seen — an age EdgeAgentOffline's `> 300` immediately exceeds."""
        try:
            edge_agent_last_heartbeat.remove(two_agents["dead"])
        except KeyError:
            pass

        await EdgeFleetSweep().sweep_once()

        stamp = _gauge_value(edge_agent_last_heartbeat, two_agents["dead"])
        assert stamp is not None, (
            "the dead agent has no last-heartbeat series after a sweep — after a backend "
            "restart it would stay unalertable until it heartbeats, which it never will"
        )
        age = datetime.now(timezone.utc).timestamp() - stamp
        assert age > 300, f"the re-derived age is {age:.0f}s; the seeded agent died 40m ago"

    async def test_the_dead_agent_is_finally_written_as_down(self, app, two_agents):
        """FS-695 recorded that nothing ever wrote edge_agent_up = 0. The sweep is the
        production writer of 0."""
        await EdgeFleetSweep().sweep_once()
        assert _gauge_value(edge_agent_up, two_agents["dead"]) == 0

    async def test_the_live_agent_is_written_as_up(self, app, two_agents):
        """NEGATIVE CONTROL: a sweep that wrote 0 for everyone would page the whole
        fleet and be silenced within the hour."""
        await EdgeFleetSweep().sweep_once()
        assert _gauge_value(edge_agent_up, two_agents["live"]) == 1
        stamp = _gauge_value(edge_agent_last_heartbeat, two_agents["live"])
        assert stamp is not None
        assert datetime.now(timezone.utc).timestamp() - stamp < 300


class TestTheLoopAccountsForItself:
    async def test_a_failing_sweep_increments_the_counter(self):
        sweep = EdgeFleetSweep()
        sweep._running = True
        calls = {"n": 0}

        async def _boom():
            calls["n"] += 1
            if calls["n"] >= 2:
                sweep._running = False
            raise RuntimeError("db unreachable")

        sweep.sweep_once = _boom
        with pytest.MonkeyPatch.context() as mp:
            from app.core.config import settings

            mp.setattr(settings, "EDGE_FLEET_SWEEP_INTERVAL_SECONDS", 0)
            await sweep._run()
        assert sweep._consecutive_failures >= 2

    async def test_a_successful_sweep_resets_the_counter(self):
        sweep = EdgeFleetSweep()
        sweep._running = True
        sweep._consecutive_failures = 7

        async def _fine():
            sweep._running = False
            return 0

        sweep.sweep_once = _fine
        with pytest.MonkeyPatch.context() as mp:
            from app.core.config import settings

            mp.setattr(settings, "EDGE_FLEET_SWEEP_INTERVAL_SECONDS", 0)
            await sweep._run()
        assert sweep._consecutive_failures == 0

    async def test_the_health_check_reads_it(self, monkeypatch):
        from app.api import health as health_module
        from app.services import edge_fleet_sweep as sweep_module

        monkeypatch.setattr(sweep_module.edge_fleet_sweep, "_running", True)
        monkeypatch.setattr(sweep_module.edge_fleet_sweep, "_consecutive_failures", 3)
        status, _ = health_module._check_fleet_sweep()
        assert status.startswith("error")

    async def test_the_check_reaches_the_detailed_report(self, monkeypatch):
        from app.api import health as health_module

        class _Boom:
            async def execute(self, *_a, **_k):
                raise RuntimeError("down")

        checks, details = await health_module._run_extended_checks(_Boom())
        assert "edge_fleet_sweep" in checks
        assert "edge_fleet_sweep" in details

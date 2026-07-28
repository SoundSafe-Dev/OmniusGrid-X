"""An edge-agent heartbeat must actually update the assets it names.

THE DEFECT. `_process_agent_heartbeat` runs `update(Asset)` to record fleet-version
fields, and `assets` is FORCE ROW LEVEL SECURITY. `_process_message` binds
`app.current_org_id` for the telemetry/state/alarm branch — but the agent-status branch
returns before reaching that code, so this path ran with **no tenant GUC at all**.

RLS FILTERS A WRITE SILENTLY rather than raising: the UPDATE simply matches no rows. So
every heartbeat updated zero assets, `result.rowcount` was 0, and the worker logged
`updated_assets=0` — an accurate log of a total failure, which nobody reads because
nothing looks wrong. Verified against a real database before the fix: `agent_version`
stayed NULL after a heartbeat naming the asset directly.

HOW IT WAS FOUND, which is the part worth keeping. A guard written to assert something
else — that the ingestion message path commits exactly once, so a transaction-local GUC
cannot be dropped mid-message — failed on a count of 2. The second commit turned out to
be a different branch, so the assertion was too crude; but reading that branch to correct
the test is what exposed the missing binding. The wrong assertion pointed at the right
place.

The binding now lives inside the heartbeat handler, next to the `organization_id` it is
derived from, rather than in the caller — so it holds for any future caller, and cannot
be lost by another early return.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def asset(admin_sync_url, seeded_orgs):
    import psycopg2

    asset_id, workcell_id, type_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    conn = psycopg2.connect(admin_sync_url)
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO workcells (id, organization_id, name) VALUES (%s, %s, 'HB WC')",
            (str(workcell_id), str(seeded_orgs["org_a_id"])))
        cur.execute(
            "INSERT INTO asset_types (id, name, category) VALUES (%s, 'HB', 'test')",
            (str(type_id),))
        cur.execute(
            "INSERT INTO assets (id, organization_id, workcell_id, asset_type_id, name) "
            "VALUES (%s, %s, %s, %s, 'HB Asset')",
            (str(asset_id), str(seeded_orgs["org_a_id"]), str(workcell_id), str(type_id)))
    yield asset_id, seeded_orgs["org_a_id"], seeded_orgs["org_b_id"]
    with conn.cursor() as cur:
        cur.execute("DELETE FROM assets WHERE id = %s", (str(asset_id),))
        cur.execute("DELETE FROM workcells WHERE id = %s", (str(workcell_id),))
        cur.execute("DELETE FROM asset_types WHERE id = %s", (str(type_id),))
    conn.close()


async def _heartbeat(tenant_async_url, org_id, asset_ids, version="1.2.3"):
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from app.workers.ingestion import IngestionWorker

    engine = create_async_engine(tenant_async_url, future=True)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    worker = IngestionWorker.__new__(IngestionWorker)
    try:
        async with maker() as session:
            await worker._process_agent_heartbeat(session, {
                "message_type": "agent_heartbeat",
                "organization_id": str(org_id),
                "asset_ids": [str(a) for a in asset_ids],
                "agent_version": version,
            })
            await session.commit()
    finally:
        await engine.dispose()


def _agent_version(admin_sync_url, asset_id):
    import psycopg2

    conn = psycopg2.connect(admin_sync_url)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT agent_version FROM assets WHERE id = %s", (str(asset_id),))
            return cur.fetchone()[0]
    finally:
        conn.close()


class TestTheHeartbeatWrites:
    async def test_the_agent_version_is_recorded(self, asset, tenant_async_url, admin_sync_url):
        """THE ASSERTION THIS FILE EXISTS FOR. This stayed NULL — the UPDATE matched no
        rows because RLS had no tenant to match against, and said nothing about it."""
        asset_id, org_a, _org_b = asset
        assert _agent_version(admin_sync_url, asset_id) is None, "fixture precondition"

        await _heartbeat(tenant_async_url, org_a, [asset_id], version="9.9.9")

        assert _agent_version(admin_sync_url, asset_id) == "9.9.9", (
            "the heartbeat updated nothing — the UPDATE is still running without a "
            "tenant GUC, and RLS is filtering it silently"
        )


class TestTheHeartbeatStaysInsideItsTenant:
    async def test_it_cannot_touch_another_orgs_asset(
        self, asset, tenant_async_url, admin_sync_url
    ):
        """The binding must scope the write, not merely enable it. A heartbeat claiming
        org B must not reach org A's asset even when it names its id."""
        asset_id, _org_a, org_b = asset

        await _heartbeat(tenant_async_url, org_b, [asset_id], version="8.8.8")

        assert _agent_version(admin_sync_url, asset_id) != "8.8.8", (
            "a heartbeat for another organization updated this asset"
        )

    async def test_the_binding_is_transaction_local(self):
        """It must not ride the connection back into the pool, where the next task
        would inherit a stale tenant."""
        import pathlib
        import re

        source = pathlib.Path(
            __file__
        ).resolve().parents[1].joinpath("app/workers/ingestion.py").read_text()
        start = source.index("async def _process_agent_heartbeat")
        end = source.index("async def ", start + 10)
        body = source[start:end]
        assert re.search(r"set_config\([^)]*current_org_id[^)]*true\s*\)", body), (
            "the heartbeat's tenant binding is missing or is not transaction-local"
        )

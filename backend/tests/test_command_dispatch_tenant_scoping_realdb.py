"""Submitting a command, reading its history, and the emergency stop must work.

THE DEFECT. `assets` is FORCE ROW LEVEL SECURITY. Three handlers in `commands.py`
looked the asset up through a session that sets no `app.current_org_id`:

    submit_command      async with AsyncSessionLocal() as session:   -> asset is None
    emergency_stop      async with AsyncSessionLocal() as session:   -> asset is None
    get_asset_commands  db: AsyncSession = Depends(get_db)           -> asset is None

Each then does `if not asset: raise HTTPException(404, "Asset not found")`. So all
three answered **404 for every asset, including the caller's own** — verified against a
real database before the fix. Command submission was impossible, command history was
empty, and the admin-gated **emergency stop was unreachable**.

The org check immediately after each lookup —
`asset.organization_id != current_user.organization_id` — is correct and never ran,
because there was never an asset to check.

WHY THIS SHAPE IS EASY TO MISS. Two of the three do not use a FastAPI dependency at
all; they open `AsyncSessionLocal()` inline, so a guard that inspects `Depends(get_db)`
sees nothing wrong. `tests/test_tenant_session_guard.py` counted one site in this file
when there were three. They now use `tenant_session(org_id)` — the context-manager form
of the same tenant binding, extracted for exactly this case.

A 404 is also the least suspicious possible symptom: it reads as "that asset does not
exist", which is a sentence nobody investigates.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def asset(admin_sync_url, seeded_orgs):
    """One asset in org A, with the workcell and type its NOT NULL columns need."""
    import psycopg2

    asset_id, workcell_id, type_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    conn = psycopg2.connect(admin_sync_url)
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO workcells (id, organization_id, name) VALUES (%s, %s, 'CMD WC')",
            (str(workcell_id), str(seeded_orgs["org_a_id"])),
        )
        cur.execute(
            "INSERT INTO asset_types (id, name, category) VALUES (%s, 'CMD Type', 'test')",
            (str(type_id),),
        )
        cur.execute(
            "INSERT INTO assets (id, organization_id, workcell_id, asset_type_id, name) "
            "VALUES (%s, %s, %s, %s, 'CMD Asset')",
            (str(asset_id), str(seeded_orgs["org_a_id"]), str(workcell_id), str(type_id)),
        )
    yield asset_id
    with conn.cursor() as cur:
        cur.execute("DELETE FROM commands WHERE asset_id = %s", (str(asset_id),))
        cur.execute("DELETE FROM assets WHERE id = %s", (str(asset_id),))
        cur.execute("DELETE FROM workcells WHERE id = %s", (str(workcell_id),))
        cur.execute("DELETE FROM asset_types WHERE id = %s", (str(type_id),))
    conn.close()


class TestTheEndpointsAreReachableAtAll:
    """All three answered 404 for the caller's own asset."""

    async def test_command_history_is_not_404(self, client_a, asset):
        response = await client_a.get(f"/api/v1/commands/asset/{asset}")
        assert response.status_code == 200, (
            f"command history for the caller's OWN asset -> {response.status_code}: "
            f"{response.text[:200]}"
        )

    async def test_a_command_can_be_submitted(self, client_a, asset):
        """THE ASSERTION THIS FILE EXISTS FOR: submission was impossible."""
        response = await client_a.post(
            "/api/v1/commands/submit",
            json={
                "asset_id": str(asset),
                "action_id": "set_speed",
                "parameters": {"speed_percent": 50},
            },
        )
        assert response.status_code == 200, (
            f"submitting to the caller's own asset -> {response.status_code}: "
            f"{response.text[:200]}"
        )

    async def test_the_submitted_command_appears_in_history(self, client_a, asset):
        """A 200 from submit proves the asset was found, not that anything was stored."""
        await client_a.post(
            "/api/v1/commands/submit",
            json={"asset_id": str(asset), "action_id": "pause_job", "parameters": {}},
        )
        response = await client_a.get(f"/api/v1/commands/asset/{asset}")
        assert response.status_code == 200, response.text
        assert response.json(), "the command was accepted but the history is empty"


class TestAnotherOrgsAssetIsStillRefused:
    """The 404 was right for the wrong reason. It must stay right for the right one."""

    @pytest_asyncio.fixture
    async def foreign_asset(self, admin_sync_url, seeded_orgs):
        import psycopg2

        asset_id, workcell_id, type_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        conn = psycopg2.connect(admin_sync_url)
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO workcells (id, organization_id, name) VALUES (%s, %s, 'B WC')",
                (str(workcell_id), str(seeded_orgs["org_b_id"])),
            )
            cur.execute(
                "INSERT INTO asset_types (id, name, category) VALUES (%s, 'B Type', 'test')",
                (str(type_id),),
            )
            cur.execute(
                "INSERT INTO assets (id, organization_id, workcell_id, asset_type_id, name) "
                "VALUES (%s, %s, %s, %s, 'B Asset')",
                (str(asset_id), str(seeded_orgs["org_b_id"]), str(workcell_id), str(type_id)),
            )
        yield asset_id
        with conn.cursor() as cur:
            cur.execute("DELETE FROM assets WHERE id = %s", (str(asset_id),))
            cur.execute("DELETE FROM workcells WHERE id = %s", (str(workcell_id),))
            cur.execute("DELETE FROM asset_types WHERE id = %s", (str(type_id),))
        conn.close()

    async def test_history_for_another_orgs_asset_is_404(self, client_a, foreign_asset):
        response = await client_a.get(f"/api/v1/commands/asset/{foreign_asset}")
        assert response.status_code == 404

    async def test_submitting_to_another_orgs_asset_is_refused(self, client_a, foreign_asset):
        """The most consequential direction: a command must never reach another
        tenant's machine."""
        response = await client_a.post(
            "/api/v1/commands/submit",
            json={
                "asset_id": str(foreign_asset),
                "action_id": "set_speed",
                "parameters": {"speed_percent": 100},
            },
        )
        assert response.status_code in (403, 404), (
            f"a command aimed at another organization's asset was accepted "
            f"({response.status_code})"
        )

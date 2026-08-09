"""Putting an asset into maintenance must actually put it into maintenance.

WHAT WAS BROKEN, END TO END. `POST /admin/assets/{id}/maintenance` writes
`assets.maintenance_mode`, and `TacticalEngine._is_maintenance_mode` reads it to decide
whether a control command may be dispatched. **The column did not exist in this schema.**

  * The endpoint raised `UndefinedColumnError` and returned 500 on every call — while
    `assetsApi.setMaintenanceMode` called it in earnest from the frontend.
  * The reader caught the error and failed SAFE, returning `True` — "in maintenance" — so
    every asset looked suppressed. Its own comment anticipated the gap ("the query can
    also error on deployments where assets.maintenance_mode doesn't exist"), which means
    the read side was written defensively against a schema nobody finished.

Failing safe is what made this survivable and therefore invisible. Nothing in the product
could put a machine into maintenance, and the message returned to whoever tried said
"Game-theoretic engine commands are blocked."

TWO MORE DEFECTS IN THE SAME HANDLER, both of which would have outlived the migration.
It updated by `id` alone, so it was not scoped to the caller's organisation; and `assets`
is FORCE ROW LEVEL SECURITY while the handler runs on `get_db`, which sets no
`app.current_org_id`. **Under RLS an INSERT is rejected loudly and an UPDATE is FILTERED**
— it succeeds having matched nothing — so even with the column present the write could
touch zero rows and still return 200. The rowcount is now checked, which is the only
thing that distinguishes "done" from "matched nothing" for an UPDATE.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
import pytest_asyncio

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def assets(admin_sync_url, seeded_orgs):
    """One asset in each organisation."""
    import psycopg2

    conn = psycopg2.connect(admin_sync_url)
    conn.autocommit = True
    type_id = uuid4()
    a_id, b_id = uuid4(), uuid4()
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO asset_types (id, name, category) VALUES (%s, %s, 'test')",
            (str(type_id), f"MM-{type_id.hex[:8]}"),
        )
        for asset_id, org, workcell in (
            (a_id, seeded_orgs["org_a_id"], seeded_orgs["workcell_a_id"]),
            (b_id, seeded_orgs["org_b_id"], seeded_orgs["workcell_b_id"]),
        ):
            cur.execute(
                "INSERT INTO assets (id, organization_id, workcell_id, asset_type_id, "
                "name, is_active) VALUES (%s, %s, %s, %s, 'MM Asset', true)",
                (str(asset_id), str(org), str(workcell), str(type_id)),
            )

    def mode(asset_id) -> bool:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT maintenance_mode FROM assets WHERE id = %s", (str(asset_id),)
            )
            return cur.fetchone()[0]

    yield {"a": a_id, "b": b_id, "mode": mode}

    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM assets WHERE id = ANY(%s::uuid[])", ([str(a_id), str(b_id)],)
        )
        cur.execute("DELETE FROM asset_types WHERE id = %s", (str(type_id),))
    conn.close()


class TestTheColumnExists:
    def test_the_schema_has_maintenance_mode(self, admin_sync_url):
        """Pinned separately from the behaviour: the endpoint, the tactical engine and
        the ORM all reference this column, and it was absent from the schema for the
        whole of that time."""
        import psycopg2

        conn = psycopg2.connect(admin_sync_url)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT is_nullable, column_default FROM information_schema.columns "
                    "WHERE table_name = 'assets' AND column_name = 'maintenance_mode'"
                )
                row = cur.fetchone()
            assert row is not None, "assets.maintenance_mode is missing again"
            is_nullable, default = row
            assert is_nullable == "NO", (
                "a nullable flag reintroduces the ambiguity: NULL coerces to 'not in "
                "maintenance' through bool(row[0]) and reads as a decision nobody made"
            )
            assert default is not None and "false" in default.lower()
        finally:
            conn.close()


class TestTheWriteLands:
    async def test_enabling_maintenance_sets_the_flag(self, client_a, assets):
        """THE ASSERTION THIS FILE EXISTS FOR. This returned 500 for the entire life of
        the feature."""
        response = await client_a.post(
            f"/admin/assets/{assets['a']}/maintenance", params={"enabled": True}
        )
        assert response.status_code == 200, response.text
        assert assets["mode"](assets["a"]) is True, (
            "the endpoint reported success and the asset is not in maintenance"
        )

    async def test_disabling_clears_it_again(self, client_a, assets):
        """The negative control: a handler that hardcoded True would satisfy the test
        above and make the override impossible to lift."""
        await client_a.post(
            f"/admin/assets/{assets['a']}/maintenance", params={"enabled": True}
        )
        response = await client_a.post(
            f"/admin/assets/{assets['a']}/maintenance", params={"enabled": False}
        )
        assert response.status_code == 200, response.text
        assert assets["mode"](assets["a"]) is False

    async def test_the_message_matches_what_happened(self, client_a, assets):
        body = (
            await client_a.post(
                f"/admin/assets/{assets['a']}/maintenance", params={"enabled": True}
            )
        ).json()
        assert body["maintenance_mode"] == "enabled"
        assert "blocked" in body["message"]


class TestAnotherTenantsAssetIsUntouched:
    async def test_it_is_refused(self, client_a, assets):
        response = await client_a.post(
            f"/admin/assets/{assets['b']}/maintenance", params={"enabled": True}
        )
        assert response.status_code == 404, (
            f"org A put org B's asset into maintenance (got {response.status_code})"
        )

    async def test_the_flag_did_not_move(self, client_a, assets):
        """A 404 returned after the write would be worse than no check. This is the
        assertion that separates 'refused' from 'refused afterwards'."""
        await client_a.post(
            f"/admin/assets/{assets['b']}/maintenance", params={"enabled": True}
        )
        assert assets["mode"](assets["b"]) is False

    async def test_a_missing_asset_is_a_404_not_a_success(self, client_a, assets):
        """The rowcount check has to answer this too — an UPDATE matching nothing is
        indistinguishable from one matching a row, unless somebody looks."""
        response = await client_a.post(
            f"/admin/assets/{uuid4()}/maintenance", params={"enabled": True}
        )
        assert response.status_code == 404


class TestTheEngineReadsWhatWasWritten:
    """The write is only half of it.

    `TacticalEngine._is_maintenance_mode` is what actually suppresses a command, and it
    ran `bool(row and row[0])` on a session with no tenant GUC. `assets` is FORCE RLS and
    the app connects as a non-owner, so the row is INVISIBLE and that expression returned
    False — *not in maintenance*. The missing column hid it: the query raised, the except
    branch returned True, and everything looked suppressed. Adding the column alone would
    have turned suppress-everything into suppress-nothing, which is worse than the bug it
    replaced, so the read is fixed in the same change as the write.
    """

    async def test_the_engine_sees_the_flag_it_was_given(
        self, app, client_a, assets, seeded_orgs
    ):
        from app.services.tactical_engine import tactical_engine

        await client_a.post(
            f"/admin/assets/{assets['a']}/maintenance", params={"enabled": True}
        )
        assert await tactical_engine._is_maintenance_mode(
            str(assets["a"]), str(seeded_orgs["org_a_id"])
        ) is True

    async def test_an_asset_not_in_maintenance_is_not_suppressed(
        self, app, assets, seeded_orgs
    ):
        """The half that could never have passed while the column was missing — the
        except branch returned True for EVERY asset, so no command would ever have been
        dispatched and no one would have noticed the write was broken."""
        from app.services.tactical_engine import tactical_engine

        assert await tactical_engine._is_maintenance_mode(
            str(assets["a"]), str(seeded_orgs["org_a_id"])
        ) is False

    async def test_an_invisible_asset_suppresses_rather_than_clears(self, app, assets):
        """THE ASSERTION THIS CLASS EXISTS FOR. No tenant named, so RLS filters the row
        and `fetchone()` is None. That must read as "cannot tell", not as "available"."""
        from app.services.tactical_engine import tactical_engine

        assert await tactical_engine._is_maintenance_mode(str(assets["a"])) is True, (
            "an asset the engine cannot see was treated as available to command"
        )

    async def test_another_tenants_asset_is_invisible_and_therefore_suppressed(
        self, app, assets, seeded_orgs
    ):
        """Naming the wrong tenant is not a way to read across one. It suppresses for
        the same reason naming none does — and must not leak the flag either way."""
        from app.services.tactical_engine import tactical_engine

        assert await tactical_engine._is_maintenance_mode(
            str(assets["b"]), str(seeded_orgs["org_a_id"])
        ) is True

    async def test_the_suppression_is_not_a_broken_connection(
        self, app, assets, seeded_orgs
    ):
        """Rule 21, and it caught this file. The four suppression assertions are all
        `is True`, and the except branch ALSO returns True — the first run of this suite
        "passed" three of them against `role "placeholder" does not exist`, because the
        engine dials `AsyncSessionLocal` and only the `app` fixture rebinds it at the
        testcontainer. A suppression proves something only if the same session can
        produce a non-suppression."""
        from app.services.tactical_engine import tactical_engine

        assert await tactical_engine._is_maintenance_mode(
            str(assets["a"]), str(seeded_orgs["org_a_id"])
        ) is False, "the engine cannot reach the database at all; nothing above is a test"

    async def test_a_nonexistent_asset_suppresses(self, app, assets):
        from app.services.tactical_engine import tactical_engine

        assert await tactical_engine._is_maintenance_mode(
            str(uuid4()), str(uuid4())
        ) is True

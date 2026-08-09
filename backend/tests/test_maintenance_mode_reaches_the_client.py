"""The third side of maintenance mode: an operator has to be able to SEE it.

Migration 053 added `assets.maintenance_mode`. `POST /admin/assets/{id}/maintenance` writes
it, tenant-scoped and rowcount-checked. `TacticalEngine._is_maintenance_mode` reads it and
suppresses control commands. All of that was fixed together — and the feature still could
not be used, because **`AssetResponse` did not declare the field**.

FastAPI validates a handler's return against `response_model` and silently drops anything
the model does not carry. So the column existed, the write worked, the engine honoured it,
and every asset read came back without it. An operator could take a machine out of service,
have the engine correctly stop commanding it, and see no sign of either anywhere in the
product.

The frontend even had a name for it: `Asset.isInMaintenance`, declared as a required
boolean and populated only by the mock fixtures — so it was `undefined` on every real
response, and no endpoint has ever sent that name. It is `maintenanceMode` now, which is
what `/api/v1/assets` delivers through the casing seam.

WHY THIS NEEDED ITS OWN TEST. `test_maintenance_mode_realdb.py` proves the write lands by
reading the column back with psycopg2 — a privileged path that bypasses the API entirely.
That is method rule 20: verifying a write through a privileged path proves the write, not
the read. The read is a separate claim and this file is where it is made.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
import pytest_asyncio

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def asset(admin_sync_url, seeded_orgs):
    import psycopg2

    conn = psycopg2.connect(admin_sync_url)
    conn.autocommit = True
    type_id, asset_id = uuid4(), uuid4()
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO asset_types (id, name, category) VALUES (%s, %s, 'test')",
            (str(type_id), f"MMR-{type_id.hex[:8]}"),
        )
        cur.execute(
            "INSERT INTO assets (id, organization_id, workcell_id, asset_type_id, name, "
            "is_active) VALUES (%s, %s, %s, %s, 'Read Path Asset', true)",
            (str(asset_id), str(seeded_orgs["org_a_id"]),
             str(seeded_orgs["workcell_a_id"]), str(type_id)),
        )
    yield asset_id
    with conn.cursor() as cur:
        cur.execute("DELETE FROM assets WHERE id = %s", (str(asset_id),))
        cur.execute("DELETE FROM asset_types WHERE id = %s", (str(type_id),))
    conn.close()


class TestTheSchemaCarriesIt:
    def test_asset_response_declares_the_field(self):
        """Pinned separately from the behaviour, because this is the thing that was
        missing while everything around it worked. FastAPI drops what the schema omits,
        so a model without this field silently deletes it from every response."""
        from app.models.schemas import AssetResponse

        assert "maintenance_mode" in AssetResponse.model_fields


class TestItCrossesTheWire:
    async def test_a_fresh_asset_reports_not_in_maintenance(self, client_a, asset):
        """The positive control for the assertion below — and a real property: the field
        must be present and False, not absent. An absent key is indistinguishable from an
        older deployment and leaves the client guessing."""
        response = await client_a.get(f"/api/v1/assets/{asset}")
        assert response.status_code == 200, response.text
        body = response.json()
        assert "maintenance_mode" in body, (
            "the field is missing from the response entirely; the schema dropped it"
        )
        assert body["maintenance_mode"] is False

    async def test_it_reflects_a_write(self, client_a, asset):
        """THE ASSERTION THIS FILE EXISTS FOR. Write through the admin endpoint, read
        through the ordinary asset endpoint — no psycopg2 in between, because the point is
        that a CLIENT can see it."""
        write = await client_a.post(
            f"/admin/assets/{asset}/maintenance", params={"enabled": True}
        )
        assert write.status_code == 200, write.text

        read = await client_a.get(f"/api/v1/assets/{asset}")
        assert read.json()["maintenance_mode"] is True, (
            "the write succeeded and the asset still reads as available"
        )

    async def test_it_reflects_a_clearing_write(self, client_a, asset):
        """The other direction: a flag that can be set and not cleared is a machine that
        can never be returned to service."""
        await client_a.post(
            f"/admin/assets/{asset}/maintenance", params={"enabled": True}
        )
        await client_a.post(
            f"/admin/assets/{asset}/maintenance", params={"enabled": False}
        )
        read = await client_a.get(f"/api/v1/assets/{asset}")
        assert read.json()["maintenance_mode"] is False

    async def test_the_list_endpoint_carries_it_too(self, client_a, asset):
        """The detail page is not the only reader — an asset list is where an operator
        would scan for machines that are out of service."""
        await client_a.post(
            f"/admin/assets/{asset}/maintenance", params={"enabled": True}
        )
        listed = (await client_a.get("/api/v1/assets/", params={"limit": 500})).json()
        rows = listed["items"] if isinstance(listed, dict) else listed
        match = [a for a in rows if a["id"] == str(asset)]
        assert match, "the asset is not in its own organisation's list"
        assert match[0]["maintenance_mode"] is True

"""API-level tenant-isolation tests for assets and telemetry endpoints.

Verifies that the FastAPI dependency chain (``get_tenant_org_id`` +
``get_tenant_db``) refuses cross-tenant access at the HTTP layer.
Returns 404 (not 403) for the non-owner — that's the deliberate choice
from PR #2/3 to avoid leaking existence of resources in other tenants.

These tests exercise the same code path as production traffic: real
ASGI, real auth dependency, real SQL against the test database. The
only override is the engine, which is rebound to the ephemeral test
container in ``conftest.py``.
"""

from __future__ import annotations

from uuid import uuid4


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _seed_asset_type(admin_sync_url: str) -> str:
    """Insert a global AssetType row (asset_types is not tenant-scoped)."""
    import psycopg2

    type_id = str(uuid4())
    conn = psycopg2.connect(admin_sync_url)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO asset_types (id, name, category) VALUES (%s, %s, %s);",
                (type_id, "TestType", "test"),
            )
    finally:
        conn.close()
    return type_id


async def _create_asset_for(
    client, asset_type_id: str, name: str, workcell_id
) -> dict:
    """POST a new asset via the API and return the JSON response.

    ``organization_id`` is required by the ``AssetCreate`` schema but is
    ignored by the endpoint (server-side override from the JWT), so we
    send a throwaway value. ``workcell_id`` is required because
    ``assets.workcell_id`` is NOT NULL.
    """
    response = await client.post(
        "/api/v1/assets/",
        json={
            "name": name,
            "asset_type_id": asset_type_id,
            "organization_id": str(uuid4()),
            "workcell_id": str(workcell_id),
            "connection_config": {},
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


# ---------------------------------------------------------------------------
# Assets — cross-tenant access
# ---------------------------------------------------------------------------

class TestAssetsCrossTenantAccess:
    """User in Org B must not be able to see / mutate / delete Org A's assets."""

    async def test_get_other_orgs_asset_returns_404(
        self, client_a, client_b, admin_sync_url, seeded_orgs
    ):
        asset_type_id = await _seed_asset_type(admin_sync_url)
        asset = await _create_asset_for(
            client_a, asset_type_id, "A-only asset", seeded_orgs["workcell_a_id"]
        )

        # Owner can see it
        own = await client_a.get(f"/api/v1/assets/{asset['id']}")
        assert own.status_code == 200

        # Foreign tenant gets 404 (not 403 — deliberate)
        foreign = await client_b.get(f"/api/v1/assets/{asset['id']}")
        assert foreign.status_code == 404

    async def test_update_other_orgs_asset_returns_404(
        self, client_a, client_b, admin_sync_url, seeded_orgs
    ):
        asset_type_id = await _seed_asset_type(admin_sync_url)
        asset = await _create_asset_for(
            client_a, asset_type_id, "A-only asset 2", seeded_orgs["workcell_a_id"]
        )

        foreign = await client_b.put(
            f"/api/v1/assets/{asset['id']}",
            json={"name": "Hacked"},
        )
        assert foreign.status_code == 404

    async def test_delete_other_orgs_asset_returns_404(
        self, client_a, client_b, admin_sync_url, seeded_orgs
    ):
        asset_type_id = await _seed_asset_type(admin_sync_url)
        asset = await _create_asset_for(
            client_a, asset_type_id, "A-only asset 3", seeded_orgs["workcell_a_id"]
        )

        foreign = await client_b.delete(f"/api/v1/assets/{asset['id']}")
        assert foreign.status_code == 404

    async def test_list_assets_only_returns_callers_org(
        self, client_a, client_b, admin_sync_url, seeded_orgs
    ):
        asset_type_id = await _seed_asset_type(admin_sync_url)
        await _create_asset_for(
            client_a, asset_type_id, "A asset", seeded_orgs["workcell_a_id"]
        )
        await _create_asset_for(
            client_b, asset_type_id, "B asset", seeded_orgs["workcell_b_id"]
        )

        a_listing = await client_a.get("/api/v1/assets/")
        b_listing = await client_b.get("/api/v1/assets/")

        a_names = {row["name"] for row in a_listing.json()}
        b_names = {row["name"] for row in b_listing.json()}

        assert "A asset" in a_names
        assert "B asset" not in a_names
        assert "B asset" in b_names
        assert "A asset" not in b_names


# ---------------------------------------------------------------------------
# Assets — server-side organization_id override
# ---------------------------------------------------------------------------

class TestServerSideOrgIdOverride:
    """A client cannot bind their new asset to a different organization.

    Even if the request body carries ``organization_id`` of another org,
    the server overrides it (see PR #2/3 fix in ``assets.py``).
    """

    async def test_post_with_foreign_organization_id_is_overridden(
        self, client_a, admin_sync_url, seeded_orgs
    ):
        asset_type_id = await _seed_asset_type(admin_sync_url)
        foreign_org_id = str(seeded_orgs["org_b_id"])

        response = await client_a.post(
            "/api/v1/assets/",
            json={
                "name": "Sneaky asset",
                "asset_type_id": asset_type_id,
                "organization_id": foreign_org_id,  # attempt to bind to org B
                "workcell_id": str(seeded_orgs["workcell_a_id"]),
                "connection_config": {},
            },
        )
        assert response.status_code == 200
        body = response.json()

        # The asset must have been bound to org A (the JWT owner), not
        # to org B as the client requested.
        assert body["organization_id"] == str(seeded_orgs["org_a_id"])


# ---------------------------------------------------------------------------
# Telemetry — cross-tenant access
# ---------------------------------------------------------------------------

class TestTelemetryCrossTenantAccess:
    """Telemetry inherits tenant scope via its parent Asset.

    The ``_verify_asset_in_org`` helper from PR #2/3 returns 404 before
    the telemetry query runs if the asset isn't in the caller's org.
    """

    async def test_latest_telemetry_for_other_orgs_asset_returns_404(
        self, client_a, client_b, admin_sync_url, seeded_orgs
    ):
        asset_type_id = await _seed_asset_type(admin_sync_url)
        asset = await _create_asset_for(
            client_a, asset_type_id, "Telem A", seeded_orgs["workcell_a_id"]
        )

        foreign = await client_b.get(f"/api/v1/telemetry/{asset['id']}/latest")
        assert foreign.status_code == 404

    async def test_history_for_other_orgs_asset_returns_404(
        self, client_a, client_b, admin_sync_url, seeded_orgs
    ):
        asset_type_id = await _seed_asset_type(admin_sync_url)
        asset = await _create_asset_for(
            client_a, asset_type_id, "Telem A 2", seeded_orgs["workcell_a_id"]
        )

        foreign = await client_b.get(f"/api/v1/telemetry/{asset['id']}/history")
        assert foreign.status_code == 404

    async def test_metrics_for_other_orgs_asset_returns_404(
        self, client_a, client_b, admin_sync_url, seeded_orgs
    ):
        asset_type_id = await _seed_asset_type(admin_sync_url)
        asset = await _create_asset_for(
            client_a, asset_type_id, "Telem A 3", seeded_orgs["workcell_a_id"]
        )

        foreign = await client_b.get(f"/api/v1/telemetry/{asset['id']}/metrics")
        assert foreign.status_code == 404


# ---------------------------------------------------------------------------
# Unauthenticated / no-org access
# ---------------------------------------------------------------------------

class TestUnauthenticatedAccess:
    """No bearer token → 401 from the JWT dependency before tenant logic runs."""

    async def test_assets_list_without_auth_returns_401(self, app):
        from httpx import ASGITransport, AsyncClient

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as anon:
            response = await anon.get("/api/v1/assets/")
        assert response.status_code in (401, 403)

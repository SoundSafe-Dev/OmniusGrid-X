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

import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _seed_asset_type(
    admin_sync_url: str, name: str | None = None, category: str = "test"
) -> str:
    """Insert a global AssetType row (asset_types is not tenant-scoped)."""
    import psycopg2

    type_id = str(uuid4())
    type_name = name or f"TestType-{type_id[:8]}"
    conn = psycopg2.connect(admin_sync_url)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO asset_types (id, name, category) VALUES (%s, %s, %s);",
                (type_id, type_name, category),
            )
    finally:
        conn.close()
    return type_id


def _seed_workcell(admin_sync_url: str, org_id, name: str) -> str:
    """Insert a workcell for the given organization (superuser, bypasses RLS)."""
    import psycopg2

    workcell_id = str(uuid4())
    conn = psycopg2.connect(admin_sync_url)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO workcells (id, organization_id, name) VALUES (%s, %s, %s);",
                (workcell_id, str(org_id), name),
            )
    finally:
        conn.close()
    return workcell_id


def _insert_telemetry(
    admin_sync_url: str,
    asset_id: str,
    recorded_at: datetime,
    metric_name: str,
    value: float,
    *,
    unit: str = "C",
    packml_state: str = "Execute",
    metadata: dict | None = None,
    sequence_num: int = 1,
) -> None:
    """Insert telemetry via raw SQL using the real ``metadata`` column."""
    import psycopg2

    conn = psycopg2.connect(admin_sync_url)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO telemetry (
                    time,
                    asset_id,
                    metric_name,
                    value,
                    unit,
                    packml_state,
                    metadata,
                    sequence_num
                ) VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s);
                """,
                (
                    recorded_at,
                    asset_id,
                    metric_name,
                    value,
                    unit,
                    packml_state,
                    json.dumps(metadata or {}),
                    sequence_num,
                ),
            )
    finally:
        conn.close()


def _asset_names(response_json: list) -> set[str]:
    return {row["name"] for row in response_json}


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


# ---------------------------------------------------------------------------
# Task 2 — list_assets filter and client-override regression
# ---------------------------------------------------------------------------

class TestListAssetsFilters:
    async def test_client_supplied_organization_id_cannot_change_list_scope(
        self, client_a, client_b, admin_sync_url, seeded_orgs
    ):
        suffix = uuid4().hex[:8]
        asset_type_id = await _seed_asset_type(admin_sync_url, f"ListOrgType-{suffix}")
        await _create_asset_for(
            client_a, asset_type_id, f"list-org-a-{suffix}", seeded_orgs["workcell_a_id"]
        )
        await _create_asset_for(
            client_b, asset_type_id, f"list-org-b-{suffix}", seeded_orgs["workcell_b_id"]
        )

        response = await client_a.get(
            "/api/v1/assets/",
            params={"organization_id": str(seeded_orgs["org_b_id"])},
        )
        assert response.status_code == 200
        names = _asset_names(response.json())
        assert f"list-org-a-{suffix}" in names
        assert f"list-org-b-{suffix}" not in names

    async def test_workcell_id_filter(
        self, client_a, client_b, admin_sync_url, seeded_orgs
    ):
        suffix = uuid4().hex[:8]
        asset_type_id = await _seed_asset_type(admin_sync_url, f"WcType-{suffix}")
        wc_a2 = _seed_workcell(admin_sync_url, seeded_orgs["org_a_id"], f"Workcell-A2-{suffix}")

        asset_wc1 = await _create_asset_for(
            client_a, asset_type_id, f"wc1-a-{suffix}", seeded_orgs["workcell_a_id"]
        )
        asset_wc2 = await _create_asset_for(
            client_a, asset_type_id, f"wc2-a-{suffix}", wc_a2
        )
        await _create_asset_for(
            client_b, asset_type_id, f"wc-b-{suffix}", seeded_orgs["workcell_b_id"]
        )

        list_wc1 = await client_a.get(
            "/api/v1/assets/", params={"workcell_id": str(seeded_orgs["workcell_a_id"])}
        )
        assert list_wc1.status_code == 200
        ids_wc1 = {row["id"] for row in list_wc1.json()}
        assert asset_wc1["id"] in ids_wc1
        assert asset_wc2["id"] not in ids_wc1
        assert f"wc-b-{suffix}" not in _asset_names(list_wc1.json())

        list_wc2 = await client_a.get("/api/v1/assets/", params={"workcell_id": wc_a2})
        assert list_wc2.status_code == 200
        ids_wc2 = {row["id"] for row in list_wc2.json()}
        assert asset_wc2["id"] in ids_wc2
        assert asset_wc1["id"] not in ids_wc2

    async def test_asset_type_id_filter(
        self, client_a, client_b, admin_sync_url, seeded_orgs
    ):
        suffix = uuid4().hex[:8]
        type_a = await _seed_asset_type(admin_sync_url, f"TypeA-{suffix}")
        type_b = await _seed_asset_type(admin_sync_url, f"TypeB-{suffix}")

        asset_type_a = await _create_asset_for(
            client_a, type_a, f"type-a-{suffix}", seeded_orgs["workcell_a_id"]
        )
        asset_type_b = await _create_asset_for(
            client_a, type_b, f"type-b-{suffix}", seeded_orgs["workcell_a_id"]
        )
        await _create_asset_for(
            client_b, type_a, f"type-foreign-{suffix}", seeded_orgs["workcell_b_id"]
        )

        list_a = await client_a.get("/api/v1/assets/", params={"asset_type_id": type_a})
        assert list_a.status_code == 200
        ids = {row["id"] for row in list_a.json()}
        assert asset_type_a["id"] in ids
        assert asset_type_b["id"] not in ids
        assert f"type-foreign-{suffix}" not in _asset_names(list_a.json())

        list_b = await client_a.get("/api/v1/assets/", params={"asset_type_id": type_b})
        assert list_b.status_code == 200
        ids_b = {row["id"] for row in list_b.json()}
        assert asset_type_b["id"] in ids_b
        assert asset_type_a["id"] not in ids_b

    async def test_is_active_filter(
        self, client_a, client_b, admin_sync_url, seeded_orgs
    ):
        suffix = uuid4().hex[:8]
        asset_type_id = await _seed_asset_type(admin_sync_url, f"ActiveType-{suffix}")

        active_asset = await _create_asset_for(
            client_a, asset_type_id, f"active-a-{suffix}", seeded_orgs["workcell_a_id"]
        )
        inactive_asset = await _create_asset_for(
            client_a, asset_type_id, f"inactive-a-{suffix}", seeded_orgs["workcell_a_id"]
        )
        delete_resp = await client_a.delete(f"/api/v1/assets/{inactive_asset['id']}")
        assert delete_resp.status_code == 200

        await _create_asset_for(
            client_b, asset_type_id, f"active-b-{suffix}", seeded_orgs["workcell_b_id"]
        )

        active_list = await client_a.get("/api/v1/assets/", params={"is_active": "true"})
        assert active_list.status_code == 200
        active_names = _asset_names(active_list.json())
        assert f"active-a-{suffix}" in active_names
        assert f"inactive-a-{suffix}" not in active_names
        assert f"active-b-{suffix}" not in active_names
        assert active_asset["id"] in {row["id"] for row in active_list.json()}

        inactive_list = await client_a.get(
            "/api/v1/assets/", params={"is_active": "false"}
        )
        assert inactive_list.status_code == 200
        inactive_names = _asset_names(inactive_list.json())
        assert f"inactive-a-{suffix}" in inactive_names
        assert f"active-a-{suffix}" not in inactive_names
        assert f"active-b-{suffix}" not in inactive_names

    async def test_combined_filters(
        self, client_a, admin_sync_url, seeded_orgs
    ):
        suffix = uuid4().hex[:8]
        type_match = await _seed_asset_type(admin_sync_url, f"ComboMatch-{suffix}")
        type_other = await _seed_asset_type(admin_sync_url, f"ComboOther-{suffix}")
        wc_match = _seed_workcell(admin_sync_url, seeded_orgs["org_a_id"], f"ComboWC-{suffix}")

        target = await _create_asset_for(
            client_a, type_match, f"combo-target-{suffix}", wc_match
        )
        await _create_asset_for(
            client_a, type_other, f"combo-wrong-type-{suffix}", wc_match
        )
        await _create_asset_for(
            client_a, type_match, f"combo-wrong-wc-{suffix}", seeded_orgs["workcell_a_id"]
        )
        to_deactivate = await _create_asset_for(
            client_a, type_match, f"combo-inactive-{suffix}", wc_match
        )
        assert (await client_a.delete(f"/api/v1/assets/{to_deactivate['id']}")).status_code == 200

        response = await client_a.get(
            "/api/v1/assets/",
            params={
                "workcell_id": wc_match,
                "asset_type_id": type_match,
                "is_active": "true",
            },
        )
        assert response.status_code == 200
        rows = response.json()
        assert len(rows) == 1
        assert rows[0]["id"] == target["id"]
        assert rows[0]["name"] == f"combo-target-{suffix}"


# ---------------------------------------------------------------------------
# Task 3 — single-asset status and rejected mutation proof
# ---------------------------------------------------------------------------

class TestSingleAssetCoverage:
    async def test_asset_status_owner_access(
        self, client_a, admin_sync_url, seeded_orgs
    ):
        suffix = uuid4().hex[:8]
        asset_type_id = await _seed_asset_type(admin_sync_url, f"StatusType-{suffix}")
        created = await _create_asset_for(
            client_a, asset_type_id, f"status-owner-{suffix}", seeded_orgs["workcell_a_id"]
        )

        response = await client_a.get(f"/api/v1/assets/{created['id']}/status")
        assert response.status_code == 200
        body = response.json()
        assert body["asset_id"] == created["id"]
        assert body["name"] == f"status-owner-{suffix}"
        assert body["current_packml_state"] == created["current_packml_state"]
        assert body["is_active"] is True

    async def test_asset_status_cross_tenant_returns_404(
        self, client_a, client_b, admin_sync_url, seeded_orgs
    ):
        suffix = uuid4().hex[:8]
        asset_type_id = await _seed_asset_type(admin_sync_url, f"StatusXType-{suffix}")
        created = await _create_asset_for(
            client_a, asset_type_id, f"status-x-{suffix}", seeded_orgs["workcell_a_id"]
        )

        foreign = await client_b.get(f"/api/v1/assets/{created['id']}/status")
        assert foreign.status_code == 404

    async def test_rejected_foreign_update_causes_no_mutation(
        self, client_a, client_b, admin_sync_url, seeded_orgs
    ):
        suffix = uuid4().hex[:8]
        original_name = f"immutable-{suffix}"
        asset_type_id = await _seed_asset_type(admin_sync_url, f"UpdType-{suffix}")
        created = await _create_asset_for(
            client_a, asset_type_id, original_name, seeded_orgs["workcell_a_id"]
        )

        foreign = await client_b.put(
            f"/api/v1/assets/{created['id']}",
            json={"name": f"hacked-{suffix}"},
        )
        assert foreign.status_code == 404

        own = await client_a.get(f"/api/v1/assets/{created['id']}")
        assert own.status_code == 200
        assert own.json()["name"] == original_name

    async def test_rejected_foreign_delete_causes_no_mutation(
        self, client_a, client_b, admin_sync_url, seeded_orgs
    ):
        suffix = uuid4().hex[:8]
        asset_type_id = await _seed_asset_type(admin_sync_url, f"DelType-{suffix}")
        created = await _create_asset_for(
            client_a, asset_type_id, f"delete-proof-{suffix}", seeded_orgs["workcell_a_id"]
        )

        foreign = await client_b.delete(f"/api/v1/assets/{created['id']}")
        assert foreign.status_code == 404

        own = await client_a.get(f"/api/v1/assets/{created['id']}")
        assert own.status_code == 200
        assert own.json()["is_active"] is True


# ---------------------------------------------------------------------------
# Task 4 — telemetry positive-path coverage and ORM mapping contract
# ---------------------------------------------------------------------------

class TestTelemetryMappingContract:
    def test_meta_data_maps_to_metadata_column(self):
        from app.db.models import Telemetry

        assert Telemetry.meta_data.property.columns[0].name == "metadata"


class TestTelemetryPositivePath:
    async def test_latest_telemetry_for_owner(
        self, client_a, admin_sync_url, seeded_orgs
    ):
        suffix = uuid4().hex[:8]
        asset_type_id = await _seed_asset_type(admin_sync_url, f"TelemLatest-{suffix}")
        asset = await _create_asset_for(
            client_a, asset_type_id, f"telem-latest-{suffix}", seeded_orgs["workcell_a_id"]
        )
        older = datetime.now(timezone.utc) - timedelta(minutes=10)
        newer = datetime.now(timezone.utc) - timedelta(minutes=1)
        metric = f"temp-{suffix}"
        _insert_telemetry(
            admin_sync_url,
            asset["id"],
            older,
            metric,
            20.0,
            metadata={"seed": "older", "suffix": suffix},
            sequence_num=1,
        )
        _insert_telemetry(
            admin_sync_url,
            asset["id"],
            newer,
            metric,
            25.5,
            metadata={"seed": "newer", "suffix": suffix},
            sequence_num=2,
        )

        response = await client_a.get(f"/api/v1/telemetry/{asset['id']}/latest")
        assert response.status_code == 200
        body = response.json()
        assert body["metric_name"] == metric
        assert body["value"] == 25.5
        assert body["metadata"] == {"seed": "newer", "suffix": suffix}

    async def test_latest_telemetry_metric_filter(
        self, client_a, admin_sync_url, seeded_orgs
    ):
        suffix = uuid4().hex[:8]
        asset_type_id = await _seed_asset_type(admin_sync_url, f"TelemFilter-{suffix}")
        asset = await _create_asset_for(
            client_a, asset_type_id, f"telem-filter-{suffix}", seeded_orgs["workcell_a_id"]
        )
        now = datetime.now(timezone.utc)
        temp_metric = f"temperature-{suffix}"
        pressure_metric = f"pressure-{suffix}"
        _insert_telemetry(
            admin_sync_url, asset["id"], now - timedelta(minutes=2),
            temp_metric, 22.0, sequence_num=1,
        )
        _insert_telemetry(
            admin_sync_url, asset["id"], now - timedelta(minutes=1),
            pressure_metric, 101.3, unit="kPa", sequence_num=2,
        )

        response = await client_a.get(
            f"/api/v1/telemetry/{asset['id']}/latest",
            params={"metric_name": temp_metric},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["metric_name"] == temp_metric
        assert body["value"] == 22.0

    async def test_telemetry_history_for_owner(
        self, client_a, admin_sync_url, seeded_orgs
    ):
        suffix = uuid4().hex[:8]
        asset_type_id = await _seed_asset_type(admin_sync_url, f"TelemHist-{suffix}")
        asset = await _create_asset_for(
            client_a, asset_type_id, f"telem-history-{suffix}", seeded_orgs["workcell_a_id"]
        )
        start = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
        mid = datetime(2026, 6, 1, 13, 0, tzinfo=timezone.utc)
        end = datetime(2026, 6, 1, 14, 0, tzinfo=timezone.utc)
        metric = f"flow-{suffix}"
        _insert_telemetry(
            admin_sync_url, asset["id"], start, metric, 1.0,
            metadata={"point": "start"}, sequence_num=1,
        )
        _insert_telemetry(
            admin_sync_url, asset["id"], mid, metric, 2.0,
            metadata={"point": "mid"}, sequence_num=2,
        )
        _insert_telemetry(
            admin_sync_url, asset["id"], end, metric, 3.0,
            metadata={"point": "end"}, sequence_num=3,
        )

        response = await client_a.get(
            f"/api/v1/telemetry/{asset['id']}/history",
            params={
                "start_time": start.isoformat(),
                "end_time": end.isoformat(),
            },
        )
        assert response.status_code == 200
        rows = response.json()
        assert len(rows) == 3
        assert [row["value"] for row in rows] == [3.0, 2.0, 1.0]
        assert rows[0]["metadata"] == {"point": "end"}
        assert rows[1]["metadata"] == {"point": "mid"}
        assert rows[2]["metadata"] == {"point": "start"}

    async def test_history_metric_filter(
        self, client_a, admin_sync_url, seeded_orgs
    ):
        suffix = uuid4().hex[:8]
        asset_type_id = await _seed_asset_type(admin_sync_url, f"HistMetric-{suffix}")
        asset = await _create_asset_for(
            client_a, asset_type_id, f"hist-metric-{suffix}", seeded_orgs["workcell_a_id"]
        )
        start = datetime(2026, 6, 2, 10, 0, tzinfo=timezone.utc)
        end = datetime(2026, 6, 2, 12, 0, tzinfo=timezone.utc)
        temp_metric = f"temp-hist-{suffix}"
        humidity_metric = f"humidity-hist-{suffix}"
        _insert_telemetry(
            admin_sync_url, asset["id"], start, temp_metric, 18.0, sequence_num=1,
        )
        _insert_telemetry(
            admin_sync_url, asset["id"], start + timedelta(hours=1),
            humidity_metric, 55.0, sequence_num=2,
        )

        response = await client_a.get(
            f"/api/v1/telemetry/{asset['id']}/history",
            params={
                "start_time": start.isoformat(),
                "end_time": end.isoformat(),
                "metric_name": temp_metric,
            },
        )
        assert response.status_code == 200
        rows = response.json()
        assert len(rows) == 1
        assert rows[0]["metric_name"] == temp_metric

    async def test_available_metrics(
        self, client_a, admin_sync_url, seeded_orgs
    ):
        suffix = uuid4().hex[:8]
        asset_type_id = await _seed_asset_type(admin_sync_url, f"Metrics-{suffix}")
        asset = await _create_asset_for(
            client_a, asset_type_id, f"metrics-{suffix}", seeded_orgs["workcell_a_id"]
        )
        now = datetime.now(timezone.utc)
        metric_a = f"metric-a-{suffix}"
        metric_b = f"metric-b-{suffix}"
        _insert_telemetry(
            admin_sync_url, asset["id"], now, metric_a, 1.0, sequence_num=1,
        )
        _insert_telemetry(
            admin_sync_url, asset["id"], now + timedelta(seconds=1),
            metric_b, 2.0, sequence_num=2,
        )
        _insert_telemetry(
            admin_sync_url, asset["id"], now + timedelta(seconds=2),
            metric_a, 1.5, sequence_num=3,
        )

        response = await client_a.get(f"/api/v1/telemetry/{asset['id']}/metrics")
        assert response.status_code == 200
        metrics = set(response.json()["metrics"])
        assert metrics == {metric_a, metric_b}

    async def test_tenant_separation_with_real_telemetry(
        self, client_a, client_b, admin_sync_url, seeded_orgs
    ):
        suffix = uuid4().hex[:8]
        asset_type_id = await _seed_asset_type(admin_sync_url, f"TelemTenant-{suffix}")
        asset_a = await _create_asset_for(
            client_a, asset_type_id, f"telem-a-{suffix}", seeded_orgs["workcell_a_id"]
        )
        asset_b = await _create_asset_for(
            client_b, asset_type_id, f"telem-b-{suffix}", seeded_orgs["workcell_b_id"]
        )
        now = datetime.now(timezone.utc)
        metric_a = f"tenant-a-{suffix}"
        metric_b = f"tenant-b-{suffix}"
        _insert_telemetry(
            admin_sync_url, asset_a["id"], now, metric_a, 10.0, sequence_num=1,
        )
        _insert_telemetry(
            admin_sync_url, asset_b["id"], now, metric_b, 20.0, sequence_num=1,
        )

        latest_a = await client_a.get(f"/api/v1/telemetry/{asset_a['id']}/latest")
        assert latest_a.status_code == 200
        assert latest_a.json()["metric_name"] == metric_a

        history_a = await client_a.get(f"/api/v1/telemetry/{asset_a['id']}/history")
        assert history_a.status_code == 200
        assert all(row["metric_name"] == metric_a for row in history_a.json())

        metrics_a = await client_a.get(f"/api/v1/telemetry/{asset_a['id']}/metrics")
        assert metrics_a.status_code == 200
        assert set(metrics_a.json()["metrics"]) == {metric_a}

        foreign_latest = await client_a.get(f"/api/v1/telemetry/{asset_b['id']}/latest")
        assert foreign_latest.status_code == 404

        foreign_history = await client_a.get(f"/api/v1/telemetry/{asset_b['id']}/history")
        assert foreign_history.status_code == 404

        foreign_metrics = await client_a.get(f"/api/v1/telemetry/{asset_b['id']}/metrics")
        assert foreign_metrics.status_code == 404

        own_b = await client_b.get(f"/api/v1/telemetry/{asset_b['id']}/latest")
        assert own_b.status_code == 200
        assert own_b.json()["metric_name"] == metric_b

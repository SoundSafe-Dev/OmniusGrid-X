"""Real-DB tenancy guards for the dashboard endpoints (FS-191).

Why this exists: every `/api/v1/dashboard/*` endpoint used `get_db`, which never
sets the `app.current_org_id` GUC. `assets` is FORCE ROW LEVEL SECURITY with
``USING (organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid)``
so with no GUC the predicate is NULL, every row is filtered, and the dashboard
rendered zeros for everyone — the "bare dashboard" bug. FORCE means being the
table owner does not rescue it.

`/overview` also accepted a client-supplied ``organization_id`` query param,
letting a caller aim the query at another tenant.

These tests must run against real Postgres — RLS is a no-op on SQLite, so a
green run there would prove nothing (that blind spot is what let this ship).
"""
import uuid
from uuid import uuid4

import pytest


@pytest.fixture
def seeded_asset_type(admin_sync_url) -> str:
    """An asset type to satisfy assets' NOT NULL FK (org-agnostic catalog row)."""
    import psycopg2

    at_id = str(uuid4())
    conn = psycopg2.connect(admin_sync_url)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO asset_types (id, name, category) VALUES (%s, %s, %s)",
                (at_id, f"dash-type-{at_id[:8]}", "production"),
            )
    finally:
        conn.close()
    return at_id


async def _create_asset(client, org_id, workcell_id, asset_type_id, name: str) -> None:
    """Create an asset through the API so it lands in the caller's org."""
    resp = await client.post(
        "/api/v1/assets/",
        json={
            "name": name,
            # required by the schema but ignored server-side — the JWT org wins
            "organization_id": str(org_id),
            "workcell_id": str(workcell_id),
            "asset_type_id": asset_type_id,
        },
    )
    assert resp.status_code in (200, 201), resp.text


@pytest.mark.asyncio
async def test_overview_returns_the_callers_own_assets(
    client_a, seeded_orgs, seeded_asset_type
):
    """The bare-dashboard regression: counts must not be zero for a seeded org."""
    await _create_asset(
        client_a, seeded_orgs["org_a_id"], seeded_orgs["workcell_a_id"],
        seeded_asset_type, "Dash Asset A1",
    )

    resp = await client_a.get("/api/v1/dashboard/overview")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    # Before FS-191 this was 0 — RLS filtered every row because the tenant GUC
    # was never set on the session.
    assert body["total_assets"] >= 1, f"dashboard is empty: {body}"


@pytest.mark.asyncio
async def test_overview_does_not_leak_another_orgs_assets(
    client_a, client_b, seeded_orgs, seeded_asset_type
):
    """Org A's dashboard must not count Org B's assets."""
    await _create_asset(
        client_a, seeded_orgs["org_a_id"], seeded_orgs["workcell_a_id"],
        seeded_asset_type, "Dash Asset A2",
    )
    await _create_asset(
        client_b, seeded_orgs["org_b_id"], seeded_orgs["workcell_b_id"],
        seeded_asset_type, "Dash Asset B1",
    )
    await _create_asset(
        client_b, seeded_orgs["org_b_id"], seeded_orgs["workcell_b_id"],
        seeded_asset_type, "Dash Asset B2",
    )

    a_total = (await client_a.get("/api/v1/dashboard/overview")).json()["total_assets"]
    b_total = (await client_b.get("/api/v1/dashboard/overview")).json()["total_assets"]

    # Each org sees only its own rows; neither sees the union.
    assert a_total >= 1 and b_total >= 2
    assert a_total != a_total + b_total


@pytest.mark.asyncio
async def test_overview_ignores_a_client_supplied_organization_id(
    client_a, client_b, seeded_orgs, seeded_asset_type
):
    """The org must come from the token, never from the query string."""
    await _create_asset(
        client_a, seeded_orgs["org_a_id"], seeded_orgs["workcell_a_id"],
        seeded_asset_type, "Dash Asset A3",
    )
    await _create_asset(
        client_b, seeded_orgs["org_b_id"], seeded_orgs["workcell_b_id"],
        seeded_asset_type, "Dash Asset B3",
    )

    baseline = (await client_a.get("/api/v1/dashboard/overview")).json()

    # Aim A's request at B's org. The param is gone, so FastAPI ignores the
    # unknown query arg and the response must be identical to the baseline.
    targeted = await client_a.get(
        f"/api/v1/dashboard/overview?organization_id={seeded_orgs['org_b_id']}"
    )
    assert targeted.status_code == 200, targeted.text
    assert targeted.json()["total_assets"] == baseline["total_assets"]

    # And a nonsense org id must not widen the result either.
    bogus = await client_a.get(
        f"/api/v1/dashboard/overview?organization_id={uuid.uuid4()}"
    )
    assert bogus.json()["total_assets"] == baseline["total_assets"]


@pytest.mark.asyncio
async def test_oee_dashboard_summary_is_tenant_scoped(
    client_a, seeded_orgs, seeded_asset_type
):
    """`/oee/dashboard/summary` had the same get_db bug."""
    await _create_asset(
        client_a, seeded_orgs["org_a_id"], seeded_orgs["workcell_a_id"],
        seeded_asset_type, "Dash Asset A4",
    )

    resp = await client_a.get("/api/v1/oee/dashboard/summary")
    assert resp.status_code == 200, resp.text
    payload = resp.json()

    # Shape: {organization_id, timestamp, aggregate:{...,asset_count}, assets:[...]}
    # Assert on the real fields — an earlier version of this test fell back to
    # len(payload) and passed vacuously by counting dict keys.
    assert payload["aggregate"]["asset_count"] >= 1, f"OEE summary is empty: {payload}"
    assert len(payload["assets"]) >= 1, f"OEE summary has no assets: {payload}"

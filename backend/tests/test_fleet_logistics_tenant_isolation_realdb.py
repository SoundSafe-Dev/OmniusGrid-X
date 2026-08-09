"""Geofencing and maintenance endpoints must not cross tenants.

THE DEFECT. All 23 handlers in `fleet_logistics.py` ran on `get_db`, and their four
tables — `geofence_zones`, `geofence_alerts`, `maintenance_schedules`, `repair_orders` —
carry `organization_id` but have **no row-level security**. So neither layer applied:
no filter in the handler, no policy in the database.

Confirmed against a real database before the fix, in two distinct shapes:

    GET /api/v1/geofencing/zones      -> returned every tenant's zones
    GET /api/v1/geofencing/zones/{id} -> returned another tenant's zone outright (IDOR)

The four create paths compounded it by taking `organization_id` **from the request
payload**, so a caller could file a record under any organization they named.

WHY THE EXISTING SUITE MISSED IT. `test_route_auth_walk.py` checks that routes demand
authentication — these do. The RLS isolation tests exercise policies, and these tables
have none, so they were invisible to exactly the suite meant to cover them.

THE FIX has two parts, because the session alone is not enough here: every handler moved
to `get_tenant_db`, AND every query on the four unprotected tables is wrapped in
`_scope(...)`. `organization_id` is `VARCHAR(36)` on all four, so the comparison is
against `str(org_id)` — comparing to a UUID object matches nothing and would look like
working isolation while emptying the page, which is why the "sees its own" assertions
below matter as much as the "cannot see the other" ones.

Same-file endpoints that read `Shipment`/`Carrier`/`Driver` were fixed by the same move
for the opposite reason: those tables DO have RLS, so on `get_db` — which sets no GUC —
they were returning zero rows.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def fixtures(admin_sync_url, seeded_orgs):
    """A zone, an alert, a schedule and a repair order in each of two orgs."""
    import psycopg2

    ids = {}
    conn = psycopg2.connect(admin_sync_url)
    conn.autocommit = True
    with conn.cursor() as cur:
        for suffix, org_key in (("a", "org_a_id"), ("b", "org_b_id")):
            org = str(seeded_orgs[org_key])
            zone, alert = uuid.uuid4(), uuid.uuid4()
            schedule, order = uuid.uuid4(), uuid.uuid4()
            cur.execute(
                "INSERT INTO geofence_zones (id, organization_id, name, is_active) "
                "VALUES (%s,%s,%s,true)", (str(zone), org, f"ZONE-{suffix}"))
            cur.execute(
                "INSERT INTO geofence_alerts (id, organization_id, zone_id, vehicle_id, "
                "event_type, severity, acknowledged) VALUES (%s,%s,%s,%s,'enter','warning',false)",
                (str(alert), org, str(zone), f"VEH-{suffix}"))
            cur.execute(
                "INSERT INTO maintenance_schedules (id, organization_id, vehicle_id, "
                "maintenance_type, status) VALUES (%s,%s,%s,'oil','scheduled')",
                (str(schedule), org, f"VEH-{suffix}"))
            cur.execute(
                "INSERT INTO repair_orders (id, organization_id, vehicle_id, title, status) "
                "VALUES (%s,%s,%s,%s,'open')",
                (str(order), org, f"VEH-{suffix}", f"RO-{suffix}"))
            ids[suffix] = {"zone": zone, "alert": alert, "schedule": schedule, "order": order}
    yield ids
    with conn.cursor() as cur:
        for kind, table in (("alert", "geofence_alerts"), ("zone", "geofence_zones"),
                            ("schedule", "maintenance_schedules"), ("order", "repair_orders")):
            cur.execute(
                f"DELETE FROM {table} WHERE id IN (%s, %s)",
                (str(ids["a"][kind]), str(ids["b"][kind])))
    conn.close()


async def _ids(client, path: str) -> set:
    response = await client.get(path)
    assert response.status_code == 200, f"{path} -> {response.status_code}: {response.text[:200]}"
    return {item.get("id") for item in response.json()}


LISTS = [
    ("/api/v1/geofencing/zones", "zone"),
    ("/api/v1/geofencing/alerts", "alert"),
    ("/api/v1/maintenance/schedules", "schedule"),
    ("/api/v1/maintenance/repair-orders", "order"),
]


class TestListsAreScopedToTheCaller:
    @pytest.mark.parametrize("path,kind", LISTS)
    async def test_another_orgs_row_is_not_listed(self, client_a, fixtures, path, kind):
        """THE ASSERTION THIS FILE EXISTS FOR."""
        assert str(fixtures["b"][kind]) not in await _ids(client_a, path), (
            f"{path} returned another organization's {kind}"
        )

    @pytest.mark.parametrize("path,kind", LISTS)
    async def test_the_caller_still_sees_its_own(self, client_a, fixtures, path, kind):
        """The other half. `organization_id` is VARCHAR(36); comparing it to a UUID
        object matches nothing, which empties the page while passing the isolation
        assertion above."""
        assert str(fixtures["a"][kind]) in await _ids(client_a, path), (
            f"{path} did not return the caller's own {kind} — the filter matches nothing"
        )

    @pytest.mark.parametrize("path,kind", LISTS)
    async def test_each_org_sees_only_its_own(self, client_a, client_b, fixtures, path, kind):
        a_ids, b_ids = await _ids(client_a, path), await _ids(client_b, path)
        assert str(fixtures["a"][kind]) in a_ids and str(fixtures["a"][kind]) not in b_ids
        assert str(fixtures["b"][kind]) in b_ids and str(fixtures["b"][kind]) not in a_ids


class TestFetchByIdIsNotAnIdor:
    """Reading another tenant's row by naming its id was possible on every one of
    these — the list filter and the by-id lookup are separate code paths."""

    @pytest.mark.parametrize("template,kind", [
        ("/api/v1/geofencing/zones/{}", "zone"),
        ("/api/v1/maintenance/schedules/{}", "schedule"),
        ("/api/v1/maintenance/repair-orders/{}", "order"),
    ])
    async def test_another_orgs_row_is_404(self, client_a, fixtures, template, kind):
        response = await client_a.get(template.format(fixtures["b"][kind]))
        assert response.status_code == 404, (
            f"{template} exposed another organization's {kind} "
            f"({response.status_code})"
        )

    @pytest.mark.parametrize("template,kind", [
        ("/api/v1/geofencing/zones/{}", "zone"),
        ("/api/v1/maintenance/schedules/{}", "schedule"),
        ("/api/v1/maintenance/repair-orders/{}", "order"),
    ])
    async def test_the_callers_own_row_is_reachable(self, client_a, fixtures, template, kind):
        """404-for-everything would satisfy the test above and break the product."""
        response = await client_a.get(template.format(fixtures["a"][kind]))
        assert response.status_code == 200, (
            f"the caller cannot read its own {kind}: {response.status_code}"
        )


class TestWritesTakeTheOrgFromTheToken:
    async def test_a_client_supplied_organization_id_is_ignored(
        self, client_a, seeded_orgs, admin_sync_url
    ):
        """`create_zone` took `organization_id` straight from the payload, so a caller
        could file a record under any organization they named — and with no RLS on the
        table, nothing downstream would question it."""
        import psycopg2

        response = await client_a.post(
            "/api/v1/geofencing/zones",
            json={
                "name": "planted",
                "organization_id": str(seeded_orgs["org_b_id"]),  # someone else's
                "center": {"lat": 1.0, "lng": 2.0},
                "radiusMeters": 10,
            },
        )
        assert response.status_code in (200, 201), response.text
        zone_id = response.json()["id"]

        conn = psycopg2.connect(admin_sync_url)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT organization_id FROM geofence_zones WHERE id = %s", (zone_id,)
                )
                stored = cur.fetchone()[0]
            assert str(stored) == str(seeded_orgs["org_a_id"]), (
                "the zone was filed under the organization named in the payload rather "
                "than the caller's own"
            )
        finally:
            conn = psycopg2.connect(admin_sync_url)
            conn.autocommit = True
            with conn.cursor() as cur:
                cur.execute("DELETE FROM geofence_zones WHERE id = %s", (zone_id,))
            conn.close()

    async def test_the_created_zone_is_visible_to_its_creator(self, client_a, admin_sync_url):
        """Filing under the token must not file it somewhere the creator cannot see."""
        import psycopg2

        response = await client_a.post(
            "/api/v1/geofencing/zones",
            json={"name": "mine", "center": {"lat": 1.0, "lng": 2.0}, "radiusMeters": 10},
        )
        assert response.status_code in (200, 201), response.text
        zone_id = response.json()["id"]
        try:
            assert zone_id in await _ids(client_a, "/api/v1/geofencing/zones")
        finally:
            conn = psycopg2.connect(admin_sync_url)
            conn.autocommit = True
            with conn.cursor() as cur:
                cur.execute("DELETE FROM geofence_zones WHERE id = %s", (zone_id,))
            conn.close()

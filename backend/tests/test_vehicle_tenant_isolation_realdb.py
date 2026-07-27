"""`GET /api/v1/transportation/vehicles` must not return another tenant's vehicles.

THE DEFECT — a live cross-tenant read, confirmed against a real database before the fix.

    query = select(Vehicle).where(Vehicle.is_active == True)

No organization filter at all, on `get_db` (which sets no tenant GUC). The `vehicles`
table carries `organization_id` but has **no row-level security**, so both mechanisms
that normally catch this missed: the application layer never filtered, and the database
had no policy to fall back on.

Every authenticated user therefore listed every tenant's fleet. Proven, not inferred: a
probe seeded one vehicle in each of two orgs and org A's client saw both.

WHY IT SURVIVED. `test_route_auth_walk.py` checks that routes require authentication —
this one does. Authentication was never the problem; scoping was. And RLS-based tenant
tests cannot see it, because there is no policy on this table to exercise.

`vehicles.organization_id` is a `String(36)` rather than a UUID column, so the filter
compares against `str(org_id)`. Getting that wrong yields zero rows rather than an
error, which would look like "scoping works" — hence the assertion below that the
caller still sees its OWN vehicle.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def vehicles_in_two_orgs(admin_sync_url, seeded_orgs):
    """One active vehicle per org, seeded over a superuser connection."""
    import psycopg2

    vehicle_a, vehicle_b = uuid.uuid4(), uuid.uuid4()
    conn = psycopg2.connect(admin_sync_url)
    conn.autocommit = True
    with conn.cursor() as cur:
        for vid, org_key, number in (
            (vehicle_a, "org_a_id", "VEH-A"),
            (vehicle_b, "org_b_id", "VEH-B"),
        ):
            cur.execute(
                "INSERT INTO vehicles (id, organization_id, vehicle_number, is_active) "
                "VALUES (%s, %s, %s, true)",
                (str(vid), str(seeded_orgs[org_key]), number),
            )
    yield vehicle_a, vehicle_b
    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM vehicles WHERE id IN (%s, %s)", (str(vehicle_a), str(vehicle_b))
        )
    conn.close()


async def _vehicle_ids(client) -> set:
    response = await client.get("/api/v1/transportation/vehicles")
    assert response.status_code == 200, response.text
    return {v.get("id") for v in response.json()["items"]}


class TestTheListIsScopedToTheCaller:
    async def test_another_orgs_vehicle_is_not_returned(
        self, client_a, vehicles_in_two_orgs
    ):
        """THE ASSERTION THIS FILE EXISTS FOR. Before the fix this was org B's row,
        returned to org A."""
        _vehicle_a, vehicle_b = vehicles_in_two_orgs
        assert str(vehicle_b) not in await _vehicle_ids(client_a), (
            "org A listed org B's vehicle — the endpoint is not tenant-scoped"
        )

    async def test_the_caller_still_sees_its_own(self, client_a, vehicles_in_two_orgs):
        """Guards against the opposite failure. `vehicles.organization_id` is a
        String(36); comparing it to a UUID object matches nothing, which would empty
        the list and pass the isolation assertion above while breaking the page."""
        vehicle_a, _vehicle_b = vehicles_in_two_orgs
        assert str(vehicle_a) in await _vehicle_ids(client_a), (
            "the caller's own vehicle is missing — the filter is matching nothing"
        )

    async def test_each_org_sees_exactly_its_own(
        self, client_a, client_b, vehicles_in_two_orgs
    ):
        vehicle_a, vehicle_b = vehicles_in_two_orgs
        a_ids, b_ids = await _vehicle_ids(client_a), await _vehicle_ids(client_b)
        assert str(vehicle_a) in a_ids and str(vehicle_a) not in b_ids
        assert str(vehicle_b) in b_ids and str(vehicle_b) not in a_ids


class TestTheTableHasNoRlsToFallBackOn:
    """Records WHY this needed an application-layer fix, and fails if that stops
    being true — at which point the filter is defence in depth rather than the only
    defence, and this file's framing should be revisited."""

    async def test_vehicles_has_no_row_level_security(self, admin_sync_url):
        import psycopg2

        conn = psycopg2.connect(admin_sync_url)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT relrowsecurity FROM pg_class WHERE relname = 'vehicles'"
                )
                row = cur.fetchone()
        finally:
            conn.close()
        assert row is not None, "vehicles table missing"
        assert row[0] is False, (
            "vehicles now has RLS enabled — good, but this test's premise (that the "
            "explicit filter is the ONLY protection) no longer holds; check whether "
            "the sibling logistics tables were covered too"
        )

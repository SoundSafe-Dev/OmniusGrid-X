"""Transportation reads scope to the token, and actually return rows.

THE DEFECT, WHICH FAILED IN THE OPPOSITE DIRECTION TO ITS SIBLING. `get_carriers`,
`get_drivers`, `get_shipments`, `get_routes` and `geotab.get_fleet_summary` took
`organization_id` as a **required client-supplied query parameter** and ran on `get_db`.

That is the IDOR shape `app/core/tenant.py` forbids — but it never leaked, because
`carriers`, `drivers`, `shipments` and `routes` have ENABLE **and FORCE** row-level
security. `get_db` sets no tenant GUC, `NULLIF(current_setting(...), '')` is NULL, and
the policy matched nothing. So every one of these endpoints **returned an empty list to
every caller, including for its own organization**. Confirmed against a real database:
listing carriers with the caller's own `organization_id` returned zero rows while the
row sat in the table.

The sibling defect in the same file, `get_vehicles`, was the same wrong dependency
producing the exact opposite result — a live cross-tenant leak — because `vehicles` has
no policy. One mistake, two failure modes, decided only by whether the table happened to
carry RLS. Neither is visible to a test that only checks status codes.

These tests pin both directions: the endpoints return the caller's own rows (they did
not), and naming another organization in the query string changes nothing (it should
never have been readable in the first place).
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def carriers(admin_sync_url, seeded_orgs):
    """One active carrier per organization, seeded past RLS."""
    import psycopg2

    carrier_a, carrier_b = uuid.uuid4(), uuid.uuid4()
    conn = psycopg2.connect(admin_sync_url)
    conn.autocommit = True
    with conn.cursor() as cur:
        for cid, org_key, name in (
            (carrier_a, "org_a_id", "CARRIER-A"),
            (carrier_b, "org_b_id", "CARRIER-B"),
        ):
            cur.execute(
                "INSERT INTO carriers (id, organization_id, carrier_name, is_active) "
                "VALUES (%s, %s, %s, true)",
                (str(cid), str(seeded_orgs[org_key]), name),
            )
    yield carrier_a, carrier_b
    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM carriers WHERE id IN (%s, %s)", (str(carrier_a), str(carrier_b))
        )
    conn.close()


async def _ids(client, path: str) -> set:
    response = await client.get(path)
    assert response.status_code == 200, f"{path} -> {response.status_code}: {response.text[:200]}"
    payload = response.json()
    rows = payload["items"] if isinstance(payload, dict) and "items" in payload else payload
    return {row.get("id") for row in rows}


class TestTheEndpointsReturnAnythingAtAll:
    """The headline failure. FORCE RLS plus a missing GUC filtered every row, so
    these lists were empty for everyone — which reads as "no data yet", not as a bug."""

    @pytest.mark.parametrize(
        "path",
        [
            "/api/v1/transportation/carriers",
            "/api/v1/transportation/drivers",
            "/api/v1/transportation/shipments",
            "/api/v1/transportation/routes",
        ],
    )
    async def test_a_bare_call_succeeds(self, client_a, path):
        """It also used to be a 422: the parameter was required and the client did
        not always send it."""
        response = await client_a.get(path)
        assert response.status_code == 200, (
            f"{path} -> {response.status_code}: {response.text[:200]}"
        )

    async def test_the_callers_own_carrier_is_returned(self, client_a, carriers):
        carrier_a, _carrier_b = carriers
        assert str(carrier_a) in await _ids(client_a, "/api/v1/transportation/carriers"), (
            "the caller's own carrier is missing — the endpoint is still returning "
            "nothing, which is what FORCE RLS with no tenant GUC produces"
        )


class TestScopingComesFromTheToken:
    async def test_another_orgs_carrier_is_not_returned(self, client_a, carriers):
        _carrier_a, carrier_b = carriers
        assert str(carrier_b) not in await _ids(client_a, "/api/v1/transportation/carriers")

    async def test_each_org_sees_its_own(self, client_a, client_b, carriers):
        carrier_a, carrier_b = carriers
        a_ids = await _ids(client_a, "/api/v1/transportation/carriers")
        b_ids = await _ids(client_b, "/api/v1/transportation/carriers")
        assert str(carrier_a) in a_ids and str(carrier_a) not in b_ids
        assert str(carrier_b) in b_ids and str(carrier_b) not in a_ids

    async def test_naming_another_org_in_the_query_string_changes_nothing(
        self, client_a, carriers, seeded_orgs
    ):
        """The parameter is gone, so it is ignored. What matters is that a stale
        client sending it neither reaches another tenant's rows nor loses its own."""
        carrier_a, carrier_b = carriers
        ids = await _ids(
            client_a,
            f"/api/v1/transportation/carriers?organization_id={seeded_orgs['org_b_id']}",
        )
        assert str(carrier_b) not in ids, "a caller reached another org by naming it"
        assert str(carrier_a) in ids, "a stale client sending the old parameter was emptied out"


class TestFetchByIdIsScoped:
    async def test_another_orgs_carrier_is_404(self, client_a, carriers):
        _carrier_a, carrier_b = carriers
        response = await client_a.get(f"/api/v1/transportation/carriers/{carrier_b}")
        assert response.status_code == 404

    async def test_the_callers_own_carrier_is_reachable(self, client_a, carriers):
        """404-for-everything satisfies the assertion above and breaks the product —
        which is exactly what this endpoint did before, via RLS with no GUC."""
        carrier_a, _carrier_b = carriers
        response = await client_a.get(f"/api/v1/transportation/carriers/{carrier_a}")
        assert response.status_code == 200, response.text

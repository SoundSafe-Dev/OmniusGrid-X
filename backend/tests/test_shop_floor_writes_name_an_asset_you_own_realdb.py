"""A shop-floor write may only name an asset the caller can see (FS-724).

FOUND BY THE CONTRACT GATE, once it could finish. Of the 546 operations it drives, 36 answer
a 5xx under generated input, and most of those are dependency outages reported correctly —
Redis for the feature-flag store, an unreachable vector store, a broker that is not running.
Eight were not: they answered a bare `internal server error`. Three of the eight are here.

**Defect one, the loud half.** `asset_id` was a bare `str` on three write models, so any
value that is not a UUID reached Postgres and surfaced as a 500 where the contract promises
a 4xx:

    POST /shop-floor/downtime/start   {"asset_id": "nope"}   ->  500
    POST /shop-floor/part-issues      {"asset_id": "nope"}   ->  500
    POST /shop-floor/labor/clock-in   {"asset_id": "nope"}   ->  500

**Defect two, which the gate could not see and is worse.** Nothing checked WHOSE asset it
was. `downtime_events.asset_id` is a foreign key to `assets`, and a foreign-key check is
performed by the database at a level RLS does not filter — so a valid id belonging to another
organisation was accepted and **org B could log downtime against org A's machine and get a
201**. The row lands in org B's own tenancy, so this is not a read of someone else's data; it
is a write that references it. `/downtime/open` then returns an event whose asset the caller
cannot resolve, and downtime is an OEE input, so the figure it feeds is computed against a
machine the tenant does not own.

Both are closed by `_own_asset_id`, which types the id and proves the asset is visible on the
caller's own session — one statement, because RLS does the work once something asks.

WHY THIS IS THE THIRD FILE IN A ROW ABOUT THE SAME THING. `operations` had no organisation
column and four handlers that trusted a session which could not help them (FS-720). Here the
table is protected but the WRITE named a row across the boundary. Same question each time —
*what proves this id belongs to the caller* — and each time the answer had been "nothing, and
nobody would notice".
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio

pytestmark = pytest.mark.asyncio

SHOP_FLOOR = "/api/v1/shop-floor"

#: (path, body-without-asset). Every shop-floor write that names an asset.
WRITES = [
    (f"{SHOP_FLOOR}/downtime/start", {}),
    (f"{SHOP_FLOOR}/part-issues", {"part_number": "P-1", "quantity": 1}),
    (f"{SHOP_FLOOR}/labor/clock-in", {}),
]


def _conn(admin_sync_url):
    import psycopg2

    conn = psycopg2.connect(admin_sync_url)
    conn.autocommit = True
    return conn


@pytest_asyncio.fixture
async def org_a_asset(admin_sync_url, seeded_orgs):
    """A real asset belonging to org A, so 'another tenant's asset' means a row that
    genuinely exists rather than an id that resolves to nothing for everybody."""
    ids = {"type": uuid.uuid4(), "asset": uuid.uuid4()}
    conn = _conn(admin_sync_url)
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO asset_types (id, name, category) VALUES (%s, %s, 'machine')",
            (str(ids["type"]), f"FS724-{uuid.uuid4().hex[:8]}"),
        )
        cur.execute(
            "INSERT INTO assets (id, organization_id, asset_type_id, workcell_id, name, is_active) "
            "VALUES (%s, %s, %s, %s, 'FS724 Asset', true)",
            (
                str(ids["asset"]),
                str(seeded_orgs["org_a_id"]),
                str(ids["type"]),
                str(seeded_orgs["workcell_a_id"]),
            ),
        )
    yield ids["asset"]
    with conn.cursor() as cur:
        cur.execute("DELETE FROM downtime_events WHERE asset_id = %s", (str(ids["asset"]),))
        cur.execute("DELETE FROM part_issues WHERE asset_id = %s", (str(ids["asset"]),))
        cur.execute("DELETE FROM labor_entries WHERE asset_id = %s", (str(ids["asset"]),))
        cur.execute("DELETE FROM assets WHERE id = %s", (str(ids["asset"]),))
        cur.execute("DELETE FROM asset_types WHERE id = %s", (str(ids["type"]),))
    conn.close()


class TestRubbishIsRefusedRatherThanCrashing:
    """The contract promises a 4xx for input it cannot accept. A 500 is the server saying
    the request was fine and something else broke, which is a different sentence."""

    @pytest.mark.parametrize("path,body", WRITES, ids=[p.rsplit("/", 1)[-1] for p, _ in WRITES])
    async def test_a_non_uuid_asset_is_a_422(self, client_a, path, body):
        response = await client_a.post(path, json={**body, "asset_id": "not-a-uuid"})
        assert response.status_code == 422, (
            f"{path} answered {response.status_code} for a malformed asset id. A bare `str` "
            f"on the request model lets it reach Postgres, and asyncpg's DataError becomes "
            f"a 500."
        )


class TestAWriteCannotNameAnotherTenantsAsset:
    """The half the contract gate cannot reach: the id is well-formed and the row exists —
    it just is not yours."""

    @pytest.mark.parametrize("path,body", WRITES, ids=[p.rsplit("/", 1)[-1] for p, _ in WRITES])
    async def test_another_org_gets_404(self, client_b, org_a_asset, path, body):
        response = await client_b.post(path, json={**body, "asset_id": str(org_a_asset)})
        assert response.status_code == 404, (
            f"org B wrote to {path} naming org A's asset and got {response.status_code}. "
            f"The foreign key is checked below RLS, so the database accepts the reference; "
            f"only the handler can refuse it."
        )

    async def test_the_row_was_not_written(self, client_b, org_a_asset, admin_sync_url):
        """The status code is not the property — the absence of the row is. A handler could
        answer 404 after inserting."""
        await client_b.post(
            f"{SHOP_FLOOR}/downtime/start", json={"asset_id": str(org_a_asset)}
        )
        conn = _conn(admin_sync_url)
        with conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM downtime_events WHERE asset_id = %s",
                (str(org_a_asset),),
            )
            count = cur.fetchone()[0]
        conn.close()
        assert count == 0, "a downtime event was written against another tenant's asset"


class TestTheOwnerIsStillServed:
    """Every assertion above is satisfied by a route that refuses everybody. This is the
    denominator (rule 165)."""

    async def test_the_owner_can_start_downtime_on_their_own_asset(
        self, client_a, org_a_asset
    ):
        response = await client_a.post(
            f"{SHOP_FLOOR}/downtime/start", json={"asset_id": str(org_a_asset)}
        )
        assert response.status_code == 201, response.text[:300]
        assert response.json()["asset_id"] == str(org_a_asset)

    async def test_an_asset_free_write_still_works(self, client_a):
        """`asset_id` is optional on two of the three. Making it a UUID must not make it
        required — a part issued against no particular machine is a real thing."""
        response = await client_a.post(
            f"{SHOP_FLOOR}/part-issues", json={"part_number": "P-2", "quantity": 2}
        )
        assert response.status_code == 201, response.text[:300]

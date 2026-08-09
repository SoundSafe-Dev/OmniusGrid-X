"""`/maintenance/vehicles/{id}/history` returned any tenant's repair history.

The handler took no `org_id` and called no `_scope` — the only one in `fleet_logistics.py` that
did neither. It filtered `repair_orders` on `vehicle_id` and status alone and returned
`_history_out`: description, cost, vendor, and the technician's notes.

WHAT THIS TEST CAN AND CANNOT SHOW. On Postgres, migration 051's FORCEd policy filtered the rows
anyway, so the endpoint answered correctly here even while the handler was wrong — which is why
this file's assertion passes against the pre-fix code too, and why the guard that actually
caught it is a source check (`test_every_fleet_query_is_scoped.py`). The leak was on the SQLite
offline path, where no policy exists and the application filter is the only thing there.

So this file pins the OTHER half: that adding the filter did not break the endpoint for its
owner, and that the policy and the filter agree rather than one masking the other. Two layers
that disagree are worse than one, because whichever answers first decides.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

pytestmark = pytest.mark.asyncio

VEHICLE_ID = "veh-shared-id"


def _seed(admin_sync_url, org_id, *, title, cost):
    """A completed repair order on `VEHICLE_ID`, owned by `org_id`.

    The SAME vehicle id under both organisations on purpose: `repair_orders.vehicle_id` is a
    bare VARCHAR with no foreign key, so nothing stops two tenants from using one, and it is
    the only input this endpoint takes.
    """
    import psycopg2

    order_id = str(uuid.uuid4())
    conn = psycopg2.connect(admin_sync_url)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO repair_orders (id, organization_id, vehicle_id, title, status, "
                "cost, category, vendor, description, opened_at, completed_at) "
                "VALUES (%s, %s, %s, %s, 'completed', %s, 'brakes', %s, %s, %s, %s)",
                (order_id, org_id, VEHICLE_ID, title, cost, f"{title} Garage",
                 f"Notes for {title}", datetime.now(timezone.utc) - timedelta(days=2),
                 datetime.now(timezone.utc) - timedelta(days=1)),
            )
    finally:
        conn.close()
    return order_id


async def _history(client):
    resp = await client.get(f"/api/v1/maintenance/vehicles/{VEHICLE_ID}/history")
    assert resp.status_code == 200, resp.text
    return resp.json()


class TestTheHistoryBelongsToOneTenant:
    async def test_each_tenant_sees_only_its_own_repair_history(
        self, app, client_a, client_b, admin_sync_url, seeded_orgs
    ):
        """BOTH DIRECTIONS. Asserting only that B sees nothing passes just as well when the
        endpoint is broken for everyone — the mistake this suite has made before."""
        _seed(admin_sync_url, str(seeded_orgs["org_a_id"]), title="Alpha", cost=100)
        _seed(admin_sync_url, str(seeded_orgs["org_b_id"]), title="Bravo", cost=200)

        a_descriptions = {row["description"] for row in await _history(client_a)}
        b_descriptions = {row["description"] for row in await _history(client_b)}

        assert a_descriptions == {"Alpha"}
        assert b_descriptions == {"Bravo"}

    async def test_the_payload_fields_still_arrive(
        self, app, client_a, admin_sync_url, seeded_orgs
    ):
        """The control on the scoping: a filter that matched nothing would satisfy "B sees no
        A rows" perfectly. `_history_out` carries the fields the panel reads."""
        _seed(admin_sync_url, str(seeded_orgs["org_a_id"]), title="Alpha", cost=100)

        [row] = await _history(client_a)

        assert row["vehicleId"] == VEHICLE_ID
        assert row["cost"] == 100
        assert row["technician"] == "Alpha Garage"
        assert row["notes"] == "Notes for Alpha"
        assert row["serviceDate"] is not None

    async def test_an_incomplete_repair_is_not_history(
        self, app, client_a, admin_sync_url, seeded_orgs
    ):
        """The status predicate has to survive being wrapped in `_scope`, which rebuilds the
        query — an easy thing to drop when moving a `.where()` inside another call."""
        import psycopg2

        _seed(admin_sync_url, str(seeded_orgs["org_a_id"]), title="Alpha", cost=100)
        conn = psycopg2.connect(admin_sync_url)
        conn.autocommit = True
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO repair_orders (id, organization_id, vehicle_id, title, "
                    "status, opened_at) VALUES (%s, %s, %s, 'In progress', 'in_progress', %s)",
                    (str(uuid.uuid4()), str(seeded_orgs["org_a_id"]), VEHICLE_ID,
                     datetime.now(timezone.utc)),
                )
        finally:
            conn.close()

        descriptions = {row["description"] for row in await _history(client_a)}
        assert descriptions == {"Alpha"}

    async def test_the_ordering_survives_the_wrapping(
        self, app, client_a, admin_sync_url, seeded_orgs
    ):
        """`.order_by()` moved from the `select()` to the outside of `_scope()`. Newest first
        is what "history" means here, and a silently reversed list is the kind of thing that
        looks fine until somebody reads the top row as the latest service."""
        import psycopg2

        org_a = str(seeded_orgs["org_a_id"])
        conn = psycopg2.connect(admin_sync_url)
        conn.autocommit = True
        try:
            with conn.cursor() as cur:
                for title, days in (("Older", 30), ("Newer", 1)):
                    cur.execute(
                        "INSERT INTO repair_orders (id, organization_id, vehicle_id, title, "
                        "status, opened_at, completed_at) "
                        "VALUES (%s, %s, %s, %s, 'completed', %s, %s)",
                        (str(uuid.uuid4()), org_a, VEHICLE_ID, title,
                         datetime.now(timezone.utc) - timedelta(days=days + 1),
                         datetime.now(timezone.utc) - timedelta(days=days)),
                    )
        finally:
            conn.close()

        descriptions = [row["description"] for row in await _history(client_a)]
        assert descriptions == ["Newer", "Older"]

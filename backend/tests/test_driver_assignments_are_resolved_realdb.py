"""The driver panel's "Current Vehicle" and "Current Shipment" rows never rendered.

`Driver.currentVehicleId` and `Driver.currentShipmentId` are declared by the client, read by
`TransportationManagement`, and were produced by nothing — both rows are conditional, so they
were simply always absent.

WHY THE SWEEP FOUND THEM AND A SCHEMA COMPARISON WOULD NOT HAVE. Neither is a column on
`drivers`, and neither should be: a vehicle names its driver (`vehicles.current_driver_id`) and
a shipment names its driver (`shipments.driver_id`). The driver's side of both associations is a
reverse lookup. Comparing the table to the type reports "no such column" for a field that is
perfectly derivable — the answer here is the third of the sweep's three options, make the server
send it, not the first.

WHAT THIS FILE PINS beyond presence:

  * the assignment is the CURRENT one — a delivered shipment is not what the driver is on now,
    and without that filter the panel names whichever historical load the query returned first;
  * one driver's assignment does not leak onto another's row, which a `setdefault` on a shared
    dict makes easy to get wrong;
  * it stays batched. Two queries for the page, not two per driver, on the endpoint that backs
    the fleet list.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

pytestmark = pytest.mark.asyncio


def _seed(admin_sync_url, org_id):
    """Two drivers. One has a vehicle and an active shipment plus a delivered one; the other
    has nothing. Returns the ids the assertions need."""
    import psycopg2

    ids = {
        "driver_assigned": str(uuid.uuid4()),
        "driver_idle": str(uuid.uuid4()),
        "vehicle": str(uuid.uuid4()),
        "shipment_active": str(uuid.uuid4()),
        "shipment_delivered": str(uuid.uuid4()),
        "carrier": str(uuid.uuid4()),
    }
    now = datetime.now(timezone.utc)

    conn = psycopg2.connect(admin_sync_url)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO carriers (id, organization_id, carrier_name) VALUES (%s, %s, %s)",
                (ids["carrier"], org_id, "Test Carrier"),
            )
            for key, first in (("driver_assigned", "Assigned"), ("driver_idle", "Idle")):
                cur.execute(
                    "INSERT INTO drivers (id, organization_id, carrier_id, first_name, "
                    "last_name, license_number, is_active) "
                    "VALUES (%s, %s, %s, %s, 'Driver', %s, true)",
                    (ids[key], org_id, ids["carrier"], first, f"LIC-{first}"),
                )
            cur.execute(
                "INSERT INTO vehicles (id, organization_id, vehicle_number, current_driver_id) "
                "VALUES (%s, %s, 'TRK-ASSIGNED', %s)",
                (ids["vehicle"], org_id, ids["driver_assigned"]),
            )
            # THE DELIVERED LOAD IS THE MORE RECENT ONE, deliberately. With it older, the
            # `order_by(scheduled_pickup.desc())` put the active shipment first and
            # `setdefault` kept it — so the test passed with the status filter DELETED, and
            # proved only that the ordering happened to agree. Now nothing but the filter can
            # exclude it.
            for key, status, pickup in (
                ("shipment_active", "in_transit", now - timedelta(days=9)),
                ("shipment_delivered", "delivered", now - timedelta(days=1)),
            ):
                cur.execute(
                    "INSERT INTO shipments (id, organization_id, carrier_id, driver_id, "
                    "shipment_number, status, scheduled_pickup) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                    (ids[key], org_id, ids["carrier"], ids["driver_assigned"],
                     f"SHP-{key}", status, pickup),
                )
    finally:
        conn.close()
    return ids


async def _drivers_by_id(client):
    resp = await client.get("/api/v1/transportation/drivers")
    assert resp.status_code == 200, resp.text
    return {row["id"]: row for row in resp.json()}


class TestTheDriverCarriesItsAssignments:
    async def test_the_assigned_driver_names_its_vehicle_and_shipment(
        self, app, client_a, admin_sync_url, seeded_orgs
    ):
        """THE ASSERTION THIS FILE EXISTS FOR. Both rows were conditional and both fields were
        undefined on every response, so the panel showed neither."""
        ids = _seed(admin_sync_url, str(seeded_orgs["org_a_id"]))
        rows = await _drivers_by_id(client_a)

        assigned = rows[ids["driver_assigned"]]
        assert assigned["currentVehicleId"] == ids["vehicle"]
        assert assigned["currentShipmentId"] == ids["shipment_active"], (
            "the driver was given a delivered load; a shipment that has been handed over is "
            "not what they are on now"
        )

    async def test_an_unassigned_driver_carries_neither(
        self, app, client_a, admin_sync_url, seeded_orgs
    ):
        """The control on the leak below AND on the fields being real: `None` here rather than
        another driver's vehicle, and the key present rather than the whole feature absent."""
        ids = _seed(admin_sync_url, str(seeded_orgs["org_a_id"]))
        rows = await _drivers_by_id(client_a)

        idle = rows[ids["driver_idle"]]
        assert "currentVehicleId" in idle, "the field is not being emitted at all"
        assert idle["currentVehicleId"] is None
        assert idle["currentShipmentId"] is None

    async def test_the_hos_figures_still_come_through(
        self, app, client_a, admin_sync_url, seeded_orgs
    ):
        """Adding two keys to this row must not disturb the derivation beside them — the HOS
        remaining hours, which are computed here because the stored columns are always NULL and
        a missing value on that tab reads as 'no violations' for DOT-regulated hours."""
        ids = _seed(admin_sync_url, str(seeded_orgs["org_a_id"]))
        rows = await _drivers_by_id(client_a)

        assigned = rows[ids["driver_assigned"]]
        assert "hosDriveHoursRemaining" in assigned
        assert "hosDutyHoursRemaining" in assigned


class TestItStaysBatched:
    async def test_the_page_does_not_query_per_driver(
        self, app, client_a, admin_sync_url, seeded_orgs
    ):
        """Two reverse lookups are the easiest N+1 in this file to write by accident, and this
        endpoint backs the fleet list. The count is asserted against the number of SELECTs the
        request issues, not against a timing.

        Listening on the `Engine` CLASS, not on `app.db.database.engine`: conftest builds its
        own engine for the test container, so a listener attached to the module global records
        nothing and `len([]) <= N` passes for any implementation whatsoever.
        """
        from sqlalchemy import event
        from sqlalchemy.engine import Engine

        _seed(admin_sync_url, str(seeded_orgs["org_a_id"]))

        statements: list[str] = []

        def _record(conn, cursor, statement, parameters, context, executemany):
            if statement.lstrip().upper().startswith("SELECT"):
                statements.append(statement)

        event.listen(Engine, "before_cursor_execute", _record)
        try:
            await client_a.get("/api/v1/transportation/drivers")
        finally:
            event.remove(Engine, "before_cursor_execute", _record)

        assert statements, "nothing was recorded, so this guard is inspecting nothing"

        # `in "... FROM vehicles ..."` WITH A LEADING SPACE MATCHED NOTHING. SQLAlchemy renders
        # the clause at the start of a line, so `FROM` is preceded by a newline — every count
        # here was 0, and `0 <= 1` is true for any implementation including one query per row.
        # The bound is EXACT for the same reason: an upper bound is satisfied by zero, which is
        # indistinguishable from a matcher that matches nothing.
        vehicle_reads = [s for s in statements if "FROM vehicles" in s]
        shipment_reads = [s for s in statements if "FROM shipments" in s]
        assert len(vehicle_reads) == 1, (
            f"expected exactly one query against vehicles for a page of drivers, saw "
            f"{len(vehicle_reads)}"
        )
        assert len(shipment_reads) == 1, (
            f"expected exactly one query against shipments for a page of drivers, saw "
            f"{len(shipment_reads)}"
        )


class TestTheLookupIsTenantScoped:
    async def test_another_tenants_vehicle_is_not_claimed(
        self, app, client_a, client_b, admin_sync_url, seeded_orgs
    ):
        """The reverse lookups run on the tenant session, so org B's list must not resolve org
        A's vehicle even though the driver ids are unique platform-wide."""
        ids = _seed(admin_sync_url, str(seeded_orgs["org_a_id"]))
        rows_b = await _drivers_by_id(client_b)
        assert ids["driver_assigned"] not in rows_b

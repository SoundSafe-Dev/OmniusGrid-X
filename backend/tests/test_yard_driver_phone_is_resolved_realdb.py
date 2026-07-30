"""The number an operator calls about a trailer sitting on the yard was never sent.

`YardTrailer.driverPhone` and `DockAppointment.driverPhone` are declared by the client and
rendered in three places — the trailer card, the trailer detail panel, and the appointment row.
Nothing produced either. Both are conditional, so the line was simply always absent.

Both are joins, not missing columns: `yard_trailers.driver_id` and
`dock_appointments.driver_id` reference `drivers`, and `drivers.phone` is where the number
lives. The same shape as `trailerLicensePlate`, resolved in this same file one finding earlier
— and the reason a table-versus-type comparison does not find these: the column exists, on the
other table.

WHAT THIS PINS beyond presence: that a driver with no number recorded yields `None` rather than
an empty string (the panel omits the line on null and would render a blank one on `""`), and
that the resolution stays batched, which is the easiest thing to lose in a list endpoint.
"""

from __future__ import annotations

import uuid

import pytest

pytestmark = pytest.mark.asyncio

PHONE = "+1-555-0142"


def _seed(admin_sync_url, org_id):
    """One driver with a phone, one without, and a trailer plus an appointment for each."""
    import psycopg2

    ids = {k: str(uuid.uuid4()) for k in (
        "carrier", "driver_with_phone", "driver_no_phone",
        "trailer_with", "trailer_without", "trailer_no_driver",
        "door", "appt_with", "appt_without",
    )}

    conn = psycopg2.connect(admin_sync_url)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO carriers (id, organization_id, carrier_name) VALUES (%s, %s, %s)",
                (ids["carrier"], org_id, "Yard Carrier"),
            )
            for key, phone in (("driver_with_phone", PHONE), ("driver_no_phone", None)):
                cur.execute(
                    "INSERT INTO drivers (id, organization_id, carrier_id, first_name, "
                    "last_name, license_number, phone, is_active) "
                    "VALUES (%s, %s, %s, 'Yard', 'Driver', %s, %s, true)",
                    (ids[key], org_id, ids["carrier"], f"LIC-{key}", phone),
                )
            for key, driver in (
                ("trailer_with", ids["driver_with_phone"]),
                ("trailer_without", ids["driver_no_phone"]),
                ("trailer_no_driver", None),
            ):
                cur.execute(
                    "INSERT INTO yard_trailers (id, organization_id, trailer_number, "
                    "carrier_id, status, driver_id) "
                    "VALUES (%s, %s, %s, %s, 'checked_in', %s)",
                    (ids[key], org_id, f"TRL-{key}", ids["carrier"], driver),
                )
            cur.execute(
                "INSERT INTO dock_doors (id, organization_id, door_number, status, is_active) "
                "VALUES (%s, %s, 'D-1', 'available', true)",
                (ids["door"], org_id),
            )
            for key, driver in (
                ("appt_with", ids["driver_with_phone"]),
                ("appt_without", ids["driver_no_phone"]),
            ):
                cur.execute(
                    "INSERT INTO dock_appointments (id, organization_id, dock_door_id, "
                    "trailer_id, carrier_id, driver_id, appointment_type, status, "
                    "scheduled_start, scheduled_end) "
                    "VALUES (%s, %s, %s, %s, %s, %s, 'inbound', 'scheduled', "
                    "now(), now() + interval '1 hour')",
                    (ids[key], org_id, ids["door"], ids["trailer_with"], ids["carrier"], driver),
                )
    finally:
        conn.close()
    return ids


class TestTheTrailerCarriesItsDriversNumber:
    async def test_the_phone_is_resolved_through_the_driver(
        self, app, client_a, admin_sync_url, seeded_orgs
    ):
        """THE ASSERTION THIS FILE EXISTS FOR."""
        ids = _seed(admin_sync_url, str(seeded_orgs["org_a_id"]))
        resp = await client_a.get("/api/v1/yard/trailers")
        assert resp.status_code == 200, resp.text
        rows = {r["id"]: r for r in resp.json()["items"]}

        assert rows[ids["trailer_with"]]["driverPhone"] == PHONE

    async def test_a_driver_with_no_number_is_null_not_blank(
        self, app, client_a, admin_sync_url, seeded_orgs
    ):
        """`drivers.phone` is nullable. The panel omits the line on null and would render an
        empty one on `""` — a trailer whose driver is reachable at no number."""
        ids = _seed(admin_sync_url, str(seeded_orgs["org_a_id"]))
        rows = {r["id"]: r for r in (await client_a.get("/api/v1/yard/trailers")).json()["items"]}

        assert rows[ids["trailer_without"]]["driverPhone"] is None

    async def test_a_trailer_with_no_driver_is_null(
        self, app, client_a, admin_sync_url, seeded_orgs
    ):
        """`driver_id` is nullable too — a trailer dropped in the yard has nobody with it. The
        lookup must not resolve `None` to some other driver's number."""
        ids = _seed(admin_sync_url, str(seeded_orgs["org_a_id"]))
        rows = {r["id"]: r for r in (await client_a.get("/api/v1/yard/trailers")).json()["items"]}

        assert "driverPhone" in rows[ids["trailer_no_driver"]]
        assert rows[ids["trailer_no_driver"]]["driverPhone"] is None

    async def test_the_plate_join_beside_it_still_works(
        self, app, client_a, admin_sync_url, seeded_orgs
    ):
        """Two resolvers now run over the same list. The one that was already there is the
        control: adding a join must not disturb it."""
        ids = _seed(admin_sync_url, str(seeded_orgs["org_a_id"]))
        rows = {r["id"]: r for r in (await client_a.get("/api/v1/yard/trailers")).json()["items"]}
        assert "carrierName" in rows[ids["trailer_with"]]
        assert rows[ids["trailer_with"]]["carrierName"] == "Yard Carrier"


class TestTheAppointmentCarriesItToo:
    async def test_the_appointment_row_gets_the_phone(
        self, app, client_a, admin_sync_url, seeded_orgs
    ):
        ids = _seed(admin_sync_url, str(seeded_orgs["org_a_id"]))
        resp = await client_a.get("/api/v1/yard/dock/appointments")
        assert resp.status_code == 200, resp.text
        rows = {r["id"]: r for r in resp.json()}

        assert rows[ids["appt_with"]]["driverPhone"] == PHONE
        assert rows[ids["appt_without"]]["driverPhone"] is None

    async def test_the_trailer_plate_is_still_resolved(
        self, app, client_a, admin_sync_url, seeded_orgs
    ):
        ids = _seed(admin_sync_url, str(seeded_orgs["org_a_id"]))
        rows = {r["id"]: r for r in (await client_a.get("/api/v1/yard/dock/appointments")).json()}
        assert "trailerLicensePlate" in rows[ids["appt_with"]] or (
            "trailer_license_plate" in rows[ids["appt_with"]]
        )


class TestItStaysBatched:
    async def test_one_query_against_drivers_per_page(
        self, app, client_a, admin_sync_url, seeded_orgs
    ):
        """EXACT, not an upper bound. `<= 1` is satisfied by zero, which is indistinguishable
        from a matcher that matches nothing — rule 51, learned from the driver-assignment guard
        in this same batch, which passed against a one-query-per-row mutation for exactly that
        reason.

        Listening on the `Engine` CLASS: conftest builds its own engine, so a listener on the
        module global records nothing.
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
            await client_a.get("/api/v1/yard/trailers")
        finally:
            event.remove(Engine, "before_cursor_execute", _record)

        driver_reads = [s for s in statements if "FROM drivers" in s]
        assert len(driver_reads) == 1, (
            f"expected exactly one query against drivers for a page of trailers, saw "
            f"{len(driver_reads)}"
        )


class TestTheJoinIsTenantScoped:
    async def test_another_tenant_sees_none_of_it(
        self, app, client_a, client_b, admin_sync_url, seeded_orgs
    ):
        ids = _seed(admin_sync_url, str(seeded_orgs["org_a_id"]))
        rows_b = {r["id"] for r in (await client_b.get("/api/v1/yard/trailers")).json()["items"]}
        assert ids["trailer_with"] not in rows_b

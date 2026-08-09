"""Every geofence alert displayed as "Violation", including routine authorised entries.

`GET /geofencing/alerts` emitted `zoneId`, `eventType` and `createdAt`. The TypeScript
`GeofenceAlert` declares `geofenceId`, `alertType` and `timestamp` — and **nothing in the
frontend reads the three names that were being sent**. The wire and the contract had drifted
apart with no overlap on the fields that matter.

`alertType` is the damaging one. `GeofencingPanel` renders

    alert.alertType === 'entry' ? 'Entered'
      : alert.alertType === 'exit' ? 'Exited'
      : 'Violation'

An undefined field matches neither branch, so the final one fires — and the final one is an
assertion. Every alert in the list read **"Violation"**, whether the vehicle had entered an
authorised zone, left one, or actually breached a boundary. A falsy ternary branch that
states something, which is the shape this codebase has now been wrong about six times.

`geofenceName` and `vehicleNumber` were undefined too, so the row could not say which zone
or which vehicle. Both live on other tables, referenced by id, and are fetched here in two
batched queries — an N+1 behind an alert list would be a performance defect introduced while
fixing a correctness one.

WHY THE NAMES CHANGED SERVER-SIDE RATHER THAN IN THE CLIENT. Nothing consumed `zoneId` or
`eventType`, so there was no second reader to keep happy, and the TypeScript interface is
the contract the only consumer was written against. Renaming the producer is the smaller
change and leaves one name per concept instead of two.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
import pytest_asyncio

pytestmark = pytest.mark.asyncio

ALERTS = "/api/v1/geofencing/alerts"


@pytest_asyncio.fixture
async def alerts(admin_sync_url, seeded_orgs):
    """A zone, a vehicle, and one alert of each event type against them."""
    import psycopg2

    conn = psycopg2.connect(admin_sync_url)
    conn.autocommit = True
    org = str(seeded_orgs["org_a_id"])
    zone_id, vehicle_id = uuid4(), uuid4()
    entry_id, exit_id, orphan_id = uuid4(), uuid4(), uuid4()
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO geofence_zones (id, organization_id, name, zone_type, is_active) "
            "VALUES (%s, %s, 'North Yard', 'circle', true)",
            (str(zone_id), org),
        )
        cur.execute(
            "INSERT INTO vehicles (id, organization_id, vehicle_number) "
            "VALUES (%s, %s, 'TRK-7781')",
            (str(vehicle_id), org),
        )
        for alert_id, event in ((entry_id, "entry"), (exit_id, "exit")):
            cur.execute(
                "INSERT INTO geofence_alerts (id, organization_id, zone_id, vehicle_id, "
                "event_type, severity) VALUES (%s, %s, %s, %s, %s, 'warning')",
                (str(alert_id), org, str(zone_id), str(vehicle_id), event),
            )
        # An alert whose zone and vehicle cannot be resolved — a deleted zone, or a row
        # written by an integration that referenced something outside this org.
        cur.execute(
            "INSERT INTO geofence_alerts (id, organization_id, zone_id, vehicle_id, "
            "event_type, severity) VALUES (%s, %s, %s, %s, 'entry', 'warning')",
            (str(orphan_id), org, str(uuid4()), str(uuid4())),
        )
    yield {"zone": zone_id, "vehicle": vehicle_id,
           "entry": entry_id, "exit": exit_id, "orphan": orphan_id}
    with conn.cursor() as cur:
        cur.execute("DELETE FROM geofence_alerts WHERE id = ANY(%s::uuid[])",
                    ([str(entry_id), str(exit_id), str(orphan_id)],))
        cur.execute("DELETE FROM vehicles WHERE id = %s", (str(vehicle_id),))
        cur.execute("DELETE FROM geofence_zones WHERE id = %s", (str(zone_id),))
    conn.close()


async def _one(client, alert_id):
    response = await client.get(ALERTS, params={"limit": 500})
    assert response.status_code == 200, response.text
    match = [a for a in response.json() if a["id"] == str(alert_id)]
    assert match, f"alert {alert_id} is missing from its own org's list"
    return match[0]


class TestTheNamesTheClientReads:
    async def test_the_event_type_arrives_as_alert_type(self, client_a, alerts):
        """THE ASSERTION THIS FILE EXISTS FOR. Sent as `eventType`, read as `alertType`,
        so the panel's ternary fell through to "Violation" for every alert."""
        alert = await _one(client_a, alerts["entry"])
        assert alert["alertType"] == "entry", (
            "the field the panel switches on is still missing or misnamed; every alert "
            "will render as a violation"
        )

    async def test_an_exit_is_distinguishable_from_an_entry(self, client_a, alerts):
        """One value proves a key exists; two prove it carries the row's actual state."""
        alert = await _one(client_a, alerts["exit"])
        assert alert["alertType"] == "exit"

    async def test_the_zone_is_identified_by_the_name_the_client_uses(
        self, client_a, alerts
    ):
        alert = await _one(client_a, alerts["entry"])
        assert alert["geofenceId"] == str(alerts["zone"])

    async def test_the_timestamp_is_called_timestamp(self, client_a, alerts):
        alert = await _one(client_a, alerts["entry"])
        assert alert["timestamp"] is not None


class TestTheDenormalisedFields:
    async def test_the_zone_name_is_resolved(self, client_a, alerts):
        """The row references the zone by id; without the join the panel cannot say which
        zone the vehicle entered, which is most of the information in an alert."""
        alert = await _one(client_a, alerts["entry"])
        assert alert["geofenceName"] == "North Yard"

    async def test_the_vehicle_number_is_resolved(self, client_a, alerts):
        alert = await _one(client_a, alerts["entry"])
        assert alert["vehicleNumber"] == "TRK-7781"

    async def test_an_unresolvable_zone_is_null_not_empty(self, client_a, alerts):
        """NULL means "could not resolve"; "" would read as a zone with no name. The panel
        renders the two differently and only one of them is true."""
        alert = await _one(client_a, alerts["orphan"])
        assert alert["geofenceName"] is None
        assert alert["vehicleNumber"] is None

    async def test_the_alert_is_still_listed_when_its_zone_is_gone(
        self, client_a, alerts
    ):
        """An inner join would have dropped it. An alert nobody can see is worse than one
        missing a zone name — it happened, and the row is the only record of it."""
        alert = await _one(client_a, alerts["orphan"])
        assert alert["alertType"] == "entry"


class TestANonUuidReferenceDoesNotBreakTheList:
    """`zone_id` and `vehicle_id` are `String(36)`; the tables they point at have UUID
    primary keys. Batching the lookups introduced a 500 for any alert whose reference is
    not a UUID — `DataError: invalid UUID` — and integrations do write device identifiers
    there. Caught by the existing tenant-isolation suite, which seeds `'VEH-a'`; pinned
    here so the next person to touch the join sees why the filter exists."""

    async def test_the_list_survives_a_non_uuid_vehicle_reference(
        self, client_a, admin_sync_url, seeded_orgs, alerts
    ):
        import psycopg2

        conn = psycopg2.connect(admin_sync_url)
        conn.autocommit = True
        odd_id = uuid4()
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO geofence_alerts (id, organization_id, zone_id, vehicle_id, "
                "event_type, severity) VALUES (%s, %s, 'ZONE-XYZ', 'VEH-a', 'exit', 'info')",
                (str(odd_id), str(seeded_orgs["org_a_id"])),
            )
        try:
            response = await client_a.get(ALERTS, params={"limit": 500})
            assert response.status_code == 200, response.text
            match = [a for a in response.json() if a["id"] == str(odd_id)]
            assert match, "the alert with a non-UUID reference was dropped from the list"
            # It still carries everything the row itself knows.
            assert match[0]["alertType"] == "exit"
            assert match[0]["geofenceId"] == "ZONE-XYZ"
            # And nothing is invented for what could not be resolved.
            assert match[0]["geofenceName"] is None
            assert match[0]["vehicleNumber"] is None
        finally:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM geofence_alerts WHERE id = %s", (str(odd_id),))
            conn.close()


class TestItDoesNotBecomeAnNPlusOne:
    async def test_the_joins_are_batched(self, client_a, alerts):
        """Resolving names per row would put two queries behind every alert in a list that
        defaults to 100. Asserted by counting the statements the endpoint issues, because
        the fix for a correctness defect must not introduce a performance one."""
        from sqlalchemy import event
        from sqlalchemy.engine import Engine

        statements: list[str] = []

        def record(conn, cursor, statement, parameters, context, executemany):
            if statement.lstrip().upper().startswith("SELECT"):
                statements.append(statement)

        # ON THE `Engine` CLASS, not on `app.db.database.engine`. The first version listened
        # to the module-level engine, and `conftest` builds its OWN `test_engine` and
        # rebinds every module's `AsyncSessionLocal` to it — so nothing was ever recorded,
        # `statements` stayed empty, and `len([]) <= 1` passed for any implementation. A
        # deliberate per-row-query mutation did not fail this test, which is how it was
        # found. Class-level registration catches every instance, including one created
        # after this line runs.
        event.listen(Engine, "before_cursor_execute", record)
        try:
            await client_a.get(ALERTS, params={"limit": 500})
        finally:
            event.remove(Engine, "before_cursor_execute", record)

        assert statements, (
            "no SELECT was recorded at all, so the counts below are vacuous — the "
            "listener is attached to an engine this request does not use"
        )

        zone_queries = [s for s in statements if "geofence_zones" in s]
        vehicle_queries = [s for s in statements if "vehicles" in s]
        assert len(zone_queries) <= 1, f"{len(zone_queries)} zone queries — one per alert?"
        assert len(vehicle_queries) <= 1, (
            f"{len(vehicle_queries)} vehicle queries — one per alert?"
        )

"""A dock door could not say which trailer was at it.

`YardManagement` renders `door.trailerLicensePlate` as bare text on the dock-door card, and
`appt.trailerLicensePlate || appt.trailerId || '-'` on the appointment row. Neither was ever
sent. `dock_doors.current_trailer_id` and `dock_appointments.trailer_id` both reference
`yard_trailers`, and the plate lives there — so the door card printed an empty line exactly
where the trailer occupying the dock should be identified.

Found by triaging the wire-vocabulary baseline **table-aware**: does the entity's own table
have a column that could feed this field, or a reference to one that does? That question
splits the remaining entries into the three fixes they actually need — rename the producer,
expose what exists, or delete the field. This one is the second kind.

`workcellName` on the same two types is the third kind and was DELETED rather than resolved:
`dock_doors` has no workcell relationship of any sort, so there is nothing to join. The card
was rendering a blank line for an association that does not exist in this schema.

THE RESPONSE MODEL NEARLY ATE THE FIX. `GET /yard/dock/doors` declares
`response_model=List[DockDoorResponse]`, and FastAPI drops whatever the schema does not
name — so resolving the plate in the handler without declaring it on the schema would have
deleted it from every response and changed nothing visible. That is the same trap that hid
`maintenance_mode` on `AssetResponse`, hit twice in one session.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
import pytest_asyncio

pytestmark = pytest.mark.asyncio

DOORS = "/api/v1/yard/dock/doors"
APPOINTMENTS = "/api/v1/yard/dock/appointments"


@pytest_asyncio.fixture
async def yard(admin_sync_url, seeded_orgs):
    """A trailer with a plate, a door holding it, and an appointment for it — plus a door
    holding nothing, which is the case that must not invent a plate."""
    import psycopg2

    conn = psycopg2.connect(admin_sync_url)
    conn.autocommit = True
    org = str(seeded_orgs["org_a_id"])
    trailer_id, door_id, empty_door_id, appt_id = uuid4(), uuid4(), uuid4(), uuid4()
    start = datetime.now(timezone.utc) + timedelta(hours=1)
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO yard_trailers (id, organization_id, trailer_number, "
            "license_plate, status) VALUES (%s, %s, 'TR-9001', 'PLT-4417', 'in_yard')",
            (str(trailer_id), org),
        )
        cur.execute(
            "INSERT INTO dock_doors (id, organization_id, door_number, door_type, status, "
            "current_trailer_id, is_active) "
            "VALUES (%s, %s, 'D-1', 'inbound', 'occupied', %s, true)",
            (str(door_id), org, str(trailer_id)),
        )
        cur.execute(
            "INSERT INTO dock_doors (id, organization_id, door_number, door_type, status, "
            "is_active) VALUES (%s, %s, 'D-2', 'inbound', 'available', true)",
            (str(empty_door_id), org),
        )
        cur.execute(
            "INSERT INTO dock_appointments (id, organization_id, dock_door_id, trailer_id, "
            "appointment_type, scheduled_start, scheduled_end, status) "
            "VALUES (%s, %s, %s, %s, 'delivery', %s, %s, 'scheduled')",
            (str(appt_id), org, str(door_id), str(trailer_id),
             start, start + timedelta(hours=1)),
        )
    yield {"trailer": trailer_id, "door": door_id,
           "empty_door": empty_door_id, "appointment": appt_id, "start": start}
    with conn.cursor() as cur:
        cur.execute("DELETE FROM dock_appointments WHERE id = %s", (str(appt_id),))
        cur.execute("DELETE FROM dock_doors WHERE id = ANY(%s::uuid[])",
                    ([str(door_id), str(empty_door_id)],))
        cur.execute("DELETE FROM yard_trailers WHERE id = %s", (str(trailer_id),))
    conn.close()


async def _door(client, door_id):
    response = await client.get(DOORS)
    assert response.status_code == 200, response.text
    match = [d for d in response.json() if d["id"] == str(door_id)]
    assert match, f"door {door_id} is missing from its own org's list"
    return match[0]


class TestTheDoorNamesItsTrailer:
    async def test_the_plate_is_resolved(self, client_a, yard):
        """THE ASSERTION THIS FILE EXISTS FOR. The card printed an empty line here."""
        door = await _door(client_a, yard["door"])
        assert door.get("trailer_license_plate") == "PLT-4417", (
            "the dock door still cannot say which trailer is at it; the response model "
            "may be dropping the field"
        )

    async def test_an_empty_door_reports_no_plate(self, client_a, yard):
        """The control, and a real property: a door holding nothing must not borrow a
        plate from another row, and must not report an empty string either."""
        door = await _door(client_a, yard["empty_door"])
        assert door.get("trailer_license_plate") is None

    async def test_the_field_survives_the_response_model(self, client_a, yard):
        """Pinned separately from the value. `response_model=List[DockDoorResponse]` drops
        anything the schema does not declare, so a correct handler with an undeclared
        field is indistinguishable from a handler that never resolved it."""
        from app.models.schemas import DockDoorResponse

        assert "trailer_license_plate" in DockDoorResponse.model_fields


class TestTheAppointmentNamesItsTrailer:
    async def test_the_plate_is_resolved(self, client_a, yard):
        response = await client_a.get(
            APPOINTMENTS,
            params={"start_date": (yard["start"] - timedelta(hours=2)).isoformat()},
        )
        assert response.status_code == 200, response.text
        match = [a for a in response.json() if a["id"] == str(yard["appointment"])]
        assert match, "the appointment is missing from its own org's schedule"
        assert match[0].get("trailer_license_plate") == "PLT-4417"


class TestTheDoorCarriesOnlyWhatItHas:
    """The per-interface audit rule 34 says the global sweep cannot do.

    `DockDoor` declared `supportedEquipment: string[]`, `hasLoadingEquipment`,
    `maxWeightCapacity`, `currentAppointmentId` and `estimatedReleaseAt`. `dock_doors`
    carries door_number, door_type, status, equipment_capabilities (a JSON OBJECT, not a
    list), current_trailer_id, last_occupied_at and is_active — and nothing else. None of the
    five was ever reported by the wire-vocabulary sweep, because its vocabulary is global: a
    name that exists as a column on ANY table passes.

    `estimatedReleaseAt` was the one that rendered — "Release: HH:MM", a prediction nothing
    produces, so the line never appeared. `last_occupied_at` exists and means something
    different (when the door was last occupied, a fact about the past); mapping one onto the
    other would have been the `currentMileage` defect exactly — the right number under the
    wrong label.
    """

    async def test_the_door_reports_its_equipment_capabilities(self, client_a, yard):
        door = await _door(client_a, yard["door"])
        assert "equipment_capabilities" in door

    async def test_the_door_reports_when_it_was_last_occupied(self, client_a, yard):
        """Present as a key even when null, so the client can tell "never occupied" from
        "this deployment does not send it"."""
        door = await _door(client_a, yard["door"])
        assert "last_occupied_at" in door

    def test_the_schema_declares_no_field_the_table_lacks(self):
        """The audit itself, asserted. Every response field must correspond to a column —
        or to a denormalised value the handler resolves, of which there is exactly one."""
        from app.db.models import DockDoor
        from app.models.schemas import DockDoorResponse

        columns = {c.name for c in DockDoor.__table__.columns}
        resolved = {"trailer_license_plate"}  # joined from yard_trailers by the handler
        declared = set(DockDoorResponse.model_fields)
        assert not (declared - columns - resolved), (
            "DockDoorResponse declares fields dock_doors does not have and the handler does "
            f"not resolve: {sorted(declared - columns - resolved)}"
        )


class TestARawInsertedAppointmentDoesNotFiveHundred:
    """A SECOND defect, found because this file's fixture writes rows with psycopg2.

    `dock_appointments.meta_data` is `Column(JSON, default={})` — a PYTHON-side default, so
    it fires only for rows written through SQLAlchemy. A migration, a seeder or any raw
    INSERT leaves NULL, the ORM hands the field an explicit None, and
    `metadata: Dict[str, Any]` rejected it: `GET /yard/dock/appointments` answered **500**
    with "metadata: Input should be a valid dictionary" — an error naming our own schema
    rather than the row, so nobody would think to look at the data.

    `DockDoorResponse` carries a long comment describing this exact failure being fixed for
    `equipment_capabilities`. The appointment schema beside it was left alone. Method rule
    18, and the fixture that caught it was not looking for it.
    """

    async def test_the_schedule_loads_for_a_row_written_outside_sqlalchemy(
        self, client_a, yard
    ):
        response = await client_a.get(
            APPOINTMENTS,
            params={"start_date": (yard["start"] - timedelta(hours=2)).isoformat()},
        )
        assert response.status_code == 200, response.text

    def test_the_nullable_json_fields_accept_none(self):
        """Pinned on the schema, because the endpoint only fails when such a row exists —
        and a suite that seeds everything through the ORM would never produce one."""
        from app.models.schemas import DockAppointmentResponse

        model = DockAppointmentResponse.model_validate({
            "id": uuid4(), "organization_id": uuid4(),
            "appointment_type": None, "scheduled_start": datetime.now(timezone.utc),
            "scheduled_end": datetime.now(timezone.utc),
            "status": None, "priority": None, "compliance_required": False,
            "meta_data": None,
            "dock_door_id": None, "trailer_id": None, "shipment_id": None,
            "operation_id": None, "carrier_id": None, "driver_id": None,
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
        })
        assert model.metadata is None


class TestItDoesNotBecomeAnNPlusOne:
    async def test_one_query_resolves_every_plate(self, client_a, yard):
        """Two doors, one query. Listening on the `Engine` CLASS, not on
        `app.db.database.engine` — conftest rebinds every module to its own `test_engine`,
        so a module-level listener records nothing and the count passes vacuously. That
        mistake was made in this session's geofence guard and caught by mutation."""
        from sqlalchemy import event
        from sqlalchemy.engine import Engine

        statements: list[str] = []

        def record(conn, cursor, statement, parameters, context, executemany):
            if statement.lstrip().upper().startswith("SELECT"):
                statements.append(statement)

        event.listen(Engine, "before_cursor_execute", record)
        try:
            await client_a.get(DOORS)
        finally:
            event.remove(Engine, "before_cursor_execute", record)

        assert statements, "nothing was recorded; the listener is on the wrong engine"
        trailer_queries = [s for s in statements if "yard_trailers" in s]
        assert len(trailer_queries) <= 1, (
            f"{len(trailer_queries)} trailer queries for a two-door list — one per row?"
        )

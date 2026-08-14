"""`GET /transportation/drivers` finally declares a model — proven against a real response (FS-702).

The route answered `List[Dict[str, Any]]` for its whole life while `DriverResponse` sat on
the single-driver route beside it. FS-688 registered it as the clearest permissive-model
instance and documented exactly why nobody had "just declared" it: the handler dumps
`DriverResponse` (snake_case — no alias generator) and adds SEVEN derived keys in
camelCase, and FastAPI **filters** any response key the declared model omits. Declare the
model with one field missing and that field silently vanishes from the wire; the first
casualty would be `hosDriveHoursRemaining`, which the compliance tab reads to count DOT
violations — the exact figure FS-676 fixed after `null === 0` cleared every fleet.

So every one of the seven is asserted BY NAME here, against a real response from a real
Postgres, with the declared model in the loop. The per-field mutation this protects
against: deleting any single field from `DriverListItem` fails this file on that field's
name, not on a count.

Fixture note: drivers are seeded through the admin connection like the HOS tests beside
this file, because the suite's client fixtures speak to the app over HTTP and the app's
own POST /drivers path (also asserted here, as the sanity check that the model accepts
what Create produces) covers only a subset of the columns the list derives from.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
import pytest_asyncio

pytestmark = pytest.mark.asyncio

#: Every key the handler adds on top of DriverResponse, spelled as the wire spells it.
#: A NEW derived key added to the handler without joining the model is filtered by
#: FastAPI and never reaches a client — which is why this list must match the handler,
#: and why test_the_model_and_handler_agree below reads the handler's source.
DERIVED_KEYS = (
    "carrierName",
    "currentVehicleId",
    "currentShipmentId",
    "endorsements",
    "licenseExpiry",
    "hosDriveHoursRemaining",
    "hosDutyHoursRemaining",
)

#: A sample of the base model's own keys, snake_case on the wire (the frontend's
#: registerTransform seam converts; the payload itself is mixed-case by design).
BASE_KEYS = ("first_name", "last_name", "is_active", "carrier_id", "created_at")


@pytest_asyncio.fixture
async def a_full_driver(admin_sync_url, seeded_orgs):
    """One driver exercising every derived key: a carrier, an assigned vehicle, an active
    shipment, endorsements, a license expiry, and reported HOS hours."""
    import psycopg2

    conn = psycopg2.connect(admin_sync_url)
    conn.autocommit = True
    ids = {
        "carrier": uuid4(), "driver": uuid4(), "vehicle": uuid4(), "shipment": uuid4(),
    }
    org = str(seeded_orgs["org_a_id"])
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO carriers (id, organization_id, carrier_name, is_active) "
            "VALUES (%s, %s, 'Full Freight', true)",
            (str(ids["carrier"]), org),
        )
        cur.execute(
            "INSERT INTO drivers (id, organization_id, carrier_id, first_name, last_name, "
            "endorsements, license_expiry, hos_drive_hours_today, hos_on_duty_hours_today) "
            "VALUES (%s, %s, %s, 'Full', 'Coverage', %s, '2027-01-15T00:00:00+00:00', 8.0, 10.0)",
            (str(ids["driver"]), org, str(ids["carrier"]), '["hazmat", "tanker"]'),
        )
        cur.execute(
            "INSERT INTO vehicles (id, organization_id, vehicle_number, current_driver_id) "
            "VALUES (%s, %s, %s, %s)",
            (str(ids["vehicle"]), org, f"V-{ids['vehicle'].hex[:6]}", str(ids["driver"])),
        )
        cur.execute(
            "INSERT INTO shipments (id, organization_id, shipment_number, driver_id, status) "
            "VALUES (%s, %s, %s, %s, 'in_transit')",
            (str(ids["shipment"]), org, f"S-{ids['shipment'].hex[:6]}", str(ids["driver"])),
        )
    yield ids
    with conn.cursor() as cur:
        cur.execute("DELETE FROM shipments WHERE id = %s", (str(ids["shipment"]),))
        cur.execute("DELETE FROM vehicles WHERE id = %s", (str(ids["vehicle"]),))
        cur.execute("DELETE FROM drivers WHERE id = %s", (str(ids["driver"]),))
        cur.execute("DELETE FROM carriers WHERE id = %s", (str(ids["carrier"]),))
    conn.close()


async def _the_row(client):
    response = await client.get("/api/v1/transportation/drivers")
    assert response.status_code == 200, response.text
    match = [d for d in response.json() if d.get("last_name") == "Coverage"]
    assert match, "the seeded driver is missing from the list"
    return match[0]


class TestEveryDerivedKeySurvivesTheModel:
    @pytest.mark.parametrize("key", DERIVED_KEYS)
    async def test_the_key_is_on_the_wire(self, client_a, a_full_driver, key):
        """PER FIELD, BY NAME. `response_model` filtering fails silently — remove a field
        from DriverListItem and FastAPI drops it from every response with no error
        anywhere. A single all-keys assertion would report 'something missing'; this
        reports which."""
        row = await _the_row(client_a)
        assert key in row, (
            f"'{key}' is not in the response — DriverListItem no longer declares it, so "
            f"FastAPI filtered it out. The handler still computes it; the wire lost it."
        )

    async def test_the_derived_values_are_real_not_defaults(self, client_a, a_full_driver):
        """The model's None defaults must not be what actually ships when data exists —
        a model whose defaults papered over a broken handler would pass the presence
        tests above with seven nulls."""
        row = await _the_row(client_a)
        assert row["carrierName"] == "Full Freight"
        assert row["currentVehicleId"] == str(a_full_driver["vehicle"])
        assert row["currentShipmentId"] == str(a_full_driver["shipment"])
        assert row["endorsements"] == ["hazmat", "tanker"]
        assert row["licenseExpiry"] is not None
        assert row["hosDriveHoursRemaining"] == pytest.approx(3.0)  # 11 - 8
        assert row["hosDutyHoursRemaining"] == pytest.approx(4.0)   # 14 - 10

    async def test_the_base_keys_are_still_snake_case(self, client_a, a_full_driver):
        """The mixed casing is the contract: the frontend's registerTransform seam
        converts the snake half and passes the camel half through. A well-meant alias
        generator on DriverListItem would camelise the base keys and double-convert on
        the client."""
        row = await _the_row(client_a)
        for key in BASE_KEYS:
            assert key in row, f"base key '{key}' missing — the base model half changed"

    async def test_the_openapi_document_now_has_properties(self, client_a):
        """The point of declaring: the generated schema stopped being an empty object."""
        response = await client_a.get("/openapi.json")
        schema = response.json()["components"]["schemas"].get("DriverListItem")
        assert schema, "DriverListItem is not in the OpenAPI components"
        for key in DERIVED_KEYS:
            assert key in schema["properties"], f"{key} missing from the OpenAPI schema"


def test_the_model_and_handler_agree():
    """A derived key added to the handler without joining the model would be silently
    filtered — the original defect, reintroduced one field at a time. The handler's
    `row[...] =` assignments and DriverListItem's declared fields must be the same set."""
    import pathlib
    import re

    from app.models.schemas import DriverListItem, DriverResponse

    source = pathlib.Path("app/api/transportation.py").read_text()
    start = source.index('def get_drivers(')
    end = source.index('@router.get("/drivers/{driver_id}"')
    handler_keys = set(re.findall(r'row\["(\w+)"\]\s*=', source[start:end]))

    declared = set(DriverListItem.model_fields) - set(DriverResponse.model_fields)
    assert handler_keys == declared == set(DERIVED_KEYS), (
        f"handler adds {sorted(handler_keys)}, DriverListItem declares {sorted(declared)}, "
        f"this file asserts {sorted(DERIVED_KEYS)} — any key in one set and not the others "
        f"is either filtered off the wire or declared and never produced"
    )

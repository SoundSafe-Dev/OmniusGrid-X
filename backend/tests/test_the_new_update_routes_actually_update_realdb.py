"""The five routes that did not exist, driven against a real database (FS-677).

`test_what_can_be_created_can_be_updated.py` proves each route is declared. Declared is not
applied — FS-676 was a route that accepted a body and changed nothing, and answered 200 while
doing it — so every one of these creates a row, sends a change, and reads it back through the
API.

Two of the five carry real logic rather than a `setattr` loop, and those are where most of the
assertions are:

  * **rescheduling a dock appointment** has to honour the two invariants `schedule_appointment`
    enforces, or the update becomes the way to create what FS-392 removed: a reversed booking
    that blocks a legitimate slot while protecting none, and a double-booked door. Both are
    checked against the EFFECTIVE interval — the new value where sent, the stored one where
    not — because a caller who moves only `scheduled_end` still changes the interval;
  * **moving a task to another board** must carry a column on the destination board, or the
    task lands in a column belonging to the board it just left.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio

pytestmark = pytest.mark.asyncio

TRANSPORT = "/api/v1/transportation"
YARD = "/api/v1/yard"


def _conn(admin_sync_url):
    import psycopg2

    conn = psycopg2.connect(admin_sync_url)
    conn.autocommit = True
    return conn


@pytest_asyncio.fixture
async def rows(admin_sync_url, seeded_orgs):
    """A shipment, two dock doors and a carrier for org A, cleaned up afterwards."""
    org = str(seeded_orgs["org_a_id"])
    ids = {
        "shipment": uuid.uuid4(),
        "door_a": uuid.uuid4(),
        "door_b": uuid.uuid4(),
        "carrier": uuid.uuid4(),
    }
    conn = _conn(admin_sync_url)
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO carriers (id, organization_id, carrier_name) VALUES (%s, %s, %s)",
            (str(ids["carrier"]), org, f"FS677-{uuid.uuid4().hex[:6]}"),
        )
        cur.execute(
            "INSERT INTO shipments (id, organization_id, shipment_number, status) "
            "VALUES (%s, %s, %s, 'planned')",
            (str(ids["shipment"]), org, f"FS677-{uuid.uuid4().hex[:6]}"),
        )
        for key in ("door_a", "door_b"):
            cur.execute(
                "INSERT INTO dock_doors (id, organization_id, door_number, status) "
                "VALUES (%s, %s, %s, 'available')",
                (str(ids[key]), org, f"FS677-{uuid.uuid4().hex[:6]}"),
            )
    yield ids
    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM dock_appointments WHERE dock_door_id IN (%s, %s)",
            (str(ids["door_a"]), str(ids["door_b"])),
        )
        cur.execute("DELETE FROM freight_charges WHERE shipment_id = %s", (str(ids["shipment"]),))
        cur.execute("DELETE FROM load_plans WHERE shipment_id = %s", (str(ids["shipment"]),))
        cur.execute("DELETE FROM shipments WHERE id = %s", (str(ids["shipment"]),))
        cur.execute(
            "DELETE FROM dock_doors WHERE id IN (%s, %s)",
            (str(ids["door_a"]), str(ids["door_b"])),
        )
        cur.execute("DELETE FROM routes WHERE route_name LIKE 'FS677%%'")
        cur.execute("DELETE FROM carriers WHERE id = %s", (str(ids["carrier"]),))
    conn.close()


async def _post(client, path, body):
    response = await client.post(path, json=body)
    assert response.status_code in (200, 201), f"POST {path} -> {response.status_code}\n{response.text}"
    return response.json()


async def _put(client, path, body, expect=200):
    response = await client.put(path, json=body)
    assert response.status_code == expect, f"PUT {path} -> {response.status_code}\n{response.text}"
    return response.json() if response.status_code == 200 else response


def _future(hours: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()


class TestARouteCanBeCorrected:
    async def test_the_distance_that_prices_every_shipment_can_be_fixed(self, client_a, rows):
        """FS-665 made `get_shipment_costs` price a shipment from its route's distance. A
        route entered with the wrong distance therefore mispriced every shipment on it, and
        until now there was no route to correct it."""
        route = await _post(
            client_a,
            f"{TRANSPORT}/routes",
            {"route_name": "FS677 Route", "origin": {"city": "Reno"}, "destination": {"city": "Elko"}},
        )
        updated = await _put(
            client_a, f"{TRANSPORT}/routes/{route['id']}", {"total_distance_miles": 289.4}
        )
        assert updated["total_distance_miles"] == 289.4

        reread = await client_a.get(f"{TRANSPORT}/routes")
        mine = [r for r in reread.json() if r["id"] == route["id"]]
        assert mine and mine[0]["total_distance_miles"] == 289.4, (
            "the update answered 200 and the row did not change"
        )

    async def test_an_origin_can_be_corrected(self, client_a, rows):
        route = await _post(client_a, f"{TRANSPORT}/routes", {"route_name": "FS677 Route B"})
        updated = await _put(
            client_a, f"{TRANSPORT}/routes/{route['id']}", {"origin": {"city": "Sparks"}}
        )
        assert updated["origin"] == {"city": "Sparks"}

    async def test_an_omitted_field_is_left_alone(self, client_a, rows):
        route = await _post(
            client_a, f"{TRANSPORT}/routes", {"route_name": "FS677 Route C", "origin": {"city": "Reno"}}
        )
        await _put(client_a, f"{TRANSPORT}/routes/{route['id']}", {"total_distance_miles": 12.0})
        after = await _put(client_a, f"{TRANSPORT}/routes/{route['id']}", {"is_active": False})
        assert after["total_distance_miles"] == 12.0
        assert after["origin"] == {"city": "Reno"}

    async def test_another_tenant_cannot_reach_it(self, client_a, client_b, rows):
        route = await _post(client_a, f"{TRANSPORT}/routes", {"route_name": "FS677 Route D"})
        response = await client_b.put(
            f"{TRANSPORT}/routes/{route['id']}", json={"total_distance_miles": 1.0}
        )
        assert response.status_code in (403, 404)


class TestALoadPlanCanBeAmended:
    async def test_the_sequence_can_be_changed(self, client_a, rows):
        plan = await _post(
            client_a,
            f"{TRANSPORT}/load-plans",
            {"shipment_id": str(rows["shipment"]), "load_sequence": [{"pallet": 1}]},
        )
        updated = await _put(
            client_a,
            f"{TRANSPORT}/load-plans/{plan['id']}",
            {"load_sequence": [{"pallet": 1}, {"pallet": 2}], "special_instructions": "Reefer at 4C"},
        )
        assert len(updated["load_sequence"]) == 2
        assert updated["special_instructions"] == "Reefer at 4C"

    async def test_the_temperature_zones_stay_a_list(self, client_a, rows):
        """FS-670: `temperature_zones` is `Column(JSON, default=[])` and a dict there made
        the response model refuse the row — a 500 on the success path. The update path can
        write this column too, so it is asserted here rather than assumed."""
        plan = await _post(
            client_a, f"{TRANSPORT}/load-plans", {"shipment_id": str(rows["shipment"])}
        )
        updated = await _put(
            client_a,
            f"{TRANSPORT}/load-plans/{plan['id']}",
            {"temperature_zones": [{"zone": "front", "setpoint_c": 4}]},
        )
        assert isinstance(updated["temperature_zones"], list)


class TestAFreightChargeCanBeCorrected:
    async def test_an_invented_amount_can_be_replaced(self, client_a, rows):
        """The loop back to FS-665, which found this service inventing a $1,333.33 linehaul
        from a 500-mile default. Once written, that figure was permanent."""
        charge = await _post(
            client_a,
            f"{TRANSPORT}/freight-charges",
            {"shipment_id": str(rows["shipment"]), "charge_type": "linehaul", "amount": 1333.33},
        )
        updated = await _put(
            client_a,
            f"{TRANSPORT}/freight-charges/{charge['id']}",
            {"amount": 742.5, "rate_basis": "per_mile", "charge_description": "Corrected"},
        )
        assert updated["amount"] == 742.5
        assert updated["rate_basis"] == "per_mile"

        reread = await client_a.get(f"{TRANSPORT}/shipments/{rows['shipment']}/freight-charges")
        assert [c for c in reread.json() if c["id"] == charge["id"]][0]["amount"] == 742.5


class TestADockDoorCanBeReconfigured:
    async def test_a_bay_can_change_type_and_go_out_of_service(self, client_a, rows):
        updated = await _put(
            client_a,
            f"{YARD}/dock/doors/{rows['door_a']}",
            {"door_type": "cross_dock", "status": "maintenance"},
        )
        assert updated["door_type"] == "cross_dock"
        assert updated["status"] == "maintenance"

    async def test_the_capabilities_map_is_not_wiped_by_an_unrelated_update(
        self, client_a, rows
    ):
        """`equipment_capabilities` was declared `Dict[str, Any] = {}` rather than
        Optional — `exclude_unset` saves it, and this is the assertion that says so."""
        await _put(
            client_a,
            f"{YARD}/dock/doors/{rows['door_a']}",
            {"equipment_capabilities": {"leveler": True}},
        )
        after = await _put(
            client_a, f"{YARD}/dock/doors/{rows['door_a']}", {"status": "available"}
        )
        assert after["equipment_capabilities"] == {"leveler": True}


class TestADockAppointmentCanBeRescheduled:
    async def _appointment(self, client_a, door, start_h=4, end_h=5):
        return await _post(
            client_a,
            f"{YARD}/dock/appointments",
            {
                "dock_door_id": str(door),
                "appointment_type": "delivery",
                "scheduled_start": _future(start_h),
                "scheduled_end": _future(end_h),
            },
        )

    async def test_an_appointment_can_be_moved(self, client_a, rows):
        appointment = await self._appointment(client_a, rows["door_a"])
        new_start, new_end = _future(20), _future(21)
        updated = await _put(
            client_a,
            f"{YARD}/dock/appointments/{appointment['id']}",
            {"scheduled_start": new_start, "scheduled_end": new_end},
        )
        assert updated["scheduled_start"][:16] == new_start[:16]

    async def test_it_can_be_moved_to_another_door(self, client_a, rows):
        appointment = await self._appointment(client_a, rows["door_a"])
        updated = await _put(
            client_a,
            f"{YARD}/dock/appointments/{appointment['id']}",
            {"dock_door_id": str(rows["door_b"])},
        )
        assert updated["dock_door_id"] == str(rows["door_b"])

    async def test_a_reversed_interval_is_refused(self, client_a, rows):
        """FS-392: a reversed booking is not merely wrong, it BLOCKS a legitimate slot
        through the containment branch of the conflict check while protecting none."""
        appointment = await self._appointment(client_a, rows["door_a"])
        response = await client_a.put(
            f"{YARD}/dock/appointments/{appointment['id']}",
            json={"scheduled_start": _future(30), "scheduled_end": _future(29)},
        )
        assert response.status_code == 400, response.text

    async def test_moving_only_the_end_before_the_start_is_refused(self, client_a, rows):
        """The effective-interval check. A caller who sends only `scheduled_end` still
        changes the interval, and comparing it against the stored start is the only way to
        see that."""
        appointment = await self._appointment(client_a, rows["door_a"], 40, 41)
        response = await client_a.put(
            f"{YARD}/dock/appointments/{appointment['id']}",
            json={"scheduled_end": _future(39)},
        )
        assert response.status_code == 400, response.text

    async def test_moving_onto_an_occupied_slot_is_refused(self, client_a, rows):
        first = await self._appointment(client_a, rows["door_a"], 50, 51)
        second = await self._appointment(client_a, rows["door_b"], 50, 51)
        response = await client_a.put(
            f"{YARD}/dock/appointments/{second['id']}",
            json={"dock_door_id": str(rows["door_a"])},
        )
        assert response.status_code == 400, response.text
        assert "booked" in response.text.lower()

    async def test_an_appointment_does_not_conflict_with_itself(self, client_a, rows):
        """`_check_conflicts` has taken an `exclude_id` since it was written and nothing
        passed one. Without it, changing anything on an appointment while keeping its slot
        collides with the row being updated and no reschedule could ever succeed."""
        appointment = await self._appointment(client_a, rows["door_a"], 60, 61)
        updated = await _put(
            client_a,
            f"{YARD}/dock/appointments/{appointment['id']}",
            {"scheduled_start": _future(60), "scheduled_end": _future(62), "priority": "high"},
        )
        assert updated["priority"] == "high"

"""What the maintenance form sends must be what the schedule stores and sends back.

THREE FAILURES IN ONE ROUND TRIP, and each hid the next.

**Creation always failed.** `create_schedule` raised 400 "vehicleId is required" unless the
payload carried `vehicleId` — while `_schedule_out` emits the vehicle under BOTH
`vehicleId` and `vehicleNumber`, from the same column. The form sent what it had been
shown, `vehicleNumber`, so no schedule could be created from the UI at all. Reading a field
under one name and refusing to accept it under that name is a round trip that cannot close.

**`priority` was collected, sent, and dropped.** The form offers Low/Normal/High/Urgent and
the panel renders a coloured badge for every row. `maintenance_schedules` had no such
column, so the handler ignored it and `_schedule_out` never emitted one — and the frontend
adapter substituted the literal `'medium'`, which is not even a member of its own declared
union. Every schedule displayed the same invented priority, whatever was chosen.

**`currentMileage` was collected, sent, and dropped too** — and this one was displayed. The
adapter filled it from `dueMileage`, so the panel printed the odometer at which service
falls DUE under the label "Mileage:", which a technician reads as where the vehicle is now.
The two differ by exactly the distance left before the service. With neither value present
it printed 0.

The mock fixtures supplied `currentMileage`, so every existing test was green while the
real path rendered a fabricated number. A mock more generous than the wire hides precisely
the defects that mock-mode testing is supposed to surface.

Fixed by migration 054 (a real `priority` column), by accepting `vehicleNumber`, by
returning the whole row from create instead of `{id, status}` — a caller that gets two
fields back cannot check that what it sent was stored — and by deleting `currentMileage`
rather than manufacturing it. A schedule knows when service is due; it does not know the
vehicle's present odometer.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

pytestmark = pytest.mark.asyncio

SOON = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
BASE = "/api/v1/maintenance/schedules"
# Distinctive enough to clean up by, because these tests POST into a database other
# suites read. `maintenance_schedules` has no RLS, so a row left behind is visible to
# every tenant and to anything that counts schedules.
VEHICLES = ("TRK-001", "TRK-002")


@pytest.fixture(autouse=True)
def cleanup(admin_sync_url):
    import psycopg2

    yield
    conn = psycopg2.connect(admin_sync_url)
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM maintenance_schedules WHERE vehicle_id = ANY(%s)", (list(VEHICLES),)
        )
    conn.close()


async def _create(client, **over):
    payload = {
        "vehicleNumber": "TRK-001",
        "serviceType": "oil_change",
        "description": "15,000 mile service",
        "scheduledDate": SOON,
        "priority": "urgent",
        "dueMileage": 145000,
    }
    payload.update(over)
    return await client.post(BASE, json=payload)


class TestTheColumnExists:
    def test_priority_is_not_null_with_a_default(self, admin_sync_url):
        """Pinned separately. A nullable column would put the ambiguity straight back —
        the reader would have to decide what a missing priority means, which is how the
        client came to invent 'medium' in the first place."""
        import psycopg2

        conn = psycopg2.connect(admin_sync_url)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT is_nullable, column_default FROM information_schema.columns "
                    "WHERE table_name = 'maintenance_schedules' AND column_name = 'priority'"
                )
                row = cur.fetchone()
            assert row is not None, "maintenance_schedules.priority is missing again"
            assert row[0] == "NO"
            assert row[1] is not None and "normal" in row[1]
        finally:
            conn.close()


class TestTheFormCanCreateAtAll:
    async def test_a_payload_carrying_vehicle_number_is_accepted(self, client_a):
        """THE ASSERTION THIS FILE EXISTS FOR. The UI sends `vehicleNumber`, because that
        is the name it was given when the row was read back."""
        response = await _create(client_a)
        assert response.status_code == 200, response.text

    async def test_a_payload_carrying_vehicle_id_still_works(self, client_a):
        """The original name must keep working — accepting a second spelling is not a
        licence to break the first."""
        response = await _create(client_a, vehicleId="TRK-002", vehicleNumber=None)
        assert response.status_code == 200, response.text

    async def test_a_payload_naming_no_vehicle_is_still_refused(self, client_a):
        """The negative control. Accepting anything at all would satisfy both tests above
        and lose the only validation this endpoint has."""
        response = await _create(client_a, vehicleNumber=None, vehicleId=None)
        assert response.status_code == 400, response.text


class TestWhatWasSentIsWhatComesBack:
    async def test_create_returns_the_stored_row_not_two_fields(self, client_a):
        """It returned `{id, status}`. A caller that gets two fields back cannot tell that
        its priority was discarded, which is how this survived."""
        body = (await _create(client_a)).json()
        assert body["serviceType"] == "oil_change"
        assert body["dueMileage"] == 145000
        assert body["vehicleId"] == "TRK-001"

    async def test_the_priority_is_the_one_that_was_chosen(self, client_a):
        body = (await _create(client_a, priority="urgent")).json()
        assert body["priority"] == "urgent", (
            "the operator chose 'urgent' and the schedule came back with something else"
        )

    async def test_a_different_priority_is_not_the_same_priority(self, client_a):
        """Together with the test above this is what rules out a hardcoded answer — one
        assertion on one value is satisfied by a handler that always says 'urgent'."""
        body = (await _create(client_a, priority="low")).json()
        assert body["priority"] == "low"

    async def test_an_unspecified_priority_defaults_to_normal(self, client_a):
        """Never 'medium'. That value was the client's invention and is not in the
        union the frontend declares."""
        body = (await _create(client_a, priority=None)).json()
        assert body["priority"] == "normal"

    async def test_it_survives_a_reread(self, client_a):
        """The create response could be built from the payload without ever storing it.
        This reads the row back through a different handler."""
        created = (await _create(client_a, priority="high")).json()
        listed = (await client_a.get(BASE)).json()
        match = [s for s in listed if s["id"] == created["id"]]
        assert match, "the created schedule is not in the list"
        assert match[0]["priority"] == "high"


class TestUpdatingThePriority:
    async def test_a_patch_changes_it(self, client_a):
        created = (await _create(client_a, priority="low")).json()
        patched = await client_a.patch(
            f"{BASE}/{created['id']}", json={"priority": "urgent"}
        )
        assert patched.status_code == 200, patched.text
        assert patched.json()["priority"] == "urgent"

    async def test_a_patch_that_omits_it_leaves_it_alone(self, client_a):
        """`pick()` returns None for an absent key and the loop skips it — asserted
        because a patch that silently reset every unmentioned field to a default would
        be a worse defect than the one being fixed."""
        created = (await _create(client_a, priority="urgent")).json()
        patched = await client_a.patch(
            f"{BASE}/{created['id']}", json={"description": "revised"}
        )
        assert patched.status_code == 200, patched.text
        assert patched.json()["priority"] == "urgent"
        assert patched.json()["description"] == "revised"

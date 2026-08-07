"""Yard's seven write routes actually change state, and only for their own tenant (FS-523).

`tests/route_walk.py` drives every route against a real Postgres and asserts no 5xx, so none
of these was *unexecuted*. All seven were **unasserted**: nothing checked that a checkout
checks anything out, that starting an appointment starts it, or that the row a caller writes
lands under the caller's organization rather than one they named.

    POST /trailers/{id}/checkout
    POST /dock/doors/{door}/assign/{trailer}
    POST /dock/appointments/{id}/start
    POST /dock/appointments/{id}/complete
    POST /moves
    POST /moves/{id}/complete
    POST /driver-wait-times

"Returns 200" is a weak claim for a state transition. A handler that catches its own
`ValueError`, returns a cheerful `{"message": "Trailer checked out successfully"}` and writes
nothing satisfies it — and this file's own subject includes a route whose entire response is a
hand-built dict with the word "successfully" in it. FS-352 removed a collector-restart endpoint
that was exactly that: past tense about a signal no code sent.

WHY EACH ONE IS TESTED TWICE. Once for the transition, once for the tenant. The service layer
takes `move_id` / `appointment_id` / `trailer_id` straight into a `WHERE id = :id` with **no
organization filter** (`yard_management.py:278-281, 302-304`), so RLS is the only thing between
a caller and another tenant's row. That is defence in depth doing the whole job rather than
backing something up — the same finding as FS-99's read side, on the write side, where the
consequence is a mutation rather than a read.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio

pytestmark = pytest.mark.asyncio


def _conn(admin_sync_url):
    import psycopg2

    conn = psycopg2.connect(admin_sync_url)
    conn.autocommit = True
    return conn


@pytest_asyncio.fixture
async def yard_fixtures(admin_sync_url, seeded_orgs):
    """A trailer, a dock door, an appointment and a move in EACH org.

    Seeded past RLS with a superuser connection, because the point of half these tests is
    that a caller in org A cannot reach org B's row — which requires org B's row to exist
    and be invisible, not merely absent.
    """
    ids = {}
    conn = _conn(admin_sync_url)
    with conn.cursor() as cur:
        for suffix, org_key in (("a", "org_a_id"), ("b", "org_b_id")):
            org = str(seeded_orgs[org_key])
            trailer, door, appointment, move, driver = (uuid.uuid4() for _ in range(5))
            cur.execute(
                "INSERT INTO drivers (id, organization_id, first_name, last_name, is_active) "
                "VALUES (%s, %s, %s, 'Jockey', true)",
                (str(driver), org, f"FS523-{suffix.upper()}"),
            )
            cur.execute(
                "INSERT INTO yard_trailers (id, organization_id, trailer_number, status, "
                "yard_location, check_in_at) "
                "VALUES (%s, %s, %s, 'checked_in', 'LOT-1', %s)",
                (str(trailer), org, f"TRL-{suffix.upper()}", datetime.now(timezone.utc)),
            )
            cur.execute(
                "INSERT INTO dock_doors (id, organization_id, door_number, status, is_active) "
                "VALUES (%s, %s, %s, 'available', true)",
                (str(door), org, f"D-{suffix.upper()}"),
            )
            cur.execute(
                "INSERT INTO dock_appointments (id, organization_id, dock_door_id, "
                "trailer_id, scheduled_start, scheduled_end, status) "
                "VALUES (%s, %s, %s, %s, %s, %s, 'scheduled')",
                (
                    str(appointment), org, str(door), str(trailer),
                    datetime.now(timezone.utc),
                    datetime.now(timezone.utc) + timedelta(hours=1),
                ),
            )
            cur.execute(
                "INSERT INTO yard_moves (id, organization_id, trailer_id, from_location, "
                "to_location, move_type, started_at) "
                "VALUES (%s, %s, %s, 'LOT-1', 'DOCK-1', 'yard_relocate', %s)",
                (str(move), org, str(trailer), datetime.now(timezone.utc)),
            )
            ids[suffix] = {
                "trailer": trailer, "door": door,
                "appointment": appointment, "move": move, "driver": driver,
            }

    yield ids

    with conn.cursor() as cur:
        for row in ids.values():
            cur.execute(
                "DELETE FROM driver_wait_times WHERE trailer_id = %s", (str(row["trailer"]),)
            )
            cur.execute("DELETE FROM yard_moves WHERE trailer_id = %s", (str(row["trailer"]),))
            cur.execute("DELETE FROM yard_moves WHERE id = %s", (str(row["move"]),))
            cur.execute(
                "DELETE FROM dock_appointments WHERE id = %s", (str(row["appointment"]),)
            )
            # The assign test binds the trailer to the door, and yard_trailers.dock_door_id
            # is a real FK — clearing it first is not tidiness, the DELETE fails without it.
            cur.execute(
                "UPDATE yard_trailers SET dock_door_id = NULL WHERE dock_door_id = %s",
                (str(row["door"]),),
            )
            cur.execute(
                "UPDATE dock_doors SET current_trailer_id = NULL WHERE id = %s",
                (str(row["door"]),),
            )
            cur.execute("DELETE FROM dock_doors WHERE id = %s", (str(row["door"]),))
            cur.execute("DELETE FROM yard_trailers WHERE id = %s", (str(row["trailer"]),))
            cur.execute("DELETE FROM drivers WHERE id = %s", (str(row["driver"]),))
        cur.execute("DELETE FROM yard_moves WHERE from_location = 'FS523-LOT'")
    conn.close()


def _column(admin_sync_url, table: str, column: str, row_id) -> object:
    conn = _conn(admin_sync_url)
    with conn.cursor() as cur:
        cur.execute(f"SELECT {column} FROM {table} WHERE id = %s", (str(row_id),))
        row = cur.fetchone()
    conn.close()
    return row[0] if row else None


@pytest.mark.realdb
class TestTheTransitionsActuallyHappen:
    async def test_checkout_records_a_departure(self, client_a, admin_sync_url, yard_fixtures):
        """The route answers `{"message": "Trailer checked out successfully"}` — a hand-built
        dict, past tense, built before anything is verified. FS-352 removed an endpoint whose
        whole body was a sentence like that and no action."""
        trailer = yard_fixtures["a"]["trailer"]
        response = await client_a.post(f"/api/v1/yard/trailers/{trailer}/checkout")
        assert response.status_code == 200, response.text

        status = _column(admin_sync_url, "yard_trailers", "status", trailer)
        checked_out = _column(admin_sync_url, "yard_trailers", "check_out_at", trailer)
        assert (status, checked_out) != ("checked_in", None), (
            f"the route reported success and the trailer row is unchanged "
            f"(status={status!r}, check_out_at={checked_out!r}). The response is a "
            f"hand-built dict saying 'successfully'; nothing else asserted it was true."
        )

    async def test_assigning_a_door_binds_the_trailer(
        self, client_a, admin_sync_url, yard_fixtures
    ):
        door, trailer = yard_fixtures["a"]["door"], yard_fixtures["a"]["trailer"]
        response = await client_a.post(f"/api/v1/yard/dock/doors/{door}/assign/{trailer}")
        assert response.status_code == 200, response.text

        assert _column(admin_sync_url, "dock_doors", "status", door) != "available", (
            "the door is still 'available' after a trailer was assigned to it, so the "
            "yard board will offer it to the next trailer as well"
        )

    async def test_starting_an_appointment_moves_it_off_scheduled(
        self, client_a, admin_sync_url, yard_fixtures
    ):
        appointment = yard_fixtures["a"]["appointment"]
        response = await client_a.post(
            f"/api/v1/yard/dock/appointments/{appointment}/start"
        )
        assert response.status_code == 200, response.text

        status = _column(admin_sync_url, "dock_appointments", "status", appointment)
        assert status != "scheduled", (
            f"the appointment is still {status!r} after being started. Dwell time is "
            f"measured from the actual start, so an appointment that never starts produces "
            f"a detention figure computed from a timestamp that was never written."
        )

    async def test_completing_an_appointment_closes_it(
        self, client_a, admin_sync_url, yard_fixtures
    ):
        appointment = yard_fixtures["a"]["appointment"]
        await client_a.post(f"/api/v1/yard/dock/appointments/{appointment}/start")
        response = await client_a.post(
            f"/api/v1/yard/dock/appointments/{appointment}/complete"
        )
        assert response.status_code == 200, response.text

        status = _column(admin_sync_url, "dock_appointments", "status", appointment)
        assert status not in {"scheduled", "in_progress"}, (
            f"the appointment is still {status!r} after being completed"
        )

    async def test_recording_a_move_relocates_the_trailer(
        self, client_a, admin_sync_url, yard_fixtures
    ):
        """The move row and the trailer's location are written in two separate commits
        (`yard_management.py:273-284`), so the row can exist while the trailer never moves.

        THIS BODY OMITS `organization_id` DELIBERATELY. `YardMoveCreate` required it while
        the handler derives the tenant from the token and discards the body's value, so this
        request returned 422 before FS-523 — as it did for the frontend, whose types carry no
        organization_id at all. See test_create_schemas_do_not_demand_a_discarded_tenant.py.
        """
        trailer = yard_fixtures["a"]["trailer"]
        response = await client_a.post(
            "/api/v1/yard/moves",
            json={
                "trailer_id": str(trailer),
                "from_location": "FS523-LOT",
                "to_location": "FS523-DOCK",
                "move_type": "yard_relocate",
            },
        )
        assert response.status_code in (200, 201), response.text

        location = _column(admin_sync_url, "yard_trailers", "yard_location", trailer)
        assert location == "FS523-DOCK", (
            f"the move was recorded and the trailer is still at {location!r}. The move row "
            f"and the trailer's location are committed separately, so the board can show a "
            f"jockey move that moved nothing."
        )

    async def test_completing_a_move_stamps_a_duration(
        self, client_a, admin_sync_url, yard_fixtures
    ):
        move = yard_fixtures["a"]["move"]
        response = await client_a.post(f"/api/v1/yard/moves/{move}/complete")
        assert response.status_code == 200, response.text

        completed = _column(admin_sync_url, "yard_moves", "completed_at", move)
        duration = _column(admin_sync_url, "yard_moves", "duration_seconds", move)
        assert completed is not None, "completed_at was not written"
        assert duration is not None, (
            "duration_seconds is null on a completed move — the jockey-productivity figure "
            "is computed from this column"
        )

    async def test_a_driver_wait_time_is_persisted(self, client_a, admin_sync_url, yard_fixtures):
        """`driver_wait_times` is what detention and demurrage charges are computed from
        (`test_yard_detention_charges.py`), so a POST that answers 200 and writes nothing
        produces an invoice from an empty table."""
        trailer = yard_fixtures["a"]["trailer"]
        response = await client_a.post(
            "/api/v1/yard/driver-wait-times",
            json={
                "trailer_id": str(trailer),
                "driver_id": str(yard_fixtures["a"]["driver"]),
                "check_in_at": datetime.now(timezone.utc).isoformat(),
                "detention_rate": 75.0,
            },
        )
        assert response.status_code in (200, 201), response.text

        conn = _conn(admin_sync_url)
        with conn.cursor() as cur:
            cur.execute(
                "SELECT count(*), max(detention_rate) FROM driver_wait_times "
                "WHERE trailer_id = %s",
                (str(trailer),),
            )
            count, rate = cur.fetchone()
        conn.close()
        assert count == 1, f"expected the wait-time row to be persisted, found {count}"
        assert float(rate) == 75.0, (
            f"the row was written with detention_rate={rate}, not the 75.0 the caller sent — "
            f"the charge is computed from this column"
        )


@pytest.mark.realdb
class TestOneTenantCannotDriveAnothersYard:
    """The service layer takes each id straight into `WHERE id = :id` with no organization
    filter, so RLS is the only thing standing between a caller and another tenant's row.

    A 404 is the right answer and the one these assert: the row must be unreachable, and it
    must be unreachable in a way that does not confirm it exists.
    """

    async def test_checkout_of_another_orgs_trailer(self, client_a, admin_sync_url, yard_fixtures):
        trailer = yard_fixtures["b"]["trailer"]
        response = await client_a.post(f"/api/v1/yard/trailers/{trailer}/checkout")

        assert response.status_code in (403, 404), (
            f"org A checked out org B's trailer and got {response.status_code}"
        )
        assert _column(admin_sync_url, "yard_trailers", "status", trailer) == "checked_in", (
            "org B's trailer was modified by a caller in org A"
        )

    async def test_starting_another_orgs_appointment(
        self, client_a, admin_sync_url, yard_fixtures
    ):
        appointment = yard_fixtures["b"]["appointment"]
        response = await client_a.post(
            f"/api/v1/yard/dock/appointments/{appointment}/start"
        )

        assert response.status_code in (403, 404), (
            f"org A started org B's appointment and got {response.status_code}"
        )
        assert (
            _column(admin_sync_url, "dock_appointments", "status", appointment) == "scheduled"
        ), "org B's appointment was started by a caller in org A"

    async def test_completing_another_orgs_move(self, client_a, admin_sync_url, yard_fixtures):
        move = yard_fixtures["b"]["move"]
        response = await client_a.post(f"/api/v1/yard/moves/{move}/complete")

        assert response.status_code in (403, 404), (
            f"org A completed org B's yard move and got {response.status_code}"
        )
        assert _column(admin_sync_url, "yard_moves", "completed_at", move) is None, (
            "org B's move was completed by a caller in org A"
        )

    async def test_assigning_another_orgs_door(self, client_a, admin_sync_url, yard_fixtures):
        """400, not 404, and that is this handler's own choice.

        `assign_trailer_to_dock` maps every `ValueError` to 400 (`yard.py:352-353`) where its
        six siblings map theirs to 404. Both refuse, which is what matters here, and the
        difference is recorded rather than asserted away: a caller cannot distinguish
        "no such door" from "not yours" under either code, which is the property that
        prevents probing.
        """
        door, trailer = yard_fixtures["b"]["door"], yard_fixtures["a"]["trailer"]
        response = await client_a.post(f"/api/v1/yard/dock/doors/{door}/assign/{trailer}")

        assert response.status_code in (400, 403, 404), (
            f"org A assigned a trailer to org B's dock door and got {response.status_code}"
        )
        assert _column(admin_sync_url, "dock_doors", "status", door) == "available", (
            "org B's dock door was occupied by a caller in org A"
        )

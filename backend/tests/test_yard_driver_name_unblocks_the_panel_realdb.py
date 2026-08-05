"""The driver block on a trailer can render at all (FS-437).

`YardManagement.tsx` wraps the whole driver section in a guard:

    {trailer.driverName && (
      <div>
        <h4>Driver Information</h4>
        <p>{trailer.driverName}</p>
        {trailer.driverPhone && <p>{trailer.driverPhone}</p>}
      </div>
    )}

**`driverName` was never sent.** So the block never rendered — and it took `driverPhone`
with it, a field the yard's driver resolver exists specifically to deliver, under a
docstring calling it *"the number an operator calls when a trailer has been sitting on the
yard"*. (That resolver is now `_resolve_driver_contacts`, renamed when the name was folded
into its single query — see `TestItIsStillOneQuery` below.)

That fix was real, correct, and invisible. **A guard on a field nobody sends is a permanent
`false`, and everything inside it disappears** — which is worse than a blank line, because a
blank line can be seen.

WHY THE PHONE'S OWN TEST DID NOT NOTICE. `test_yard_driver_phone_is_resolved_realdb.py`
asserts the API sends the phone, and the API does. Nothing was wrong at that boundary. The
defect lives one layer up, in a condition that no backend test can see and no type-checker
objects to, because `driverName?: string` is a perfectly well-typed thing to test for.

So this file asserts the CONJUNCTION the screen actually needs: not "the phone is sent" but
"the block's condition is satisfiable, and the phone is inside it when it is".
"""

from __future__ import annotations

from uuid import uuid4

import pytest
import pytest_asyncio

pytestmark = pytest.mark.asyncio

pytest.importorskip("testcontainers")

FIRST, LAST, PHONE = "Dale", "Kowalski", "+1-313-555-0142"


@pytest_asyncio.fixture
async def trailer_with_driver(admin_sync_url, seeded_orgs):
    """A trailer on the yard with a named, reachable driver."""
    import psycopg2

    conn = psycopg2.connect(admin_sync_url)
    conn.autocommit = True
    driver_id, trailer_id = uuid4(), uuid4()
    org = str(seeded_orgs["org_a_id"])
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO drivers (id, organization_id, first_name, last_name, phone, "
            "is_active) VALUES (%s, %s, %s, %s, %s, true)",
            (str(driver_id), org, FIRST, LAST, PHONE),
        )
        cur.execute(
            "INSERT INTO yard_trailers (id, organization_id, trailer_number, driver_id, "
            "status) VALUES (%s, %s, %s, %s, 'on_yard')",
            (str(trailer_id), org, f"T-{trailer_id.hex[:6]}", str(driver_id)),
        )
    yield {"driver_id": driver_id, "trailer_id": trailer_id, "org": org}
    with conn.cursor() as cur:
        cur.execute("DELETE FROM yard_trailers WHERE id = %s", (str(trailer_id),))
        cur.execute("DELETE FROM drivers WHERE id = %s", (str(driver_id),))
    conn.close()


def _rows(payload):
    return payload["items"] if isinstance(payload, dict) and "items" in payload else payload


class TestTheBlockCanRender:
    async def test_the_trailer_carries_a_driver_name(self, client_a, trailer_with_driver):
        """The condition the whole block hangs on."""
        rows = _rows((await client_a.get("/api/v1/yard/trailers")).json())
        mine = [t for t in rows if t["id"] == str(trailer_with_driver["trailer_id"])]
        assert mine, f"the seeded trailer is not listed ({len(rows)} rows)"
        assert mine[0].get("driverName") == f"{FIRST} {LAST}", (
            f"driverName={mine[0].get('driverName')!r}. The panel wraps the entire driver "
            f"section in `{{trailer.driverName && …}}`, so a null hides the phone too"
        )

    async def test_the_phone_is_inside_the_block_that_now_renders(
        self, client_a, trailer_with_driver
    ):
        """THE ASSERTION THIS FILE EXISTS FOR. The phone was already sent and already
        tested; what was missing is that anything could reach it."""
        rows = _rows((await client_a.get("/api/v1/yard/trailers")).json())
        mine = [t for t in rows if t["id"] == str(trailer_with_driver["trailer_id"])][0]
        assert mine.get("driverName") and mine.get("driverPhone") == PHONE, (
            "the phone is sent but the name that gates its container is not, so the "
            "operator still cannot see the number"
        )

    async def test_the_appointment_row_carries_it_too(
        self, client_a, trailer_with_driver, admin_sync_url
    ):
        """The dock schedule resolves the same two fields from the same drivers table.
        Fixing one and not the other leaves half the yard screen as it was."""
        import psycopg2

        conn = psycopg2.connect(admin_sync_url)
        conn.autocommit = True
        appointment_id = uuid4()
        with conn.cursor() as cur:
            cur.execute(
                # SCHEDULED AHEAD, deliberately. `GET /yard/dock/appointments` filters
                # `scheduled_start >= start_date` and `start_date` defaults to now() AT
                # REQUEST TIME, so a row stamped now() at INSERT time is already in the past
                # by the time the request runs — a coin-flip on sub-millisecond ordering.
                # The first version of this test did exactly that: it passed in isolation
                # and failed in the full suite, which is the worst way for a test to be
                # wrong. Ten minutes out is also what a dock appointment actually is.
                "INSERT INTO dock_appointments (id, organization_id, appointment_type, "
                "scheduled_start, scheduled_end, status, driver_id) VALUES "
                "(%s, %s, 'delivery', now() + interval '10 minutes', "
                "now() + interval '70 minutes', 'scheduled', %s)",
                (
                    str(appointment_id),
                    trailer_with_driver["org"],
                    str(trailer_with_driver["driver_id"]),
                ),
            )
        try:
            rows = _rows((await client_a.get("/api/v1/yard/dock/appointments")).json())
            mine = [a for a in rows if a["id"] == str(appointment_id)]
            assert mine, "the seeded appointment is not on the dock schedule"
            assert mine[0].get("driverName") == f"{FIRST} {LAST}"
        finally:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM dock_appointments WHERE id = %s", (str(appointment_id),)
                )
            conn.close()


class TestTheNamelessCases:
    async def test_a_trailer_with_no_driver_is_still_listed(
        self, client_a, trailer_with_driver, admin_sync_url
    ):
        """`driver_id` is nullable — a trailer dropped without a driver record. The resolver
        skips empty ids, and the row must still come back rather than 500."""
        import psycopg2

        conn = psycopg2.connect(admin_sync_url)
        conn.autocommit = True
        orphan = uuid4()
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO yard_trailers (id, organization_id, trailer_number, status) "
                "VALUES (%s, %s, %s, 'on_yard')",
                (str(orphan), trailer_with_driver["org"], f"T-{orphan.hex[:6]}"),
            )
        try:
            rows = _rows((await client_a.get("/api/v1/yard/trailers")).json())
            mine = [t for t in rows if t["id"] == str(orphan)]
            assert mine, "a trailer with no driver dropped out of the list"
            assert mine[0].get("driverName") is None, (
                "a trailer with no driver reported a driver name — the resolver invented one"
            )
        finally:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM yard_trailers WHERE id = %s", (str(orphan),))
            conn.close()


class TestItIsStillOneQuery:
    async def test_the_name_did_not_cost_a_second_lookup(
        self, app, client_a, trailer_with_driver
    ):
        """The first version of this fix added a SECOND resolver beside the phone one, and
        `test_yard_driver_phone_is_resolved_realdb.py` refused it immediately — *"expected
        exactly one query against drivers for a page of trailers, saw 2"*. It was right: a
        per-page lookup that becomes two becomes three the next time someone needs a field.

        Asserted here as well as there, because that test guards the phone and this one
        guards the name, and whichever is edited next should fail on its own terms.

        EXACT, not an upper bound — `<= 1` is satisfied by zero, which is what a matcher
        that matches nothing also returns.
        """
        from sqlalchemy import event
        from sqlalchemy.engine import Engine

        statements: list[str] = []

        def _record(conn, cursor, statement, parameters, context, executemany):
            if "FROM drivers" in statement:
                statements.append(statement)

        event.listen(Engine, "before_cursor_execute", _record)
        try:
            await client_a.get("/api/v1/yard/trailers")
        finally:
            event.remove(Engine, "before_cursor_execute", _record)

        assert len(statements) == 1, (
            f"expected exactly one query against drivers for a page of trailers, saw "
            f"{len(statements)}:\n  " + "\n  ".join(statements)
        )
        assert "first_name" in statements[0] and "phone" in statements[0], (
            "the single query no longer fetches both the name and the phone"
        )

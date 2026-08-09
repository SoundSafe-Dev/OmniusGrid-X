"""`hosDriveHoursRemaining` was null for every driver, and null cleared every fleet.

Migration 042 added `drivers.hos_drive_hours_remaining` and `hos_duty_hours_remaining`
with no default and no backfill. **Nothing in this codebase has ever written to either** —
no ELD sync, no ingestion path, no computation. The model comment says what they were
meant to be (`# 11 - hos_drive_hours_today`) and nothing did the subtraction.

WHY IT MATTERED. The transportation compliance tab counts a violation as

    drivers.filter(d => d.hosDriveHoursRemaining === 0).length

and `null === 0` is **false** in JavaScript. So every driver was counted as compliant,
every fleet came back with zero violations, and the page rendered a green *"No HOS
violations detected"* tick — on the SUCCESS path, with the data loaded. Hours of Service
is DOT-regulated and a compliance officer reads that tick as clearance.

THIS PAGE WAS ALREADY FIXED ONCE for the same class: a failed drivers query also produced
an empty list and the same green tick. That fix added a failure branch and left this,
which is the far more common case — the query succeeds and the field is simply null.
Method rule 18: a guard wrong once is likeliest wrong again, and the second instance was
in the same component as the first.

THE FIX IS A DERIVATION, NOT A DEFAULT. `hos_drive_hours_today` is populated and is what
`check_compliance` already judges against, so remaining is computed from it. It stays NULL
when the consumed figure is missing too — a driver who has reported nothing is
unassessable, and inventing "11 hours left" for them is the same defect pointing the other
way.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
import pytest_asyncio

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def drivers(admin_sync_url, seeded_orgs):
    """Three drivers: one who has reported, one who has not, and one with a stored
    remaining figure that must win over the derivation."""
    import psycopg2

    conn = psycopg2.connect(admin_sync_url)
    conn.autocommit = True
    carrier_id = uuid4()
    ids = {"reported": uuid4(), "silent": uuid4(), "stored": uuid4()}
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO carriers (id, organization_id, carrier_name, is_active) "
            "VALUES (%s, %s, %s, true)",
            (str(carrier_id), str(seeded_orgs["org_a_id"]), f"C-{carrier_id.hex[:6]}"),
        )
        rows = (
            # consumed drive, consumed duty, stored remaining
            (ids["reported"], "Reported", 9.0, 12.0, None),
            (ids["silent"], "Silent", None, None, None),
            (ids["stored"], "Stored", 9.0, 12.0, 4.25),
        )
        for driver_id, last, drive, duty, stored in rows:
            cur.execute(
                "INSERT INTO drivers (id, organization_id, carrier_id, first_name, "
                "last_name, hos_drive_hours_today, hos_on_duty_hours_today, "
                "hos_drive_hours_remaining) VALUES (%s, %s, %s, 'Dana', %s, %s, %s, %s)",
                (str(driver_id), str(seeded_orgs["org_a_id"]), str(carrier_id),
                 last, drive, duty, stored),
            )
    yield ids
    with conn.cursor() as cur:
        cur.execute("DELETE FROM drivers WHERE carrier_id = %s", (str(carrier_id),))
        cur.execute("DELETE FROM carriers WHERE id = %s", (str(carrier_id),))
    conn.close()


async def _by_name(client, last_name):
    """Keys are snake_case ON THE WIRE. `/api/v1/transportation` is registered on the
    frontend casing seam, so the browser sees camelCase — but the two hand-added keys
    (`hosDriveHoursRemaining`, `carrierName`) are already camel in the payload, which is
    why this response mixes both. Asserting against the wire, not against the browser."""
    response = await client.get("/api/v1/transportation/drivers")
    assert response.status_code == 200, response.text
    rows = response.json()
    match = [d for d in rows if d.get("last_name") == last_name]
    assert match, f"no driver named {last_name} among {len(rows)} rows"
    return match[0]


class TestTheColumnIsStillUnwritten:
    def test_nothing_populates_it(self, admin_sync_url):
        """The premise of this whole file, asserted rather than assumed. If an ELD sync
        ever starts writing the column, the derivation below becomes a fallback rather
        than the only source, and this test says so by failing."""
        import psycopg2

        conn = psycopg2.connect(admin_sync_url)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT column_default, is_nullable FROM information_schema.columns "
                    "WHERE table_name = 'drivers' "
                    "AND column_name = 'hos_drive_hours_remaining'"
                )
                row = cur.fetchone()
            assert row is not None
            assert row[0] is None, "the column has a default now — re-read the derivation"
            assert row[1] == "YES"
        finally:
            conn.close()


class TestItIsDerivedFromWhatWasConsumed:
    async def test_a_driver_who_reported_gets_a_real_figure(self, client_a, drivers):
        """THE ASSERTION THIS FILE EXISTS FOR. 11 - 9 = 2, and it used to be null."""
        driver = await _by_name(client_a, "Reported")
        assert driver["hosDriveHoursRemaining"] == 2.0, (
            "remaining hours are still null for a driver who has reported 9 of 11"
        )

    async def test_duty_hours_are_derived_from_the_fourteen_hour_window(
        self, client_a, drivers
    ):
        driver = await _by_name(client_a, "Reported")
        assert driver["hosDutyHoursRemaining"] == 2.0

    async def test_a_stored_figure_wins_over_the_derivation(self, client_a, drivers):
        """The derivation is a fallback, not an override. A row written by a future ELD
        sync must not be recomputed from a stale consumed figure."""
        driver = await _by_name(client_a, "Stored")
        assert driver["hosDriveHoursRemaining"] == 4.25


class TestAbsenceStaysAbsent:
    async def test_a_driver_who_reported_nothing_has_no_remaining_figure(
        self, client_a, drivers
    ):
        """Inventing "11 hours left" for an unreported driver is the same defect facing
        the other way — it would clear them just as effectively as null did."""
        driver = await _by_name(client_a, "Silent")
        assert driver["hosDriveHoursRemaining"] is None
        assert driver["hosDutyHoursRemaining"] is None

    async def test_it_is_not_reported_as_zero_either(self, client_a, drivers):
        """Zero is what the frontend counts as a VIOLATION. Trading a false clearance for
        a false accusation is not a fix; an operator chasing a phantom breach stops
        trusting the number in both directions."""
        driver = await _by_name(client_a, "Silent")
        assert driver["hosDriveHoursRemaining"] != 0


class TestTheArithmeticIsBounded:
    def test_a_driver_over_the_limit_reports_zero_not_a_negative(self):
        """13 hours driven is a violation, not -2 hours remaining. Asserted on the helper
        directly, because seeding an over-limit driver exercises the same branch."""
        from app.api.transportation import _hours_remaining

        assert _hours_remaining(None, 13.0, 11.0) == 0.0

    def test_a_stored_zero_is_preserved(self):
        """`if stored is not None` — not `if stored`, which would treat a genuine zero
        (a driver who is out of hours) as missing and recompute it."""
        from app.api.transportation import _hours_remaining

        assert _hours_remaining(0.0, 5.0, 11.0) == 0.0

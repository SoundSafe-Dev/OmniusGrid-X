"""`overall_status: COMPLIANT` must mean the fleet was checked, not that nothing matched.

THE THIRD PLACE THIS DEFECT LIVED, and the one that reached it differently. The other two
were Python: `float(x or 0)` turned a driver who had never reported into one who had
driven zero hours, and a carrier roll-up counted zero violations among zero drivers. This
one is SQL:

    WHERE hos_drive_hours_today > 11
       OR hos_on_duty_hours_today > 14
       OR medical_cert_expires < now()

**A NULL never satisfies a comparison.** It evaluates to UNKNOWN, and `WHERE` discards
UNKNOWN exactly as it discards FALSE. A driver who has never reported hours, or has no
medical certificate on file, is therefore not counted as a violation — and not counted as
anything else either. `hos_count == 0` then reads as a clean fleet, and the endpoint
returned `"COMPLIANT"`.

Absence kept arriving as a clean result through three different mechanisms, which is what
makes this a class rather than a bug: Python coercion, an empty iteration, and SQL
three-valued logic.

WHY A THIRD STATUS. `"ATTENTION_REQUIRED"` would have been wrong for missing data — "your
fleet has a problem" and "we could not check your fleet" send an operator to different
places, and only one of them is about drivers. `INCOMPLETE_DATA` says which.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
import pytest_asyncio

pytestmark = pytest.mark.asyncio

FUTURE = datetime.now(timezone.utc) + timedelta(days=365)


@pytest_asyncio.fixture
async def fleet(admin_sync_url, seeded_orgs):
    """Builds a carrier plus drivers with controllable HOS/medical data."""
    import psycopg2

    conn = psycopg2.connect(admin_sync_url)
    conn.autocommit = True
    created: list[tuple[str, str]] = []

    def make(*, drive_hours=None, medical_cert=FUTURE, drivers: int = 1) -> None:
        carrier_id = uuid4()
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO carriers (id, organization_id, carrier_name, ctpat_certified, "
                "ctpat_expires_at, insurance_on_file, insurance_expires_at, is_active) "
                "VALUES (%s, %s, %s, true, %s, true, %s, true)",
                (str(carrier_id), str(seeded_orgs["org_a_id"]),
                 f"C-{carrier_id.hex[:6]}", FUTURE, FUTURE),
            )
            created.append(("carriers", str(carrier_id)))
            for i in range(drivers):
                driver_id = uuid4()
                cur.execute(
                    "INSERT INTO drivers (id, organization_id, carrier_id, first_name, "
                    "last_name, hos_drive_hours_today, hos_on_duty_hours_today, "
                    "hos_cycle_hours, medical_cert_expires) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, 20, %s)",
                    (str(driver_id), str(seeded_orgs["org_a_id"]), str(carrier_id),
                     "Dana", f"D{i}", drive_hours,
                     None if drive_hours is None else 4, medical_cert),
                )
                created.append(("drivers", str(driver_id)))

    yield make

    with conn.cursor() as cur:
        for table, row_id in reversed(created):
            cur.execute(f"DELETE FROM {table} WHERE id = %s", (row_id,))
    conn.close()


async def _status(client):
    response = await client.get("/api/v1/logistics/logistics/compliance/summary")
    assert response.status_code == 200, response.text
    return response.json()


class TestTheSetupIsReal:
    async def test_a_fully_reported_compliant_fleet_is_cleared(self, client_a, fleet):
        """Without this, every assertion below is satisfied by an endpoint that never
        returns COMPLIANT at all."""
        fleet(drive_hours=5)
        body = await _status(client_a)
        assert body["overall_status"] == "COMPLIANT", (
            f"a carrier with C-TPAT and a driver reporting 5 hours is not being cleared; "
            f"got {body['overall_status']} — the checks below would mean nothing"
        )


class TestAbsenceIsNotClearance:
    async def test_a_driver_who_never_reported_is_not_cleared(self, client_a, fleet):
        """THE ASSERTION THIS FILE EXISTS FOR. NULL hours do not match `> 11`, so the
        violation count stays zero and the fleet used to read as compliant."""
        fleet(drive_hours=None)
        body = await _status(client_a)
        assert body["overall_status"] != "COMPLIANT", (
            "a driver with no reported hours was folded into a clean fleet — SQL "
            "discards UNKNOWN exactly as it discards FALSE"
        )

    async def test_it_says_the_data_is_incomplete_rather_than_wrong(
        self, client_a, fleet
    ):
        """Not ATTENTION_REQUIRED: that sends an operator looking for a driver problem
        when the problem is a missing record."""
        fleet(drive_hours=None)
        body = await _status(client_a)
        assert body["overall_status"] == "INCOMPLETE_DATA"
        assert body["driver_compliance"]["unassessable_drivers"] >= 1

    async def test_a_missing_medical_certificate_counts_as_unassessable(
        self, client_a, fleet
    ):
        fleet(drive_hours=5, medical_cert=None)
        body = await _status(client_a)
        assert body["overall_status"] == "INCOMPLETE_DATA"
        assert body["driver_compliance"]["unassessable_drivers"] >= 1

    async def test_a_fleet_with_no_drivers_is_not_cleared(self, client_a, fleet):
        fleet(drivers=0)
        body = await _status(client_a)
        assert body["driver_compliance"]["total_drivers"] == 0
        assert body["overall_status"] == "INCOMPLETE_DATA"


class TestARealViolationStillReadsAsOne:
    async def test_an_over_hours_driver_requires_attention(self, client_a, fleet):
        """The opposite failure: routing every imperfect fleet to INCOMPLETE_DATA would
        satisfy the tests above and bury genuine violations."""
        fleet(drive_hours=12)
        body = await _status(client_a)
        assert body["overall_status"] == "ATTENTION_REQUIRED", (
            "a driver over the 11-hour limit must read as a violation, not as missing data"
        )
        assert body["driver_compliance"]["hos_violations_today"] >= 1


class TestAGradeIsAlsoAVerdict:
    """`efficiency_grade` failed the same way, in the opposite direction.

    With no shipments in the period `on_time_percent` is 0, which is below every
    threshold, so the grade came out **"D"** — a failing mark awarded for a week with
    nothing to deliver. Pessimism from absence is no more true than optimism from it;
    both pass judgement on data that does not exist.
    """

    async def test_a_period_with_no_shipments_is_not_graded_d(self, client_a):
        response = await client_a.get(
            "/api/v1/logistics/logistics/delivery-efficiency", params={"days": 1}
        )
        assert response.status_code == 200, response.text
        body = response.json()
        if body["total_delivered_shipments"]:
            pytest.skip("shipments exist in this window; the empty case is not exercised")
        assert body["efficiency_grade"] is None, (
            f"a period with no deliveries was graded {body['efficiency_grade']!r}"
        )
        assert body["graded"] is False

    async def test_the_counts_are_still_reported(self, client_a):
        """Withholding the grade must not withhold the figures it was derived from."""
        body = (
            await client_a.get(
                "/api/v1/logistics/logistics/delivery-efficiency", params={"days": 1}
            )
        ).json()
        assert "total_delivered_shipments" in body
        assert "on_time_percent" in body

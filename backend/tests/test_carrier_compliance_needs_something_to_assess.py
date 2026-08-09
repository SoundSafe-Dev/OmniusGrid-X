"""A carrier with no drivers on file is not a compliant carrier.

`get_carrier_compliance_summary` counted HOS violations by looping over the carrier's
drivers and returned:

    'overall_compliant': ctpat_certified and insurance_on_file and hos_violations == 0

`hos_violations == 0` is **trivially true when there are no drivers**, so a carrier whose
driver records had never been entered — a new carrier, a failed sync, a partial
migration — was cleared on Hours of Service. Zero violations found among zero drivers is
not a finding; it is the absence of one, and HOS is DOT-regulated.

THE SAME DEFECT EXISTED ON THE FRONTEND, on the same data, and was found first: the
transportation page computed `drivers.filter(d => d.hosDriveHoursRemaining === 0).length
=== 0` and rendered a **green checkmark** reading "No HOS violations detected" whenever
the drivers query failed, because a failed query also yields an empty list. One is an
empty table and the other is an empty response, and both produced clearance.

The verdict now requires that something was actually assessed, and says so in
`drivers_assessed` rather than leaving the reader to infer it from `total_drivers`.

WHAT IS DELIBERATELY UNCHANGED. The C-TPAT and insurance checks are untouched: those read
fields on the carrier itself, which either hold a valid date or do not. Emptiness is only
ambiguous where a COUNT stands in for an inspection.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
import pytest_asyncio

pytestmark = pytest.mark.asyncio

FUTURE = datetime.now(timezone.utc) + timedelta(days=365)


@pytest_asyncio.fixture
async def carrier_factory(admin_sync_url, seeded_orgs):
    """Creates carriers (and optionally drivers) and cleans them up."""
    import psycopg2

    conn = psycopg2.connect(admin_sync_url)
    conn.autocommit = True
    created: list[tuple[str, str]] = []

    def make(*, drivers: int, drive_hours: float = 2.0, medical_cert=FUTURE) -> str:
        """`drive_hours` is hours ALREADY DRIVEN today — the model tracks consumption,
        not remaining time, and `check_compliance` compares it against
        MAX_DRIVE_HOURS_DAY. Assuming a `hos_drive_hours_remaining` column cost a run."""
        carrier_id = uuid4()
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO carriers (id, organization_id, carrier_name, ctpat_certified, "
                "ctpat_expires_at, insurance_on_file, insurance_expires_at) "
                "VALUES (%s, %s, %s, true, %s, true, %s)",
                (str(carrier_id), str(seeded_orgs["org_a_id"]),
                 f"Carrier {carrier_id.hex[:8]}", FUTURE, FUTURE),
            )
            for i in range(drivers):
                driver_id = uuid4()
                # A medical certificate is supplied by default. Without one the driver
                # is UNASSESSABLE under the rule this file tests, which is exactly the
                # point — the first version of this fixture omitted it and the positive
                # control started failing the moment that rule landed.
                cur.execute(
                    "INSERT INTO drivers (id, organization_id, carrier_id, first_name, "
                    "last_name, hos_drive_hours_today, hos_on_duty_hours_today, "
                    "hos_cycle_hours, medical_cert_expires) "
                    "VALUES (%s, %s, %s, %s, %s, %s, 4, 20, %s)",
                    (str(driver_id), str(seeded_orgs["org_a_id"]), str(carrier_id),
                     "Dana", f"Driver{i}", drive_hours, medical_cert),
                )
                created.append(("drivers", str(driver_id)))
        created.append(("carriers", str(carrier_id)))
        return str(carrier_id)

    yield make

    with conn.cursor() as cur:
        for table, row_id in created:
            cur.execute(f"DELETE FROM {table} WHERE id = %s", (row_id,))
    conn.close()


async def _summary(client, carrier_id):
    response = await client.get(f"/api/v1/transportation/carriers/{carrier_id}/compliance")
    assert response.status_code == 200, response.text
    return response.json()


class TestTheSetupIsReal:
    """If a fully-staffed compliant carrier does not come back compliant, every
    assertion below passes for the wrong reason."""

    async def test_a_staffed_compliant_carrier_is_cleared(self, client_a, carrier_factory):
        body = await _summary(client_a, carrier_factory(drivers=2))
        assert body["overall_compliant"] is True, (
            "a carrier with valid C-TPAT, insurance and two compliant drivers is not "
            "being cleared; the check below cannot mean anything"
        )
        assert body["drivers_assessed"] is True


class TestEmptinessIsNotClearance:
    async def test_a_carrier_with_no_drivers_is_not_cleared(self, client_a, carrier_factory):
        """THE ASSERTION THIS FILE EXISTS FOR. Zero violations among zero drivers."""
        body = await _summary(client_a, carrier_factory(drivers=0))
        assert body["overall_compliant"] is False, (
            "a carrier with no drivers on file was cleared on Hours of Service — the "
            "violation count is zero because nothing was inspected"
        )

    async def test_it_says_that_nothing_was_assessed(self, client_a, carrier_factory):
        """`overall_compliant: false` alone reads as "this carrier has a problem". The
        reason has to be legible, or the next reader files a ticket against the wrong
        thing."""
        body = await _summary(client_a, carrier_factory(drivers=0))
        assert body["drivers_assessed"] is False
        assert body["driver_compliance"]["total_drivers"] == 0

    async def test_the_carrier_level_checks_are_still_reported(
        self, client_a, carrier_factory
    ):
        """C-TPAT and insurance read fields on the carrier itself, which are present or
        absent regardless of headcount. Withholding them would hide real information
        because a different check could not run."""
        body = await _summary(client_a, carrier_factory(drivers=0))
        assert body["ctpat_status"]["is_valid"] is True
        assert body["insurance_status"]["is_valid"] is True


class TestARealViolationIsStillAViolation:
    async def test_a_driver_out_of_hours_fails_the_carrier(self, client_a, carrier_factory):
        """The opposite failure: a fix that made everything non-compliant would satisfy
        the empty case and destroy the feature."""
        body = await _summary(client_a, carrier_factory(drivers=1, drive_hours=12.0))
        assert body["drivers_assessed"] is True
        assert body["overall_compliant"] is False
        assert body["driver_compliance"]["hos_violations"] >= 1


class TestAnUnassessableDriverIsNotACompliantOne:
    """The root of the carrier-level defect, one level down.

    `check_compliance` coerced every HOS column with `float(x or 0)`, so a driver who had
    never reported turned into one who had driven zero hours — no violations, therefore
    compliant. The medical-certificate check was worse: both of its branches were guarded
    on the field being SET, so a driver with **no certificate on file** produced neither a
    violation nor a warning and came back clean. A current medical certificate is a
    condition of driving; its absence is a finding, not the lack of one.
    """

    async def test_a_driver_with_no_medical_certificate_is_not_cleared(
        self, client_a, carrier_factory
    ):
        body = await _summary(client_a, carrier_factory(drivers=1, medical_cert=None))
        assert body["overall_compliant"] is False, (
            "a driver with no medical certificate on file was reported compliant"
        )

    async def test_the_carrier_reports_what_it_could_not_judge(
        self, client_a, carrier_factory
    ):
        body = await _summary(client_a, carrier_factory(drivers=1, medical_cert=None))
        assert body["driver_compliance"]["unassessable_drivers"] == 1
        assert body["drivers_assessed"] is False

    async def test_an_unassessable_driver_is_not_counted_as_a_violation(
        self, client_a, carrier_factory
    ):
        """Trading a false clearance for a false accusation is not a fix. An operator
        chasing a phantom HOS breach stops trusting the number in both directions."""
        body = await _summary(client_a, carrier_factory(drivers=1, medical_cert=None))
        assert body["driver_compliance"]["hos_violations"] == 0

    async def test_an_unassessable_driver_is_not_counted_as_compliant_either(
        self, client_a, carrier_factory
    ):
        """`compliant_drivers` was `total - violations`, which put the unjudged drivers
        on the compliant side of the ledger — the same error one level up."""
        body = await _summary(client_a, carrier_factory(drivers=1, medical_cert=None))
        assert body["driver_compliance"]["compliant_drivers"] == 0

"""Four figures on the maintenance costs tab were invented in the client. Now they are computed.

`/api/v1/maintenance/costs` sent exactly two numbers — `ytdTotal` and `byCategory` — while the
TypeScript declared six. The client filled the gap:

  * `monthlyAverage` was `ytd / 12`, computed in January as readily as in December, so a fleet
    three weeks into the year saw a twelfth of its spend labelled as a monthly average;
  * `costPerVehicle` and `upcomingEstimated` were hardcoded zeros, the second rendered in a
    highlighted box reading "Upcoming (Est.) $0";
  * `monthlyBreakdown` was a required array the server never sent, so the chart drew nothing.

A previous pass made all four optional and the panel stopped rendering them. That removed the
false figures and left four blank rows — correct, and not the end of the job. Every one of them
is a fact about data this endpoint already had or could reach with one count, so they are
computed server-side now.

WHAT THIS FILE PINS is the arithmetic, not the presence. A test that only checks the keys exist
passes just as well for `ytd / 12`.

THE DISTINCTION THAT MATTERS in three of the four: `None` and `0.00` are different answers.
An empty fleet has no cost per vehicle — not a cost of zero. Outstanding work that nobody has
costed has no estimate — not an estimate of zero, which is what the highlighted box claimed. A
month in which nothing was repaired, on the other hand, really did cost zero, and that one IS
a number.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.api.fleet_logistics import summarize_maintenance


class _Order:
    def __init__(self, cost, completed_at, category=None, status="completed"):
        self.cost = cost
        self.completed_at = completed_at
        self.category = category
        self.status = status


class _Schedule:
    def __init__(self, estimated_cost=None, status="scheduled", due_date=None):
        self.estimated_cost = estimated_cost
        self.status = status
        self.due_date = due_date


def _at(year, month, day=15):
    return datetime(year, month, day, tzinfo=timezone.utc)


class TestTheMonthlyAverageDividesByMonthsElapsed:
    def test_march_divides_by_three(self):
        """`ytd / 12` was the client's formula. In March it reported a quarter of the truth."""
        now = _at(2026, 3)
        orders = [_Order(300.0, _at(2026, 1)), _Order(300.0, _at(2026, 2)),
                  _Order(300.0, _at(2026, 3))]
        summary = summarize_maintenance([], orders, now=now)

        assert summary["ytdCosts"] == 900.0
        assert summary["monthlyAverage"] == 300.0, (
            "900 spent over three elapsed months is 300/month; ytd/12 would say 75"
        )

    def test_december_divides_by_twelve(self):
        """The control: in December the old formula was right, so a test written only in
        December would have found nothing."""
        summary = summarize_maintenance([], [_Order(1200.0, _at(2026, 6))], now=_at(2026, 12))
        assert summary["monthlyAverage"] == 100.0

    def test_no_spend_averages_zero_not_an_error(self):
        summary = summarize_maintenance([], [], now=_at(2026, 5))
        assert summary["monthlyAverage"] == 0.0
        assert summary["ytdCosts"] == 0.0


class TestTheMonthlyBreakdownCoversTheElapsedYear:
    def test_every_elapsed_month_is_present_even_at_zero(self):
        """A month in which nothing was repaired cost nothing — that is a number, not a gap.
        Omitting it draws a shorter year and moves every bar."""
        summary = summarize_maintenance(
            [], [_Order(500.0, _at(2026, 1)), _Order(250.0, _at(2026, 4))], now=_at(2026, 4)
        )
        assert summary["monthlyBreakdown"] == [
            {"month": "2026-01", "cost": 500.0},
            {"month": "2026-02", "cost": 0.0},
            {"month": "2026-03", "cost": 0.0},
            {"month": "2026-04", "cost": 250.0},
        ]

    def test_it_does_not_run_past_the_current_month(self):
        """Eight empty months at the end of a chart read as a fleet that stopped spending."""
        summary = summarize_maintenance([], [_Order(100.0, _at(2026, 2))], now=_at(2026, 4))
        assert [row["month"] for row in summary["monthlyBreakdown"]] == [
            "2026-01", "2026-02", "2026-03", "2026-04"
        ]

    def test_several_repairs_in_one_month_are_summed(self):
        summary = summarize_maintenance(
            [], [_Order(10.5, _at(2026, 2, 3)), _Order(20.25, _at(2026, 2, 20))], now=_at(2026, 2)
        )
        assert summary["monthlyBreakdown"][-1] == {"month": "2026-02", "cost": 30.75}

    def test_last_years_repairs_are_not_counted(self):
        """`ytd` is year-to-date, and the breakdown is keyed by month alone — a December repair
        from last year lands in month 12 unless the year is checked."""
        summary = summarize_maintenance(
            [], [_Order(999.0, _at(2025, 2)), _Order(10.0, _at(2026, 2))], now=_at(2026, 3)
        )
        assert summary["ytdCosts"] == 10.0
        assert summary["monthlyBreakdown"] == [
            {"month": "2026-01", "cost": 0.0},
            {"month": "2026-02", "cost": 10.0},
            {"month": "2026-03", "cost": 0.0},
        ]


class TestUpcomingEstimatedDistinguishesNoneFromZero:
    def test_it_sums_the_outstanding_estimates(self):
        summary = summarize_maintenance(
            [_Schedule(400.0), _Schedule(150.5)], [], now=_at(2026, 3)
        )
        assert summary["upcomingEstimated"] == 550.5

    def test_completed_work_is_not_upcoming(self):
        summary = summarize_maintenance(
            [_Schedule(400.0, status="completed"), _Schedule(60.0)], [], now=_at(2026, 3)
        )
        assert summary["upcomingEstimated"] == 60.0

    def test_nothing_costed_is_none_not_zero(self):
        """THE ASSERTION THIS CLASS EXISTS FOR. The panel rendered a highlighted box reading
        "Upcoming (Est.) $0" for a fleet whose upcoming work simply had no estimate against it.
        Those are different facts and an operator acts on them differently."""
        summary = summarize_maintenance([_Schedule(None), _Schedule(None)], [], now=_at(2026, 3))
        assert summary["upcomingEstimated"] is None

    def test_no_schedules_at_all_is_also_none(self):
        assert summarize_maintenance([], [], now=_at(2026, 3))["upcomingEstimated"] is None

    def test_an_estimate_of_zero_is_reported_as_zero(self):
        """The control on the two above: an outstanding schedule explicitly costed at nothing
        is a real zero, and collapsing it to `None` would be the same error inverted."""
        summary = summarize_maintenance([_Schedule(0.0)], [], now=_at(2026, 3))
        assert summary["upcomingEstimated"] == 0.0


@pytest.mark.asyncio
class TestTheEndpointReturnsWhatItComputes:
    async def test_cost_per_vehicle_needs_the_fleet_size(self, app, client_a, admin_sync_url,
                                                         seeded_orgs):
        """`costPerVehicle` cannot come from repair orders: a vehicle with no repairs this year
        has no row among them, and it is exactly the vehicle that makes the average meaningful.
        Two vehicles and 1,000 of repairs is 500 each — not 1,000, which is what dividing by
        the number of REPAIRED vehicles would give."""
        import uuid

        import psycopg2

        org_a = str(seeded_orgs["org_a_id"])
        now = datetime.now(timezone.utc)
        conn = psycopg2.connect(admin_sync_url)
        conn.autocommit = True
        try:
            with conn.cursor() as cur:
                for plate in ("FLEET-1", "FLEET-2"):
                    cur.execute(
                        "INSERT INTO vehicles (id, organization_id, vehicle_number) "
                        "VALUES (%s, %s, %s)",
                        (str(uuid.uuid4()), org_a, plate),
                    )
                # Only ONE of the two vehicles has any repair against it.
                cur.execute(
                    "INSERT INTO repair_orders "
                    "(id, organization_id, vehicle_id, title, status, cost, category, "
                    " completed_at) "
                    "VALUES (%s, %s, %s, 'Clutch', 'completed', 1000, 'drivetrain', %s)",
                    (str(uuid.uuid4()), org_a, str(uuid.uuid4()), now),
                )
        finally:
            conn.close()

        resp = await client_a.get("/api/v1/maintenance/costs")
        assert resp.status_code == 200, resp.text
        body = resp.json()

        assert body["ytdTotal"] == 1000.0
        assert body["costPerVehicle"] == 500.0, (
            f"expected 1000 across a fleet of 2; got {body['costPerVehicle']}"
        )
        assert body["byCategory"] == {"drivetrain": 1000.0}
        assert body["monthlyBreakdown"], "the chart's data is still absent"
        assert body["monthlyBreakdown"][-1]["month"] == f"{now.year}-{now.month:02d}"

    async def test_an_empty_fleet_has_no_cost_per_vehicle(self, app, client_b, seeded_orgs):
        """Org B has no vehicles. Zero would read as "we spend nothing per vehicle"; the real
        answer is that the question has no denominator. It must not be a division by zero
        either, which is what made this a hardcoded 0 in the first place."""
        resp = await client_b.get("/api/v1/maintenance/costs")
        assert resp.status_code == 200, resp.text
        assert resp.json()["costPerVehicle"] is None

    async def test_the_endpoint_is_tenant_scoped(self, app, client_a, client_b, admin_sync_url,
                                                 seeded_orgs):
        """These four tables carry `organization_id` and have no row-level security, so the
        explicit filter is the only thing scoping them — worth asserting on a figure that is
        now an average, where one leaked row moves every number on the tab."""
        import uuid

        import psycopg2

        conn = psycopg2.connect(admin_sync_url)
        conn.autocommit = True
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO repair_orders "
                    "(id, organization_id, vehicle_id, title, status, cost, completed_at) "
                    "VALUES (%s, %s, %s, 'A only', 'completed', 777, %s)",
                    (
                        str(uuid.uuid4()), str(seeded_orgs["org_a_id"]), str(uuid.uuid4()),
                        datetime.now(timezone.utc),
                    ),
                )
        finally:
            conn.close()

        a_total = (await client_a.get("/api/v1/maintenance/costs")).json()["ytdTotal"]
        b_total = (await client_b.get("/api/v1/maintenance/costs")).json()["ytdTotal"]
        assert a_total >= 777.0
        assert b_total == 0.0

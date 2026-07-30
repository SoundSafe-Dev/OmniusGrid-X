"""The detention banner said "$" and "N/A excess" for a trailer that was costing money.

`/api/v1/yard/detention-alerts` is the yard's exposure banner: it appears only when a trailer
is inside the warning window or already accruing charges — which is to say, only when it
matters. It rendered four things and three of them were never sent.

  * `alert.carrierName` and `alert.location` — undefined, so the subtitle was a bare " • ";
  * `alert.estimatedCost` — undefined, so the figure read "$" with no number;
  * `alert.excessMinutes` — undefined, and `formatDuration(undefined)` returns 'N/A', so the
    row read "N/A excess";
  * `alert.id` — undefined, used as a React `key`, so every row shared one.

`excessMinutes` is the only one the wire-vocabulary sweep reported. The others are named by
OTHER tables — `carrierName`, `location` and `estimatedCost` all exist elsewhere in the tree —
so a global vocabulary credits them and the sweep sees nothing. Rule 34, and the reason this
interface needed reading against its own endpoint.

The numbers were all there under different names (`detention_minutes`, `current_charge`,
`elapsed_minutes`, `free_minutes`); the identifying details were genuinely absent and are real
columns on the row the loop already holds. So the fix is the two halves this sweep keeps
alternating between: rename the client to the wire, and make the server send what it has.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

pytestmark = pytest.mark.asyncio

#: Well past the free window, so the trailer is in "detention" rather than merely at risk.
HOURS_ON_YARD = 6


def _seed(admin_sync_url, org_id, *, hours_ago=HOURS_ON_YARD):
    import psycopg2

    ids = {k: str(uuid.uuid4()) for k in ("carrier", "trailer", "fresh_trailer")}
    check_in = datetime.now(timezone.utc) - timedelta(hours=hours_ago)

    conn = psycopg2.connect(admin_sync_url)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO carriers (id, organization_id, carrier_name) VALUES (%s, %s, %s)",
                (ids["carrier"], org_id, "Swift Transportation"),
            )
            cur.execute(
                "INSERT INTO yard_trailers (id, organization_id, trailer_number, carrier_id, "
                "status, yard_location, license_plate, check_in_at) "
                "VALUES (%s, %s, 'TRL-9001', %s, 'checked_in', 'ZONE-A-05', 'GHI-3456', %s)",
                (ids["trailer"], org_id, ids["carrier"], check_in),
            )
            # Just arrived: comfortably inside free time, so it must NOT raise an alert.
            cur.execute(
                "INSERT INTO yard_trailers (id, organization_id, trailer_number, carrier_id, "
                "status, yard_location, license_plate, check_in_at) "
                "VALUES (%s, %s, 'TRL-9002', %s, 'checked_in', 'ZONE-B-01', 'JKL-7890', %s)",
                (ids["fresh_trailer"], org_id, ids["carrier"],
                 datetime.now(timezone.utc) - timedelta(minutes=1)),
            )
    finally:
        conn.close()
    return ids


async def _alerts(client):
    resp = await client.get("/api/v1/yard/detention-alerts")
    assert resp.status_code == 200, resp.text
    return resp.json()


class TestTheAlertSaysWhichTrailerAndWhere:
    async def test_it_names_the_carrier_the_location_and_the_plate(
        self, app, client_a, admin_sync_url, seeded_orgs
    ):
        """THE ASSERTION THIS FILE EXISTS FOR. An operator reads this banner to go and move a
        specific trailer; its whole value is saying which one and where."""
        _seed(admin_sync_url, str(seeded_orgs["org_a_id"]))
        alerts = await _alerts(client_a)

        assert len(alerts) == 1, f"expected one trailer in detention, got {alerts}"
        alert = alerts[0]
        assert alert["carrier_name"] == "Swift Transportation"
        assert alert["yard_location"] == "ZONE-A-05"
        assert alert["license_plate"] == "GHI-3456"

    async def test_the_numbers_are_still_there(
        self, app, client_a, admin_sync_url, seeded_orgs
    ):
        """The control on the enrichment: adding three keys must not disturb the arithmetic
        that was already correct. Six hours on the yard against a two-hour free window is four
        hours of detention, and the charge follows from the rate."""
        _seed(admin_sync_url, str(seeded_orgs["org_a_id"]))
        alert = (await _alerts(client_a))[0]

        assert alert["status"] == "detention"
        assert alert["detention_minutes"] == pytest.approx(240, abs=2)
        assert alert["elapsed_minutes"] == pytest.approx(360, abs=2)
        assert alert["current_charge"] > 0
        assert alert["free_minutes"] > 0

    async def test_a_trailer_inside_free_time_raises_nothing(
        self, app, client_a, admin_sync_url, seeded_orgs
    ):
        """The control on "expected one alert" above — with every trailer alerting, that
        assertion would be about the seed rather than about the window."""
        _seed(admin_sync_url, str(seeded_orgs["org_a_id"]))
        numbers = {a["trailer_number"] for a in await _alerts(client_a)}
        assert "TRL-9002" not in numbers

    async def test_a_trailer_with_nothing_recorded_reports_null_not_a_guess(
        self, app, client_a, admin_sync_url, seeded_orgs
    ):
        """`yard_location`, `license_plate` and the carrier are all nullable. An unlabelled
        trailer must come back null so the banner can omit the line, rather than '' or a
        placeholder that reads like a real location."""
        import psycopg2

        org_a = str(seeded_orgs["org_a_id"])
        bare = str(uuid.uuid4())
        conn = psycopg2.connect(admin_sync_url)
        conn.autocommit = True
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO yard_trailers (id, organization_id, trailer_number, status, "
                    "check_in_at) VALUES (%s, %s, 'TRL-BARE', 'checked_in', %s)",
                    (bare, org_a, datetime.now(timezone.utc) - timedelta(hours=HOURS_ON_YARD)),
                )
        finally:
            conn.close()

        alert = next(a for a in await _alerts(client_a) if a["trailer_number"] == "TRL-BARE")
        assert alert["yard_location"] is None
        assert alert["license_plate"] is None
        assert alert["carrier_name"] is None

    async def test_the_enrichment_follows_the_right_trailer(
        self, app, client_a, admin_sync_url, seeded_orgs
    ):
        """The alerts are sorted by exposure AFTER enrichment, and the enrichment zips two
        lists. If the sort ran first, or the lists diverged, every row would carry another
        trailer's plate and location — which is worse than the blank it replaced, because it
        sends someone to the wrong bay."""
        import psycopg2

        org_a = str(seeded_orgs["org_a_id"])
        conn = psycopg2.connect(admin_sync_url)
        conn.autocommit = True
        try:
            with conn.cursor() as cur:
                for number, plate, location, hours in (
                    ("TRL-LOW", "AAA-1111", "ZONE-LOW", 3),
                    ("TRL-HIGH", "ZZZ-9999", "ZONE-HIGH", 12),
                ):
                    cur.execute(
                        "INSERT INTO yard_trailers (id, organization_id, trailer_number, "
                        "status, yard_location, license_plate, check_in_at) "
                        "VALUES (%s, %s, %s, 'checked_in', %s, %s, %s)",
                        (str(uuid.uuid4()), org_a, number, location, plate,
                         datetime.now(timezone.utc) - timedelta(hours=hours)),
                    )
        finally:
            conn.close()

        by_number = {a["trailer_number"]: a for a in await _alerts(client_a)}
        assert by_number["TRL-LOW"]["license_plate"] == "AAA-1111"
        assert by_number["TRL-LOW"]["yard_location"] == "ZONE-LOW"
        assert by_number["TRL-HIGH"]["license_plate"] == "ZZZ-9999"
        assert by_number["TRL-HIGH"]["yard_location"] == "ZONE-HIGH"


class TestItIsTenantScoped:
    async def test_another_tenant_sees_no_alerts(
        self, app, client_a, client_b, admin_sync_url, seeded_orgs
    ):
        _seed(admin_sync_url, str(seeded_orgs["org_a_id"]))
        assert await _alerts(client_b) == []

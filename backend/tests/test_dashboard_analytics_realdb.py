"""The five `/api/v1/dashboard/*` analytics routes had no test at all.

They back the dashboard's trend charts — alarms by severity, throughput, availability, the
health histogram, and the worst-N drill list — and `dashboardAnalytics.ts` calls every one of
them. A five-route surface the landing page depends on, with nothing asserting its arithmetic.

WHAT THIS FILE ASSERTS, and it is deliberately not "does it return 200". The write-surface walk
already proves nothing 5xxs. What was unproven is that the numbers mean anything:

  * an alarm outside the window is not counted, and one inside it is;
  * the tenant filter holds. These reach the tenant by JOINING `assets`, which is a different
    scoping path from the handlers that filter a column directly — and for alarms it is
    belt-and-braces, since `alarms.organization_id` is NOT NULL and carries it too. Asserted
    rather than assumed, because "there are two ways it could be right" is not evidence that
    either is;
  * the buckets are the ones asked for, and an unknown bucket is a 400 rather than a silent
    fallback to a different resolution than the caller believes they are seeing;
  * `assets/at-risk` is sorted WORST first, since a list whose whole purpose is triage is
    useless — and quietly so — if it is reversed.

THE EMPTY-FLEET CASES MATTER MOST HERE. Every one of these endpoints answers with zero rows for
an organisation with no assets, and this codebase's recurring defect is a zero that reads as a
measurement. What is pinned is that the counts are honestly zero AND that the response still
says how many assets it looked at, so the client can tell "nothing happened" from "nothing was
examined".
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

pytestmark = pytest.mark.asyncio


def _seed_asset(admin_sync_url, org_id, name="CNC-1"):
    """An asset needs a workcell and an asset type; `seeded_orgs` already made the workcell."""
    import psycopg2

    asset_id = str(uuid.uuid4())
    type_id = str(uuid.uuid4())
    conn = psycopg2.connect(admin_sync_url)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id FROM workcells WHERE organization_id = %s LIMIT 1", (org_id,)
            )
            workcell_id = cur.fetchone()[0]
            # `asset_types` is NOT tenant-scoped — no organization_id column. Worth noting
            # rather than working around silently: it means a type is shared platform-wide,
            # which is a deliberate schema choice and not something these endpoints filter on.
            cur.execute(
                "INSERT INTO asset_types (id, name, category) VALUES (%s, %s, 'machining')",
                (type_id, f"type-{type_id[:8]}"),
            )
            cur.execute(
                "INSERT INTO assets (id, organization_id, workcell_id, asset_type_id, name, "
                "is_active) VALUES (%s, %s, %s, %s, %s, true)",
                (asset_id, org_id, workcell_id, type_id, name),
            )
    finally:
        conn.close()
    return asset_id


def _seed_alarm(admin_sync_url, org_id, asset_id, *, severity, hours_ago):
    import psycopg2

    conn = psycopg2.connect(admin_sync_url)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(
                # `alarms.organization_id` is NOT NULL, so alarms carry the tenant directly —
                # the handler's join to `assets` is belt-and-braces rather than the only path.
                "INSERT INTO alarms (id, organization_id, asset_id, alarm_code, severity, "
                "message, occurred_at, is_active, is_acknowledged) "
                "VALUES (%s, %s, %s, 'SEED-001', %s, 'seeded', %s, true, false)",
                (str(uuid.uuid4()), org_id, asset_id, severity,
                 datetime.now(timezone.utc) - timedelta(hours=hours_ago)),
            )
    finally:
        conn.close()


def _alarm_total(body: dict) -> int:
    """Every alarm in the response, across buckets and severities.

    KEYED ON `series`, and the first version of this file said `body.get("points", [])` — a
    field the endpoint does not return. `.get` with a default made that an empty list rather
    than a KeyError, so the two NEGATIVE tests below ("outside the window", "another tenant")
    passed over nothing and proved nothing. Only the positive test failed, which is the one
    piece of luck in it: a suite of three where the assertions disagree is how the vacuous one
    gets found.
    """
    return sum(
        count
        for point in body["series"]
        for key, count in point.items()
        if isinstance(count, int) and key != "timestamp"
    )


class TestTheAlarmTrendCountsTheRightAlarms:
    async def test_an_alarm_inside_the_window_is_counted(
        self, app, client_a, admin_sync_url, seeded_orgs
    ):
        org_a = str(seeded_orgs["org_a_id"])
        asset = _seed_asset(admin_sync_url, org_a)
        _seed_alarm(admin_sync_url, org_a, asset, severity="critical", hours_ago=2)

        resp = await client_a.get("/api/v1/dashboard/alarms/trend?hours=24")
        assert resp.status_code == 200, resp.text
        body = resp.json()

        total = _alarm_total(body)
        assert total >= 1, f"the seeded alarm was not counted: {body}"

    async def test_an_alarm_outside_the_window_is_not(
        self, app, client_a, admin_sync_url, seeded_orgs
    ):
        """The control on the test above. A handler ignoring its `hours` bound would satisfy
        that one perfectly — and a trend chart that silently widens its window is showing a
        different period than its axis claims.

        WHAT MUTATION TESTING SHOWED, recorded because it is a limit on this assertion rather
        than a strength of it: deleting `Alarm.occurred_at >= start` from the SQL does NOT make
        this fail. The window is enforced twice — once in the query and again in `fill_series`,
        which only emits buckets inside `[start, end]`, so an alarm outside the range has no
        bucket to land in. Removing either half alone is invisible.

        That is defence in depth and the behaviour is right, so this pins the OUTCOME an
        operator sees rather than the mechanism. It would catch both halves being removed; it
        would not catch one. Said plainly so nobody reads it as stronger than it is."""
        org_a = str(seeded_orgs["org_a_id"])
        asset = _seed_asset(admin_sync_url, org_a, name="CNC-old")
        _seed_alarm(admin_sync_url, org_a, asset, severity="critical", hours_ago=300)

        body = (await client_a.get("/api/v1/dashboard/alarms/trend?hours=1")).json()

        total = _alarm_total(body)
        assert total == 0, f"an alarm 300 hours old was counted in a 1-hour window: {body}"

    async def test_another_tenants_alarm_is_not_counted(
        self, app, client_a, client_b, admin_sync_url, seeded_orgs
    ):
        """These endpoints reach the tenant by JOINING assets rather than filtering a column,
        which is worth its own assertion — and `alarms` also carries `organization_id` itself,
        so there are two mechanisms and neither has been checked."""
        org_a = str(seeded_orgs["org_a_id"])
        asset = _seed_asset(admin_sync_url, org_a, name="CNC-a-only")
        _seed_alarm(admin_sync_url, org_a, asset, severity="critical", hours_ago=1)

        body = (await client_b.get("/api/v1/dashboard/alarms/trend?hours=24")).json()

        total = _alarm_total(body)
        assert total == 0, f"org B saw org A's alarms: {body}"

    async def test_an_unknown_bucket_is_a_400(self, app, client_a, seeded_orgs):
        """Not a silent fallback. A chart drawn at a different resolution than the caller asked
        for looks entirely normal — there is no visual tell — so the failure has to be loud."""
        resp = await client_a.get("/api/v1/dashboard/alarms/trend?bucket=fortnight")
        assert resp.status_code == 400, resp.text


class TestTheFleetEndpointsSayWhatTheyLookedAt:
    @pytest.mark.parametrize(
        "path",
        [
            "/api/v1/dashboard/health/distribution",
            "/api/v1/dashboard/assets/at-risk",
            "/api/v1/dashboard/oee/trend",
            # THESE TWO DID NOT REPORT IT, and this parametrisation is what found that. Three
            # of the five endpoints said what they had examined and two did not, so an all-zero
            # alarm trend or throughput series was indistinguishable between a healthy fleet
            # and an organisation with no assets. Both report `asset_count` now.
            "/api/v1/dashboard/throughput",
            "/api/v1/dashboard/alarms/trend",
        ],
    )
    async def test_an_empty_fleet_reports_zero_assets_rather_than_only_zeroes(
        self, app, client_b, path
    ):
        """Org B has no assets. Every one of these answers with zeroes, and a zero that does not
        say how many assets produced it is indistinguishable from a fleet that is running
        perfectly — the defect class this codebase keeps finding.

        `asset_count` is the field that makes the difference, so it is what is asserted."""
        resp = await client_b.get(path)
        assert resp.status_code == 200, resp.text
        body = resp.json()

        assert "asset_count" in body, f"{path} reports figures without saying what it examined"
        assert body["asset_count"] == 0

    async def test_at_risk_is_sorted_worst_first(
        self, app, client_a, admin_sync_url, seeded_orgs
    ):
        """A triage list that is reversed is useless in a way nobody notices: it is still full
        of real assets with real scores, and the operator works the wrong end of it."""
        org_a = str(seeded_orgs["org_a_id"])
        for i in range(3):
            _seed_asset(admin_sync_url, org_a, name=f"CNC-risk-{i}")

        body = (await client_a.get("/api/v1/dashboard/assets/at-risk?limit=10")).json()
        scores = [item["health_score"] for item in body["items"]]

        assert scores == sorted(scores), f"at-risk is not worst-first: {scores}"

    async def test_the_limit_is_honoured(self, app, client_a, admin_sync_url, seeded_orgs):
        org_a = str(seeded_orgs["org_a_id"])
        for i in range(4):
            _seed_asset(admin_sync_url, org_a, name=f"CNC-lim-{i}")

        body = (await client_a.get("/api/v1/dashboard/assets/at-risk?limit=2")).json()

        assert len(body["items"]) <= 2
        assert body["asset_count"] >= len(body["items"]), (
            "asset_count must report the whole fleet examined, not the truncated page — "
            "otherwise the drill list looks like the entire fleet"
        )

    async def test_another_tenants_assets_are_not_in_the_histogram(
        self, app, client_a, client_b, admin_sync_url, seeded_orgs
    ):
        _seed_asset(admin_sync_url, str(seeded_orgs["org_a_id"]), name="CNC-hidden")

        a_body = (await client_a.get("/api/v1/dashboard/health/distribution")).json()
        b_body = (await client_b.get("/api/v1/dashboard/health/distribution")).json()

        assert a_body["asset_count"] >= 1
        assert b_body["asset_count"] == 0

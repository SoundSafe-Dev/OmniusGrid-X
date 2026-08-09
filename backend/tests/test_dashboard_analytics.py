"""Real-DB tests for the fleet-aggregate dashboard endpoints (FS-192).

Covers three things the plain "does it 200" smoke test would miss:
  * tenancy — an aggregate must not sum another org's rows;
  * shape — a sparse window still returns a dense series, so charts don't
    silently change x-axis shape between refreshes;
  * honesty — the OEE trend is availability-only and must say so rather than
    passing itself off as full OEE.
"""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import psycopg2
import pytest


@pytest.fixture
def seeded_asset_type(admin_sync_url) -> str:
    import psycopg2 as pg

    at_id = str(uuid4())
    conn = pg.connect(admin_sync_url)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO asset_types (id, name, category) VALUES (%s, %s, %s)",
                (at_id, f"agg-type-{at_id[:8]}", "production"),
            )
    finally:
        conn.close()
    return at_id


def _insert_asset(admin_sync_url, org_id, workcell_id, asset_type_id, name) -> str:
    """Insert directly (superuser, bypasses RLS) so we control org placement."""
    asset_id = str(uuid4())
    conn = psycopg2.connect(admin_sync_url)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO assets (id, organization_id, workcell_id, asset_type_id,"
                " name, is_active) VALUES (%s, %s, %s, %s, %s, TRUE)",
                (asset_id, str(org_id), str(workcell_id), asset_type_id, name),
            )
    finally:
        conn.close()
    return asset_id


def _insert_alarm(admin_sync_url, asset_id, severity, occurred_at):
    conn = psycopg2.connect(admin_sync_url)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO alarms (id, asset_id, organization_id, alarm_code,"
                " severity, message, is_active, occurred_at)"
                " VALUES (%s, %s, (SELECT organization_id FROM assets WHERE id = %s),"
                " %s, %s, %s, TRUE, %s)",
                (str(uuid4()), asset_id, asset_id, "TEST-1", severity,
                 "test alarm", occurred_at),
            )
    finally:
        conn.close()


def _insert_telemetry(admin_sync_url, asset_id, metric, value, ts):
    conn = psycopg2.connect(admin_sync_url)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO telemetry (time, asset_id, metric_name, value)"
                " VALUES (%s, %s, %s, %s)",
                (ts, asset_id, metric, value),
            )
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_alarms_trend_is_dense_and_tenant_scoped(
    client_a, seeded_orgs, seeded_asset_type, admin_sync_url
):
    now = datetime.now(timezone.utc)
    asset_a = _insert_asset(
        admin_sync_url, seeded_orgs["org_a_id"], seeded_orgs["workcell_a_id"],
        seeded_asset_type, "agg-a",
    )
    asset_b = _insert_asset(
        admin_sync_url, seeded_orgs["org_b_id"], seeded_orgs["workcell_b_id"],
        seeded_asset_type, "agg-b",
    )
    _insert_alarm(admin_sync_url, asset_a, "critical", now - timedelta(minutes=30))
    # Org B's alarm must never appear in Org A's trend.
    _insert_alarm(admin_sync_url, asset_b, "critical", now - timedelta(minutes=30))
    _insert_alarm(admin_sync_url, asset_b, "high", now - timedelta(minutes=30))

    resp = await client_a.get("/api/v1/dashboard/alarms/trend?hours=6&bucket=1hour")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    # Dense: 6h of 1h buckets -> 7 boundaries inclusive.
    assert len(body["series"]) >= 6, body["series"]
    assert all("timestamp" in p and "total" in p for p in body["series"])

    total = sum(p["total"] for p in body["series"])
    assert total == 1, f"expected only org A's single alarm, got {total}: {body}"


@pytest.mark.asyncio
async def test_throughput_sums_part_counters_for_the_org_only(
    client_a, seeded_orgs, seeded_asset_type, admin_sync_url
):
    now = datetime.now(timezone.utc)
    asset_a = _insert_asset(
        admin_sync_url, seeded_orgs["org_a_id"], seeded_orgs["workcell_a_id"],
        seeded_asset_type, "tp-a",
    )
    asset_b = _insert_asset(
        admin_sync_url, seeded_orgs["org_b_id"], seeded_orgs["workcell_b_id"],
        seeded_asset_type, "tp-b",
    )
    _insert_telemetry(admin_sync_url, asset_a, "parts_produced", 100, now - timedelta(minutes=20))
    _insert_telemetry(admin_sync_url, asset_a, "good_parts", 90, now - timedelta(minutes=20))
    _insert_telemetry(admin_sync_url, asset_b, "parts_produced", 500, now - timedelta(minutes=20))

    resp = await client_a.get("/api/v1/dashboard/throughput?hours=6&bucket=1hour")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["totals"]["total_parts"] == 100, body["totals"]
    assert body["totals"]["good_parts"] == 90, body["totals"]
    assert body["totals"]["quality_pct"] == 90.0, body["totals"]


@pytest.mark.asyncio
async def test_throughput_quality_is_null_not_zero_without_counters(
    client_a, seeded_orgs
):
    """No parts reported must read as 'unknown', never as 0% quality."""
    resp = await client_a.get("/api/v1/dashboard/throughput?hours=1&bucket=1hour")
    assert resp.status_code == 200, resp.text
    assert resp.json()["totals"]["quality_pct"] is None


@pytest.mark.asyncio
async def test_oee_trend_declares_itself_availability_only(client_a, seeded_orgs):
    resp = await client_a.get("/api/v1/dashboard/oee/trend?hours=6&bucket=1hour")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # The whole point: this must not masquerade as full three-factor OEE.
    assert body["availability_only"] is True
    assert "series" in body and len(body["series"]) >= 6


@pytest.mark.asyncio
async def test_health_distribution_and_at_risk_are_tenant_scoped(
    client_a, client_b, seeded_orgs, seeded_asset_type, admin_sync_url
):
    _insert_asset(
        admin_sync_url, seeded_orgs["org_a_id"], seeded_orgs["workcell_a_id"],
        seeded_asset_type, "health-a",
    )
    _insert_asset(
        admin_sync_url, seeded_orgs["org_b_id"], seeded_orgs["workcell_b_id"],
        seeded_asset_type, "health-b1",
    )
    _insert_asset(
        admin_sync_url, seeded_orgs["org_b_id"], seeded_orgs["workcell_b_id"],
        seeded_asset_type, "health-b2",
    )

    dist_a = (await client_a.get("/api/v1/dashboard/health/distribution?hours=24")).json()
    dist_b = (await client_b.get("/api/v1/dashboard/health/distribution?hours=24")).json()
    assert dist_a["asset_count"] == 1, dist_a
    assert dist_b["asset_count"] == 2, dist_b
    assert sum(b["count"] for b in dist_a["bands"]) == dist_a["asset_count"]

    at_risk = (await client_a.get("/api/v1/dashboard/assets/at-risk?limit=5")).json()
    assert at_risk["asset_count"] == 1
    names = [i["asset_name"] for i in at_risk["items"]]
    assert "health-a" in names and not any(n.startswith("health-b") for n in names)


@pytest.mark.asyncio
async def test_at_risk_is_ordered_worst_first(
    client_a, seeded_orgs, seeded_asset_type, admin_sync_url
):
    now = datetime.now(timezone.utc)
    healthy = _insert_asset(
        admin_sync_url, seeded_orgs["org_a_id"], seeded_orgs["workcell_a_id"],
        seeded_asset_type, "ok-asset",
    )
    sick = _insert_asset(
        admin_sync_url, seeded_orgs["org_a_id"], seeded_orgs["workcell_a_id"],
        seeded_asset_type, "sick-asset",
    )
    # Alarms drive the health penalty, so the noisy asset must rank worst.
    for i in range(8):
        _insert_alarm(admin_sync_url, sick, "critical", now - timedelta(minutes=5 * i + 1))

    body = (await client_a.get("/api/v1/dashboard/assets/at-risk?hours=24&limit=10")).json()
    scores = [(i["asset_name"], i["health_score"]) for i in body["items"]]
    assert scores == sorted(scores, key=lambda s: s[1]), scores
    assert scores[0][0] == "sick-asset", scores


@pytest.mark.asyncio
async def test_invalid_bucket_is_a_400_not_a_500(client_a, seeded_orgs):
    resp = await client_a.get("/api/v1/dashboard/alarms/trend?bucket=1fortnight")
    assert resp.status_code == 400, resp.text

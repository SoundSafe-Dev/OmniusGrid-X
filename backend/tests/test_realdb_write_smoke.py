"""Real-DB write-path smoke (FS-93): create-then-read core resources on Postgres.

Empty-body probes stop at 422 before touching the database, so insert-time
drift (ORM-nullable vs DB NOT NULL — the ``assets.workcell_id`` class, wrong
column names, broken defaults) only surfaces when a VALID body is written and
read back. This does exactly that for the core CRUD resources.

Uses the session testcontainers TimescaleDB (schema via ``scripts/migrate.py``).
Skips where docker is unavailable.
"""

from __future__ import annotations

from uuid import uuid4

import pytest


from tests._realdb import require_testcontainers
require_testcontainers()  # FS-808: skips on a laptop, FAILS when REQUIRE_REALDB=1


@pytest.fixture
def seeded_asset_type(admin_sync_url) -> str:
    """An asset type to satisfy assets' NOT NULL FK (org-agnostic catalog row)."""
    import psycopg2

    at_id = str(uuid4())
    conn = psycopg2.connect(admin_sync_url)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO asset_types (id, name, category) VALUES (%s, %s, %s)",
                (at_id, f"smoke-type-{at_id[:8]}", "production"),
            )
    finally:
        conn.close()
    return at_id


@pytest.mark.asyncio
async def test_asset_create_then_read(client_a, seeded_orgs, seeded_asset_type):
    org = str(seeded_orgs["org_a_id"])
    body = {
        "name": f"smoke-asset-{uuid4().hex[:8]}",
        "organization_id": org,  # ignored server-side (JWT org wins) but required
        "workcell_id": str(seeded_orgs["workcell_a_id"]),
        "asset_type_id": seeded_asset_type,
    }
    created = await client_a.post("/api/v1/assets/", json=body)
    assert created.status_code in (200, 201), (
        f"asset create failed (insert-time drift class): "
        f"{created.status_code} {created.text[:200]}"
    )
    asset_id = created.json()["id"]

    fetched = await client_a.get(f"/api/v1/assets/{asset_id}")
    assert fetched.status_code == 200, fetched.text[:200]
    assert fetched.json()["name"] == body["name"]

    # The list endpoint returns the FS-82 envelope with a REAL total.
    listed = await client_a.get("/api/v1/assets/")
    assert listed.status_code == 200
    page = listed.json()
    assert set(page) == {"items", "meta"}, f"expected Page envelope, got {list(page)}"
    assert page["meta"]["total"] >= 1


@pytest.mark.asyncio
async def test_alarm_acknowledge_write_path(
    client_a, seeded_orgs, seeded_asset_type, admin_sync_url
):
    """Exercise the alarm mutation the API actually exposes.

    This used to POST /api/v1/alarms/ and assert 200/201, which could never
    pass: there is no alarm-create endpoint and there shouldn't be. Alarms are
    produced by the ingestion pipeline, and the API exposes only acknowledge and
    clear. The test was asserting an invented contract rather than the real
    write path, so it reported 405 forever.

    Seeds the alarm the way ingestion does — a direct insert — then drives the
    real mutation through HTTP.
    """
    import psycopg2

    org = str(seeded_orgs["org_a_id"])
    asset = await client_a.post(
        "/api/v1/assets/",
        json={
            "name": f"smoke-alarm-asset-{uuid4().hex[:6]}",
            "organization_id": org,
            "workcell_id": str(seeded_orgs["workcell_a_id"]),
            "asset_type_id": seeded_asset_type,
        },
    )
    assert asset.status_code in (200, 201), asset.text[:200]
    asset_id = asset.json()["id"]

    # alarms carries no organization_id — it is tenant-scoped through
    # asset_id -> assets.organization_id — and its time column is occurred_at
    # (the table is a hypertable keyed on it).
    alarm_id = str(uuid4())
    conn = psycopg2.connect(admin_sync_url)
    try:
        with conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO alarms (id, asset_id, organization_id, alarm_code,
                                    severity, message, is_active, occurred_at)
                VALUES (%s, %s,
                        (SELECT organization_id FROM assets WHERE id = %s),
                        %s, %s, %s, TRUE, now())
                """,
                (alarm_id, asset_id, asset_id, "SMOKE_TEST", "high",
                 "write-path smoke alarm"),
            )
    finally:
        conn.close()

    listed = await client_a.get("/api/v1/alarms/")
    assert listed.status_code == 200
    page = listed.json()
    assert set(page) == {"items", "meta"}
    assert any(a["alarm_code"] == "SMOKE_TEST" for a in page["items"])

    acked = await client_a.post(
        f"/api/v1/alarms/{alarm_id}/acknowledge",
        json={"comment": "write-path smoke"},  # AlarmAcknowledge body is required
    )
    assert acked.status_code in (200, 204), (
        f"alarm acknowledge failed: {acked.status_code} {acked.text[:200]}"
    )


@pytest.mark.asyncio
async def test_yard_trailer_create_then_read(client_a, seeded_orgs):
    org = str(seeded_orgs["org_a_id"])
    number = f"SMK-{uuid4().hex[:6].upper()}"
    created = await client_a.post(
        "/api/v1/yard/trailers/checkin",
        json={"trailer_number": number, "organization_id": org},
    )
    assert created.status_code in (200, 201), (
        f"trailer check-in failed: {created.status_code} {created.text[:200]}"
    )

    # `params={"organization_id": org}` REMOVED (FS-739). The endpoint never declared
    # that parameter, so it was silently dropped; unknown query parameters are now refused
    # with a 422. Scope has always come from the token, so the call is unchanged in effect.
    inventory = await client_a.get("/api/v1/yard/trailers")
    assert inventory.status_code == 200, inventory.text[:200]
    # FS-99: yard inventory returns the {items, meta} pagination envelope now.
    page = inventory.json()
    assert set(page) == {"items", "meta"}
    assert page["meta"]["total"] >= 1
    assert any(t["trailer_number"] == number for t in page["items"])


@pytest.mark.asyncio
async def test_notification_subscription_create_then_read(client_a, seeded_orgs):
    name = f"smoke-sub-{uuid4().hex[:6]}"
    created = await client_a.post(
        "/api/v1/notifications/subscriptions",
        json={
            "name": name,
            "channel": "webhook",
            "target": "https://example.invalid/hook",
            "min_severity": "critical",
        },
    )
    assert created.status_code in (200, 201), (
        f"subscription create failed: {created.status_code} {created.text[:200]}"
    )

    listed = await client_a.get("/api/v1/notifications/subscriptions")
    assert listed.status_code == 200
    body = listed.json()
    subs = body if isinstance(body, list) else body.get("items", [])
    assert any(s.get("name") == name for s in subs), f"{name} missing from {subs!r:.200}"

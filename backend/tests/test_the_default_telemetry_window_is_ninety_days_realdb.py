"""The default raw-telemetry window, and the tenant boundary it must not cross (FS-816).

WHAT THIS EXISTS TO PIN, and it is as much about a near-miss as about the change.

Raw telemetry retention was believed to be **7 days**, on the strength of
`005_data_retention.sql:22`. That statement is a no-op: `001_init.sql:104` had already
installed a policy at 30 days, and `if_not_exists => TRUE` means "succeed quietly if one
exists" — it does not change the interval. Then `034_historian_retention.sql:210` removed the
global policy entirely and replaced it with `enforce_tenant_historian_retention()`, a
per-tenant row DELETE, because a Timescale chunk holds rows for many organisations and a
global chunk-drop therefore cannot honour a per-tenant window.

**The real default was 30 days, tenant-configurable — and nothing tested it.**

A first attempt at raising the window to 90 reinstated a global
`add_retention_policy('telemetry', INTERVAL '90 days')`. That would have re-broken precisely
what 034 fixed: dropping whole chunks out from under tenants who had configured longer
windows — silent, cross-tenant, irreversible data loss, discovered only when a customer asked
for data they were entitled to. It was caught because `test_migration_chain_hygiene` refused
the migration for an unrelated reason and the investigation went one level deeper.

So this file asserts the three properties that near-miss ran through:

  1. a tenant with NO configured policy gets the 90-day default;
  2. a tenant WITH a configured window keeps it, longer or shorter;
  3. enforcing retention for one organisation deletes nothing belonging to another.

The third is the one the global policy would have broken, and the one no amount of reading
the SQL proves.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit
from uuid import uuid4

import psycopg2
import pytest

from tests._realdb import require_testcontainers

require_testcontainers()  # FS-808: skips on a laptop, FAILS when REQUIRE_REALDB=1

#: The default set by migration 072, in both the column default and the function's COALESCE.
#: The COALESCE is the one that matters: a tenant with no row has no column to default.
DEFAULT_DAYS = 90


def _admin(admin_sync_url):
    conn = psycopg2.connect(admin_sync_url)
    conn.autocommit = True
    return conn


def _asset(cur, org_id, workcell_id) -> str:
    """`assets.workcell_id` is NOT NULL, and the FK is composite on
    (workcell_id, organization_id) — an asset cannot borrow another tenant's workcell."""
    asset_id, type_id = str(uuid4()), str(uuid4())
    cur.execute(
        "INSERT INTO asset_types (id, name, category) VALUES (%s, %s, 'machine')",
        (type_id, f"FS816-{type_id[:8]}"),
    )
    cur.execute(
        "INSERT INTO assets (id, organization_id, asset_type_id, workcell_id, name, is_active)"
        " VALUES (%s, %s, %s, %s, %s, true)",
        (asset_id, str(org_id), type_id, str(workcell_id), f"retention-fixture-{asset_id[:8]}"),
    )
    return asset_id


def _telemetry(cur, asset_id: str, *ages_in_days: int) -> None:
    now = datetime.now(timezone.utc)
    for age in ages_in_days:
        cur.execute(
            """
            INSERT INTO telemetry (time, asset_id, metric_name, value)
            VALUES (%s, %s, 'retention_probe', 1.0)
            """,
            (now - timedelta(days=age), asset_id),
        )


def _count(cur, asset_id: str) -> int:
    cur.execute(
        "SELECT count(*) FROM telemetry WHERE asset_id = %s AND metric_name = 'retention_probe'",
        (asset_id,),
    )
    return cur.fetchone()[0]


def _enforce(cur, org_id) -> int:
    """Run retention for one org, under that org's tenant context.

    The function refuses outright if `app.current_org_id` does not match the argument —
    a deliberate guard, and asserting it here keeps the two from drifting apart.
    """
    cur.execute("SELECT set_config('app.current_org_id', %s, false)", (str(org_id),))
    cur.execute("SELECT enforce_tenant_historian_retention(%s)", (str(org_id),))
    return cur.fetchone()[0]


def test_a_tenant_with_no_policy_keeps_ninety_days(admin_sync_url, seeded_orgs):
    org = seeded_orgs["org_a_id"]
    conn = _admin(admin_sync_url)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM historian_retention_policies WHERE organization_id = %s",
                (str(org),),
            )
            asset = _asset(cur, org, seeded_orgs["workcell_a_id"])
            # Straddling the boundary on both sides, and one well past it.
            _telemetry(cur, asset, 1, 45, 89, 91, 200)
            assert _count(cur, asset) == 5

            deleted = _enforce(cur, org)

            assert _count(cur, asset) == 3, (
                "expected the 91- and 200-day rows to go and the 1/45/89-day rows to stay"
            )
            assert deleted == 2, f"function reported {deleted} deletions, expected 2"
    finally:
        conn.close()


def test_a_tenant_that_configured_its_own_window_is_not_overridden(
    admin_sync_url, seeded_orgs
):
    """The property a global chunk-drop policy destroys. A tenant on 365 days must keep
    a 200-day-old reading even though the platform default would have removed it."""
    org = seeded_orgs["org_a_id"]
    conn = _admin(admin_sync_url)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM historian_retention_policies WHERE organization_id = %s",
                (str(org),),
            )
            cur.execute(
                """
                INSERT INTO historian_retention_policies
                    (id, organization_id, metric_name, hot_retention_days)
                VALUES (%s, %s, '*', 365)
                """,
                (str(uuid4()), str(org)),
            )
            asset = _asset(cur, org, seeded_orgs["workcell_a_id"])
            _telemetry(cur, asset, 200, 400)
            assert _count(cur, asset) == 2

            _enforce(cur, org)

            assert _count(cur, asset) == 1, (
                "a tenant configured for 365 days lost its 200-day-old reading — the "
                "platform default overrode an explicit tenant window"
            )
    finally:
        conn.close()


def test_enforcing_one_tenants_retention_leaves_another_tenants_rows_alone(
    admin_sync_url, seeded_orgs
):
    """THE NEAR-MISS, pinned.

    A global `add_retention_policy('telemetry', ...)` drops whole CHUNKS, and a chunk holds
    rows for every organisation whose data falls in its time range. So a platform-wide
    90-day policy silently deletes a 200-day-old reading belonging to a tenant that
    configured 365 — cross-tenant, irreversible, and invisible until someone asks for data
    they are entitled to. Migration 034 removed exactly that policy for exactly this reason.
    """
    org_a, org_b = seeded_orgs["org_a_id"], seeded_orgs["org_b_id"]
    conn = _admin(admin_sync_url)
    try:
        with conn.cursor() as cur:
            for org in (org_a, org_b):
                cur.execute(
                    "DELETE FROM historian_retention_policies WHERE organization_id = %s",
                    (str(org),),
                )
            asset_a = _asset(cur, org_a, seeded_orgs["workcell_a_id"])
            asset_b = _asset(cur, org_b, seeded_orgs["workcell_b_id"])
            # Both tenants hold a reading far past the default window, in the same chunk.
            _telemetry(cur, asset_a, 200)
            _telemetry(cur, asset_b, 200)

            _enforce(cur, org_a)

            assert _count(cur, asset_a) == 0, "org A's expired row should have gone"
            assert _count(cur, asset_b) == 1, (
                "enforcing retention for org A deleted org B's row. Either the DELETE lost "
                "its organisation predicate, or a global chunk-drop policy has been "
                "reinstated — which is what migration 034 removed and FS-816 nearly "
                "restored."
            )
    finally:
        conn.close()


def test_the_function_refuses_a_mismatched_tenant_context(admin_sync_url, seeded_orgs):
    """`enforce_tenant_historian_retention` raises 42501 when `app.current_org_id` does not
    match its argument. Without that, the scheduled sweep could be pointed at one tenant
    while holding another's context."""
    org_a, org_b = seeded_orgs["org_a_id"], seeded_orgs["org_b_id"]
    conn = _admin(admin_sync_url)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT set_config('app.current_org_id', %s, false)", (str(org_a),))
            with pytest.raises(psycopg2.errors.InsufficientPrivilege):
                cur.execute("SELECT enforce_tenant_historian_retention(%s)", (str(org_b),))
    finally:
        conn.close()


def test_the_declared_config_matches_what_is_enforced(admin_sync_url):
    """`data_retention_config` is descriptive — nothing reads it to drive a policy — which
    is exactly why it drifts. It said 7 days for telemetry while the enforced default was
    30, and both were wrong about the other."""
    conn = _admin(admin_sync_url)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT hot_retention_days FROM data_retention_config WHERE table_name = 'telemetry'"
            )
            row = cur.fetchone()
            assert row, "data_retention_config has no telemetry row"
            assert row[0] == DEFAULT_DAYS, (
                f"data_retention_config says {row[0]} days; the enforced default is "
                f"{DEFAULT_DAYS}. A descriptive table that disagrees with the behaviour is "
                f"how the 7-day belief survived for months."
            )
    finally:
        conn.close()

"""API-level tenant-isolation tests for the alarms endpoints (FS-216).

Why this file exists separately from ``test_tenant_isolation_api.py``: alarms were
NOT protected the way assets and telemetry are, and the reason is structural rather
than a one-line oversight.

``assets`` is ``FORCE ROW LEVEL SECURITY`` with an ``app.current_org_id`` predicate,
so a query that forgets to filter still returns nothing for the wrong tenant.
``alarms`` had **no RLS policy at all** (absent from migrations 011/033) and no
``organization_id`` column — tenancy existed only if the query joined ``assets``.
Five of the six endpoints did not join, so ``get_tenant_db``'s GUC protected nothing
here: org B could read, acknowledge, clear and bulk-acknowledge org A's alarms.

Two changes now cover it, and these tests exist to keep BOTH honest:

* FS-216 scoped every query through ``assets`` (``_org_scoped()`` in the router).
* FS-217 / migration 046 added ``alarms.organization_id`` with FORCE RLS, so a
  future unscoped query returns nothing instead of everything.

Every endpoint is asserted individually — including both write paths and the bulk
path — rather than a representative sample, because the original bug was not one
oversight but the same omission repeated five times.

The non-owner gets 404 rather than 403, matching the existing convention: do not
leak the existence of another tenant's resources.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _seed_asset_type(admin_sync_url: str) -> str:
    import psycopg2

    type_id = str(uuid4())
    conn = psycopg2.connect(admin_sync_url)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO asset_types (id, name, category) VALUES (%s, %s, %s);",
                (type_id, f"AlarmType-{type_id[:8]}", "test"),
            )
    finally:
        conn.close()
    return type_id


def _seed_asset(admin_sync_url: str, org_id, workcell_id, name: str) -> str:
    """Insert an asset directly (superuser, bypasses RLS) for a given org."""
    import psycopg2

    asset_id = str(uuid4())
    asset_type_id = _seed_asset_type(admin_sync_url)
    conn = psycopg2.connect(admin_sync_url)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO assets
                    (id, organization_id, workcell_id, asset_type_id, name, connection_config)
                VALUES (%s, %s, %s, %s, %s, '{}');
                """,
                (asset_id, str(org_id), str(workcell_id), asset_type_id, name),
            )
    finally:
        conn.close()
    return asset_id


def _seed_alarm(
    admin_sync_url: str,
    asset_id: str,
    org_id,
    *,
    severity: str = "critical",
    code: str = "TEMP_HIGH",
    occurred_at: datetime | None = None,
) -> str:
    """Insert an active, unacknowledged alarm against an asset.

    ``org_id`` is required because migration 046 made ``alarms.organization_id``
    NOT NULL. Passing it explicitly (rather than deriving it from the asset here)
    keeps the helper honest about which tenant the row belongs to.
    """
    import psycopg2

    alarm_id = str(uuid4())
    when = occurred_at or (datetime.now(timezone.utc) - timedelta(minutes=5))
    conn = psycopg2.connect(admin_sync_url)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO alarms
                    (id, asset_id, organization_id, alarm_code, severity, message,
                     is_active, is_acknowledged, occurred_at)
                VALUES (%s, %s, %s, %s, %s, %s, TRUE, FALSE, %s);
                """,
                (alarm_id, asset_id, str(org_id), code, severity,
                 f"{code} on {asset_id[:8]}", when),
            )
    finally:
        conn.close()
    return alarm_id


def _read_alarm(admin_sync_url: str, alarm_id: str) -> dict:
    """Read an alarm back with a superuser connection, bypassing RLS."""
    import psycopg2

    conn = psycopg2.connect(admin_sync_url)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT is_acknowledged, is_active, acknowledged_by, cleared_at
                FROM alarms WHERE id = %s;
                """,
                (alarm_id,),
            )
            row = cur.fetchone()
    finally:
        conn.close()
    assert row is not None, f"alarm {alarm_id} vanished"
    return {
        "is_acknowledged": row[0],
        "is_active": row[1],
        "acknowledged_by": row[2],
        "cleared_at": row[3],
    }


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------

class TestAlarmReadIsolation:
    async def test_list_excludes_other_orgs_alarms(
        self, client_a, client_b, admin_sync_url, seeded_orgs
    ):
        """GET /alarms/ had NO organization predicate — it listed every tenant."""
        asset_a = _seed_asset(
            admin_sync_url, seeded_orgs["org_a_id"], seeded_orgs["workcell_a_id"], "AlarmAssetA"
        )
        alarm_a = _seed_alarm(admin_sync_url, asset_a, seeded_orgs["org_a_id"], code="A_ONLY")

        resp = await client_b.get("/api/v1/alarms/")
        assert resp.status_code == 200
        ids = [item["id"] for item in resp.json()["items"]]
        assert alarm_a not in ids, "org B listed org A's alarm"

        # Positive control: the owner still sees it, so the fix scoped rather
        # than simply broke the endpoint.
        own = await client_a.get("/api/v1/alarms/")
        assert alarm_a in [i["id"] for i in own.json()["items"]]

    async def test_get_by_id_is_404_for_non_owner(
        self, client_b, admin_sync_url, seeded_orgs
    ):
        asset_a = _seed_asset(
            admin_sync_url, seeded_orgs["org_a_id"], seeded_orgs["workcell_a_id"], "AlarmAssetA2"
        )
        alarm_a = _seed_alarm(admin_sync_url, asset_a, seeded_orgs["org_a_id"])

        resp = await client_b.get(f"/api/v1/alarms/{alarm_a}")
        assert resp.status_code == 404, "org B read org A's alarm by id"

    async def test_active_ignores_client_supplied_organization_id(
        self, client_b, admin_sync_url, seeded_orgs
    ):
        """/active took `organization_id` as an OPTIONAL QUERY PARAM.

        It joined assets only `if organization_id:` — so omitting the parameter
        removed the filter entirely, and supplying another org's id read that
        org's alarms. Both directions are asserted here.
        """
        asset_a = _seed_asset(
            admin_sync_url, seeded_orgs["org_a_id"], seeded_orgs["workcell_a_id"], "AlarmAssetA3"
        )
        alarm_a = _seed_alarm(admin_sync_url, asset_a, seeded_orgs["org_a_id"])

        # Omitted -> must still be scoped to the caller.
        resp = await client_b.get("/api/v1/alarms/active")
        assert resp.status_code == 200
        assert alarm_a not in [a["id"] for a in resp.json()["alarms"]]

        # Supplied with the OTHER org's id -> must not honour it.
        resp = await client_b.get(
            "/api/v1/alarms/active",
            params={"organization_id": str(seeded_orgs["org_a_id"])},
        )
        assert resp.status_code in (200, 422)
        if resp.status_code == 200:
            assert alarm_a not in [a["id"] for a in resp.json()["alarms"]], (
                "client-supplied organization_id was trusted"
            )


# ---------------------------------------------------------------------------
# Writes — the part a read-only leak test would miss
# ---------------------------------------------------------------------------

class TestAlarmWriteIsolation:
    async def test_acknowledge_is_404_and_does_not_mutate(
        self, client_b, admin_sync_url, seeded_orgs
    ):
        asset_a = _seed_asset(
            admin_sync_url, seeded_orgs["org_a_id"], seeded_orgs["workcell_a_id"], "AckAssetA"
        )
        alarm_a = _seed_alarm(admin_sync_url, asset_a, seeded_orgs["org_a_id"])

        resp = await client_b.post(
            f"/api/v1/alarms/{alarm_a}/acknowledge", json={"comment": "not mine"}
        )
        assert resp.status_code == 404

        # A 404 is not enough — prove nothing was written.
        row = _read_alarm(admin_sync_url, alarm_a)
        assert row["is_acknowledged"] is False, "org B acknowledged org A's alarm"
        assert row["acknowledged_by"] is None

    async def test_clear_is_404_and_does_not_mutate(
        self, client_b, admin_sync_url, seeded_orgs
    ):
        asset_a = _seed_asset(
            admin_sync_url, seeded_orgs["org_a_id"], seeded_orgs["workcell_a_id"], "ClearAssetA"
        )
        alarm_a = _seed_alarm(admin_sync_url, asset_a, seeded_orgs["org_a_id"])

        resp = await client_b.post(f"/api/v1/alarms/{alarm_a}/clear")
        assert resp.status_code == 404

        row = _read_alarm(admin_sync_url, alarm_a)
        assert row["is_active"] is True, "org B cleared org A's alarm"
        assert row["cleared_at"] is None

    async def test_acknowledge_all_does_not_touch_other_orgs(
        self, client_b, admin_sync_url, seeded_orgs
    ):
        """The worst of the six: an unscoped bulk UPDATE across every tenant."""
        asset_a = _seed_asset(
            admin_sync_url, seeded_orgs["org_a_id"], seeded_orgs["workcell_a_id"], "BulkAssetA"
        )
        asset_b = _seed_asset(
            admin_sync_url, seeded_orgs["org_b_id"], seeded_orgs["workcell_b_id"], "BulkAssetB"
        )
        alarm_a = _seed_alarm(admin_sync_url, asset_a, seeded_orgs["org_a_id"])
        alarm_b = _seed_alarm(admin_sync_url, asset_b, seeded_orgs["org_b_id"])

        resp = await client_b.post("/api/v1/alarms/acknowledge-all")
        assert resp.status_code == 200

        assert _read_alarm(admin_sync_url, alarm_a)["is_acknowledged"] is False, (
            "bulk acknowledge crossed tenants"
        )
        # And it did do its actual job for the caller's own org.
        assert _read_alarm(admin_sync_url, alarm_b)["is_acknowledged"] is True


# ---------------------------------------------------------------------------
# Audit trail
# ---------------------------------------------------------------------------

class TestAcknowledgedByIsRecorded:
    async def test_acknowledge_records_the_authenticated_user(
        self, client_a, admin_sync_url, seeded_orgs
    ):
        """`user_id: UUID = None  # Would come from auth dependency`.

        Every acknowledgement wrote NULL, so there was no record of who cleared
        an alarm — and `user_id` was a QUERY PARAMETER, meaning a caller could
        also attribute their acknowledgement to any user id they liked.
        """
        asset_a = _seed_asset(
            admin_sync_url, seeded_orgs["org_a_id"], seeded_orgs["workcell_a_id"], "AuditAssetA"
        )
        alarm_a = _seed_alarm(admin_sync_url, asset_a, seeded_orgs["org_a_id"])

        resp = await client_a.post(
            f"/api/v1/alarms/{alarm_a}/acknowledge", json={"comment": "on it"}
        )
        assert resp.status_code == 200

        row = _read_alarm(admin_sync_url, alarm_a)
        assert row["is_acknowledged"] is True
        assert row["acknowledged_by"] is not None, "acknowledged_by still NULL"
        assert str(row["acknowledged_by"]) == str(seeded_orgs["user_a_id"])

    async def test_caller_cannot_forge_acknowledged_by(
        self, client_a, admin_sync_url, seeded_orgs
    ):
        """Passing ?user_id=<someone else> must not be honoured."""
        asset_a = _seed_asset(
            admin_sync_url, seeded_orgs["org_a_id"], seeded_orgs["workcell_a_id"], "ForgeAssetA"
        )
        alarm_a = _seed_alarm(admin_sync_url, asset_a, seeded_orgs["org_a_id"])

        resp = await client_a.post(
            f"/api/v1/alarms/{alarm_a}/acknowledge",
            params={"user_id": str(seeded_orgs["user_b_id"])},
            json={"comment": "spoofed"},
        )
        assert resp.status_code in (200, 422)
        if resp.status_code == 200:
            row = _read_alarm(admin_sync_url, alarm_a)
            assert str(row["acknowledged_by"]) == str(seeded_orgs["user_a_id"]), (
                "acknowledged_by was taken from the request, not the token"
            )


# ---------------------------------------------------------------------------
# Defence in depth — migration 046
# ---------------------------------------------------------------------------

class TestAlarmsRLSIsIndependentOfTheJoin:
    """The join in the router and the RLS policy must BOTH hold on their own.

    The router's `_org_scoped()` is the primary barrier, but it is only as good as
    the next person remembering to use it. These assertions bypass the router
    entirely and talk to Postgres with a tenant GUC set, so they fail if migration
    046's policy is dropped even while every endpoint still passes.
    """

    async def test_policy_and_force_are_present_on_alarms(self, admin_sync_url):
        """Structural assertion: ENABLE alone is not enough, FORCE is required.

        Without FORCE the table owner — which is the application role in most of
        our deployments — bypasses the policy silently.
        """
        import psycopg2

        conn = psycopg2.connect(admin_sync_url)
        conn.autocommit = True
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT relrowsecurity, relforcerowsecurity "
                    "FROM pg_class WHERE oid = 'public.alarms'::regclass;"
                )
                enabled, forced = cur.fetchone()
                assert enabled is True, "alarms does not have RLS enabled"
                assert forced is True, "alarms has RLS but not FORCE — owners bypass it"

                cur.execute(
                    "SELECT count(*) FROM pg_policies "
                    "WHERE schemaname='public' AND tablename='alarms' "
                    "AND policyname='tenant_isolation';"
                )
                assert cur.fetchone()[0] == 1, "tenant_isolation policy missing on alarms"
        finally:
            conn.close()

    async def test_organization_id_is_not_null_and_backfilled(self, admin_sync_url):
        """A nullable tenant column would let an unscoped insert slip through."""
        import psycopg2

        conn = psycopg2.connect(admin_sync_url)
        conn.autocommit = True
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT is_nullable FROM information_schema.columns "
                    "WHERE table_schema='public' AND table_name='alarms' "
                    "AND column_name='organization_id';"
                )
                row = cur.fetchone()
                assert row is not None, "alarms.organization_id does not exist"
                assert row[0] == "NO", "alarms.organization_id is nullable"

                # Whatever demo/fixture rows the chain inserted must have been
                # backfilled from their owning asset, not left unscoped.
                cur.execute(
                    "SELECT count(*) FROM alarms a JOIN assets s ON a.asset_id = s.id "
                    "WHERE a.organization_id <> s.organization_id;"
                )
                assert cur.fetchone()[0] == 0, (
                    "alarms.organization_id disagrees with the owning asset"
                )
        finally:
            conn.close()

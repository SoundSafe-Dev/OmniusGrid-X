"""Alarm rule CRUD against a real Postgres (FS-218).

Two things need real Postgres rather than SQLite here:

* the CHECK constraints from migration 047 (comparator, severity, non-negative
  duration/hysteresis) — SQLite would happily store a typo'd comparator, which is
  exactly the "rule that looks configured and never fires" failure this table was
  designed to prevent;
* RLS, which is a no-op on SQLite, so an isolation test there proves nothing.

`alarms` needed migration 046 to retrofit tenancy after five endpoints had already
leaked (FS-216/217). `alarm_rules` was built with organization_id + FORCE RLS in
its first migration, and these tests assert that on the new table from day one.
"""

from __future__ import annotations

from uuid import uuid4


def _rule_payload(**over) -> dict:
    base = {
        "name": "Spindle temperature critical",
        "metric_name": "temperature",
        "comparator": "gt",
        "threshold": 80.0,
        "duration_seconds": 300,
        "hysteresis": 2.0,
        "severity": "critical",
        "alarm_code": "TEMP_HIGH",
    }
    base.update(over)
    return base


def _seed_asset(admin_sync_url: str, org_id, workcell_id, name: str) -> str:
    """Insert an asset (superuser, bypasses RLS) plus the global asset type."""
    import psycopg2

    asset_id, type_id = str(uuid4()), str(uuid4())
    conn = psycopg2.connect(admin_sync_url)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO asset_types (id, name, category) VALUES (%s, %s, 'test');",
                (type_id, f"RuleType-{type_id[:8]}"),
            )
            cur.execute(
                """
                INSERT INTO assets
                    (id, organization_id, workcell_id, asset_type_id, name, connection_config)
                VALUES (%s, %s, %s, %s, %s, '{}');
                """,
                (asset_id, str(org_id), str(workcell_id), type_id, name),
            )
    finally:
        conn.close()
    return asset_id


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

class TestAlarmRuleCrud:
    async def test_create_then_read_back(self, client_a):
        created = await client_a.post("/api/v1/alarm-rules/", json=_rule_payload())
        assert created.status_code == 201, created.text
        body = created.json()
        assert body["name"] == "Spindle temperature critical"
        assert body["comparator"] == "gt"
        assert body["duration_seconds"] == 300
        # Server-assigned, never client-supplied.
        assert body["organization_id"]
        assert body["created_by"]

        fetched = await client_a.get(f"/api/v1/alarm-rules/{body['id']}")
        assert fetched.status_code == 200
        assert fetched.json()["id"] == body["id"]

    async def test_list_returns_the_envelope_with_a_real_total(self, client_a):
        for i in range(3):
            resp = await client_a.post(
                "/api/v1/alarm-rules/",
                json=_rule_payload(name=f"Rule {i}", alarm_code=f"CODE_{i}"),
            )
            assert resp.status_code == 201

        listed = await client_a.get("/api/v1/alarm-rules/", params={"limit": 2})
        assert listed.status_code == 200
        payload = listed.json()
        # Assert the envelope explicitly: counting dict keys or len(items) would
        # pass even if `total` were wrong, which is how a paginated total gets
        # quietly reported as the page size.
        assert len(payload["items"]) == 2
        assert payload["meta"]["total"] >= 3
        assert payload["meta"]["limit"] == 2

    async def test_patch_leaves_omitted_fields_alone(self, client_a):
        created = await client_a.post("/api/v1/alarm-rules/", json=_rule_payload())
        rule_id = created.json()["id"]

        patched = await client_a.patch(
            f"/api/v1/alarm-rules/{rule_id}", json={"is_enabled": False}
        )
        assert patched.status_code == 200
        body = patched.json()
        assert body["is_enabled"] is False
        # The whole reason AlarmRuleUpdate is a separate schema: a PATCH that only
        # disables a rule must not reset its threshold or duration to defaults.
        assert body["threshold"] == 80.0
        assert body["duration_seconds"] == 300
        assert body["severity"] == "critical"

    async def test_delete_removes_the_rule(self, client_a):
        created = await client_a.post("/api/v1/alarm-rules/", json=_rule_payload())
        rule_id = created.json()["id"]

        deleted = await client_a.delete(f"/api/v1/alarm-rules/{rule_id}")
        assert deleted.status_code == 204

        gone = await client_a.get(f"/api/v1/alarm-rules/{rule_id}")
        assert gone.status_code == 404

    async def test_filters_narrow_the_list(self, client_a):
        await client_a.post(
            "/api/v1/alarm-rules/",
            json=_rule_payload(name="Temp", metric_name="temperature", alarm_code="T1"),
        )
        await client_a.post(
            "/api/v1/alarm-rules/",
            json=_rule_payload(
                name="Pressure", metric_name="pressure", alarm_code="P1", severity="low"
            ),
        )

        by_metric = await client_a.get(
            "/api/v1/alarm-rules/", params={"metric_name": "pressure"}
        )
        names = [r["name"] for r in by_metric.json()["items"]]
        assert names == ["Pressure"]

        by_severity = await client_a.get(
            "/api/v1/alarm-rules/", params={"severity": "low"}
        )
        assert [r["name"] for r in by_severity.json()["items"]] == ["Pressure"]


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

class TestAlarmRuleValidation:
    async def test_bad_comparator_is_rejected(self, client_a):
        resp = await client_a.post(
            "/api/v1/alarm-rules/", json=_rule_payload(comparator="GREATER")
        )
        assert resp.status_code == 422, (
            "a typo'd comparator would create a rule that never fires"
        )

    async def test_bad_severity_is_rejected(self, client_a):
        resp = await client_a.post(
            "/api/v1/alarm-rules/", json=_rule_payload(severity="urgent")
        )
        assert resp.status_code == 422, (
            "a severity `alarms` cannot hold would fail at fire time, not create time"
        )

    async def test_negative_duration_and_hysteresis_are_rejected(self, client_a):
        assert (
            await client_a.post(
                "/api/v1/alarm-rules/", json=_rule_payload(duration_seconds=-1)
            )
        ).status_code == 422
        assert (
            await client_a.post(
                "/api/v1/alarm-rules/", json=_rule_payload(hysteresis=-0.5)
            )
        ).status_code == 422

    async def test_unknown_asset_target_is_rejected(self, client_a):
        resp = await client_a.post(
            "/api/v1/alarm-rules/", json=_rule_payload(asset_id=str(uuid4()))
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Tenancy
# ---------------------------------------------------------------------------

class TestAlarmRuleTenancy:
    async def test_rules_are_not_visible_across_organizations(self, client_a, client_b):
        created = await client_a.post(
            "/api/v1/alarm-rules/", json=_rule_payload(name="A only", alarm_code="A1")
        )
        rule_id = created.json()["id"]

        listed = await client_b.get("/api/v1/alarm-rules/")
        assert rule_id not in [r["id"] for r in listed.json()["items"]]

        assert (await client_b.get(f"/api/v1/alarm-rules/{rule_id}")).status_code == 404

    async def test_other_org_cannot_patch_or_delete(self, client_a, client_b):
        created = await client_a.post(
            "/api/v1/alarm-rules/", json=_rule_payload(name="A only", alarm_code="A2")
        )
        rule_id = created.json()["id"]

        patched = await client_b.patch(
            f"/api/v1/alarm-rules/{rule_id}", json={"is_enabled": False}
        )
        assert patched.status_code == 404

        deleted = await client_b.delete(f"/api/v1/alarm-rules/{rule_id}")
        assert deleted.status_code == 404

        # Prove the writes did not land, not merely that the responses were 404.
        still_there = await client_a.get(f"/api/v1/alarm-rules/{rule_id}")
        assert still_there.status_code == 200
        assert still_there.json()["is_enabled"] is True

    async def test_cannot_target_another_organizations_asset(
        self, client_a, admin_sync_url, seeded_orgs
    ):
        """The kanban `alarm_id` hole in FS-216 was exactly this shape: a foreign
        id accepted verbatim from the body, which later became a cross-tenant
        write. A rule must not be able to reference org B's asset."""
        foreign_asset = _seed_asset(
            admin_sync_url,
            seeded_orgs["org_b_id"],
            seeded_orgs["workcell_b_id"],
            "ForeignAsset",
        )

        resp = await client_a.post(
            "/api/v1/alarm-rules/", json=_rule_payload(asset_id=foreign_asset)
        )
        assert resp.status_code == 404, "accepted another organization's asset as a target"

    async def test_can_target_own_asset(self, client_a, admin_sync_url, seeded_orgs):
        own_asset = _seed_asset(
            admin_sync_url,
            seeded_orgs["org_a_id"],
            seeded_orgs["workcell_a_id"],
            "OwnAsset",
        )
        resp = await client_a.post(
            "/api/v1/alarm-rules/", json=_rule_payload(asset_id=own_asset)
        )
        assert resp.status_code == 201, resp.text
        assert resp.json()["asset_id"] == own_asset


# ---------------------------------------------------------------------------
# Schema-level guarantees
# ---------------------------------------------------------------------------

class TestAlarmRulesTableIsTenantScopedAtTheDatabase:
    async def test_force_rls_and_policy_exist(self, admin_sync_url):
        """Built in from migration 047, unlike `alarms` which needed 046 to
        retrofit it. Without FORCE the app role (usually the table owner) bypasses
        the policy silently."""
        import psycopg2

        conn = psycopg2.connect(admin_sync_url)
        conn.autocommit = True
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT relrowsecurity, relforcerowsecurity FROM pg_class "
                    "WHERE oid = 'public.alarm_rules'::regclass;"
                )
                enabled, forced = cur.fetchone()
                assert enabled is True, "alarm_rules has no RLS"
                assert forced is True, "alarm_rules has RLS but not FORCE"

                cur.execute(
                    "SELECT count(*) FROM pg_policies WHERE schemaname='public' "
                    "AND tablename='alarm_rules' AND policyname='tenant_isolation';"
                )
                assert cur.fetchone()[0] == 1
        finally:
            conn.close()

    async def test_check_constraints_reject_bad_values_at_the_database(
        self, admin_sync_url, seeded_orgs
    ):
        """Defence in depth: the API validates too, but a raw INSERT (a migration,
        a fixture, a script) must not be able to write an unevaluatable rule."""
        import psycopg2

        conn = psycopg2.connect(admin_sync_url)
        conn.autocommit = True
        try:
            # `gtx` rather than `GREATER`: comparator is VARCHAR(4), so a longer
            # value is rejected by the length limit before the CHECK is ever
            # evaluated — the assertion would pass without the constraint existing.
            for column, value in (
                ("comparator", "'gtx'"),
                ("severity", "'urgent'"),
            ):
                with conn.cursor() as cur:
                    good = {
                        "comparator": "'gt'",
                        "severity": "'critical'",
                    }
                    good[column] = value
                    try:
                        cur.execute(
                            f"""
                            INSERT INTO alarm_rules
                                (organization_id, name, metric_name, comparator,
                                 threshold, severity, alarm_code)
                            VALUES (%s, 'raw', 'temperature', {good['comparator']},
                                    1.0, {good['severity']}, 'C');
                            """,
                            (str(seeded_orgs["org_a_id"]),),
                        )
                        raise AssertionError(
                            f"database accepted an invalid {column}: {value}"
                        )
                    except psycopg2.errors.CheckViolation:
                        pass
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# End-to-end: a rule actually firing from telemetry
# ---------------------------------------------------------------------------

class TestRuleFiresFromRealTelemetry:
    """The unit tests in test_alarm_rule_evaluation.py use SimpleNamespace fakes,
    so they prove the DECISION logic but not the two parts that touch the
    database: the SQL loader's targeting predicate, and whether the Alarm row the
    evaluator builds actually satisfies the real schema and the RLS WITH CHECK.

    Both have failed silently in this codebase before — a rule that looks
    configured and never fires is indistinguishable from a quiet system.
    """

    async def test_rule_raises_a_real_alarm_row(
        self, client_a, admin_sync_url, seeded_orgs
    ):
        from sqlalchemy import text
        from app.db.database import AsyncSessionLocal
        from app.db.models import Asset
        from sqlalchemy import select
        from app.services.alarm_rules import InMemoryBreachStore, evaluate_metric

        asset_id = _seed_asset(
            admin_sync_url,
            seeded_orgs["org_a_id"],
            seeded_orgs["workcell_a_id"],
            "RuleFireAsset",
        )
        created = await client_a.post(
            "/api/v1/alarm-rules/",
            json=_rule_payload(
                name="Fires immediately",
                alarm_code="E2E_TEMP",
                duration_seconds=0,
                asset_id=asset_id,
            ),
        )
        assert created.status_code == 201, created.text

        org = str(seeded_orgs["org_a_id"])
        async with AsyncSessionLocal() as session:
            # The GUC is what the ingestion worker sets before dispatching, and it
            # is required for both the rule SELECT and the Alarm INSERT under RLS.
            await session.execute(
                text("SELECT set_config('app.current_org_id', :o, true)"), {"o": org}
            )
            asset = (
                await session.execute(select(Asset).where(Asset.id == asset_id))
            ).scalars().first()
            assert asset is not None

            outcomes = await evaluate_metric(
                session,
                InMemoryBreachStore(),
                organization_id=org,
                asset=asset,
                metric_name="temperature",
                value=95.0,
            )
            assert [o.reason for o in outcomes] == ["fired"], outcomes
            await session.commit()

        # Read it back through the API, which proves the row is both persisted and
        # visible to its own tenant.
        listed = await client_a.get("/api/v1/alarms/", params={"severity": "critical"})
        assert listed.status_code == 200
        raised = [a for a in listed.json()["items"] if a["alarm_code"] == "E2E_TEMP"]
        assert len(raised) == 1, "the rule did not persist an alarm"
        alarm = raised[0]
        assert alarm["severity"] == "critical"
        assert alarm["metadata"]["source"] == "alarm_rule"
        assert alarm["metadata"]["value"] == 95.0

    async def test_rule_targeting_another_asset_does_not_fire(
        self, client_a, admin_sync_url, seeded_orgs
    ):
        """Proves the SQL loader + targeting predicate actually discriminate. A
        loader that ignored targeting would fire this rule for every asset."""
        from sqlalchemy import select, text
        from app.db.database import AsyncSessionLocal
        from app.db.models import Asset
        from app.services.alarm_rules import InMemoryBreachStore, evaluate_metric

        target = _seed_asset(
            admin_sync_url, seeded_orgs["org_a_id"], seeded_orgs["workcell_a_id"], "Targeted"
        )
        other = _seed_asset(
            admin_sync_url, seeded_orgs["org_a_id"], seeded_orgs["workcell_a_id"], "Other"
        )
        resp = await client_a.post(
            "/api/v1/alarm-rules/",
            json=_rule_payload(
                name="Only the targeted asset",
                alarm_code="TARGETED_ONLY",
                duration_seconds=0,
                asset_id=target,
            ),
        )
        assert resp.status_code == 201

        org = str(seeded_orgs["org_a_id"])
        async with AsyncSessionLocal() as session:
            await session.execute(
                text("SELECT set_config('app.current_org_id', :o, true)"), {"o": org}
            )
            other_asset = (
                await session.execute(select(Asset).where(Asset.id == other))
            ).scalars().first()
            outcomes = await evaluate_metric(
                session,
                InMemoryBreachStore(),
                organization_id=org,
                asset=other_asset,
                metric_name="temperature",
                value=999.0,
            )
            await session.commit()

        assert outcomes == [], "a targeted rule fired for an untargeted asset"

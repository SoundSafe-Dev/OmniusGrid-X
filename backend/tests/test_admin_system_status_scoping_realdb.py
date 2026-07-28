"""The engineer-facing system status must count the caller's assets, not zero.

THE DEFECT. `/admin/system/status` is admin-gated and has an authenticated user, but ran
on `get_db` — which sets no `app.current_org_id`. `assets` and `alarms` are both FORCE
ROW LEVEL SECURITY, so both counts came back **zero no matter how much existed**. A
system-status page reporting `active_assets: 0` and no alarms on a running platform reads
as an idle system, not as a broken query.

WHY THE REST OF health.py STAYS ON get_db, and why that is not the same debt.
`/health/live`, `/health/ready` and `/health/startup` are UNAUTHENTICATED probes. They
cannot use `get_tenant_db`, which resolves a tenant from an authenticated user, so they
must read only tables without a policy — and they now do. `_check_ingestion` had to drop
an `assets.last_seen` read for exactly this reason: it published
`latest_asset_seen_at: null`, which asserts "no asset has ever been seen" rather than
"not obtainable here".

So the file is deliberately mixed rather than uniformly converted, and this test exists to
pin which half is which.

Counts are the caller's organisation. Platform-wide totals need the super-admin role that
does not exist yet — the same one `data_retention` and the audit log's cross-org view are
blocked on.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def active_asset(admin_sync_url, seeded_orgs):
    import psycopg2

    asset_a, asset_b = uuid.uuid4(), uuid.uuid4()
    wc_a, wc_b, type_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    conn = psycopg2.connect(admin_sync_url)
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO asset_types (id, name, category) VALUES (%s, 'HS', 'test')",
            (str(type_id),))
        for asset, wc, org_key in ((asset_a, wc_a, "org_a_id"), (asset_b, wc_b, "org_b_id")):
            org = str(seeded_orgs[org_key])
            cur.execute(
                "INSERT INTO workcells (id, organization_id, name) VALUES (%s, %s, 'HS WC')",
                (str(wc), org))
            cur.execute(
                "INSERT INTO assets (id, organization_id, workcell_id, asset_type_id, "
                "name, is_active) VALUES (%s, %s, %s, %s, 'HS Asset', true)",
                (str(asset), org, str(wc), str(type_id)))
    yield asset_a, asset_b
    with conn.cursor() as cur:
        for asset, wc in ((asset_a, wc_a), (asset_b, wc_b)):
            cur.execute("DELETE FROM assets WHERE id = %s", (str(asset),))
            cur.execute("DELETE FROM workcells WHERE id = %s", (str(wc),))
        cur.execute("DELETE FROM asset_types WHERE id = %s", (str(type_id),))
    conn.close()


def _active_assets(payload) -> int:
    """The count, wherever the report puts it."""
    for container in (payload.get("storage", {}), payload, payload.get("metrics", {})):
        if isinstance(container, dict) and "active_assets" in container:
            return container["active_assets"]
    raise AssertionError(f"no active_assets in the report: {list(payload)}")


class TestTheAdminStatusCountsRealAssets:
    async def test_it_does_not_report_zero(self, client_a, active_asset):
        """THE ASSERTION THIS FILE EXISTS FOR."""
        response = await client_a.get("/admin/system/status")
        assert response.status_code == 200, response.text
        assert _active_assets(response.json()) >= 1, (
            "the system status reports no active assets while one exists — the counts "
            "are still running without a tenant GUC"
        )

    async def test_it_counts_only_the_callers_org(self, client_a, client_b, active_asset):
        """Each org seeded exactly one asset. If scoping were absent both would see 2,
        which is also how a platform-wide count would look — hence the exact equality."""
        a_count = _active_assets((await client_a.get("/admin/system/status")).json())
        b_count = _active_assets((await client_b.get("/admin/system/status")).json())
        assert a_count == 1, f"org A sees {a_count} assets, expected only its own"
        assert b_count == 1, f"org B sees {b_count} assets, expected only its own"


class TestThePublicProbesStayPublic:
    """Converting these would break them: `get_tenant_db` needs an authenticated user
    and a probe has none. They are exempt, not debt — pinned so a later uniform sweep
    does not 'fix' them into 500s."""

    @pytest.mark.parametrize("path", ["/health/live", "/health/ready", "/health/startup"])
    async def test_the_probe_answers_without_authentication(self, app, path):
        from httpx import ASGITransport, AsyncClient

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get(path)
        assert response.status_code in (200, 503), (
            f"{path} -> {response.status_code}; an unauthenticated probe must answer, "
            f"not demand a tenant"
        )

    async def test_readiness_does_not_publish_an_unreadable_figure(self, app):
        """`_check_ingestion` used to report `latest_asset_seen_at`, which a probe can
        never read under RLS, so it was always null — asserting 'no asset has ever been
        seen'. It must not come back."""
        from httpx import ASGITransport, AsyncClient

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/health/ready")
        body = response.json()
        ingestion = (body.get("checks") or {}).get("ingestion")
        details = (body.get("details") or {}).get("ingestion", {})
        assert "latest_asset_seen_at" not in details, (
            "the readiness probe is again publishing a figure it cannot read"
        )
        assert ingestion is not None or response.status_code == 503

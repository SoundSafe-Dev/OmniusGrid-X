"""Handlers that opened their own session could not see the caller's own assets.

THE BLIND SPOT THAT HID THEM. `test_tenant_session_guard.py` looks for
`Depends(get_db)`. These five handlers never used it — they opened
`AsyncSessionLocal()` inline, which binds no `app.current_org_id`. `assets` is FORCE
ROW LEVEL SECURITY, so the policy matched nothing and every lookup came back empty.

The guard's own docstring had already recorded this, in the note explaining why its
`commands.py` count was wrong: *"A static guard keyed on one idiom under-counts a file
that uses two."* The idiom was named and the sweep was never extended to it. Five more
handlers were sitting in the same gap.

VERIFIED AGAINST A REAL DATABASE BEFORE THE FIX, with an asset that plainly existed:

    404  /api/v1/oee/current/{id}          "Asset not found"
    404  /api/v1/oee/historical/{id}       "Asset not found"
    404  /api/v1/oee/losses/{id}           "Asset not found"
    200  /api/v1/health-index              []
    200  /api/v1/simulation/fleet-summary  {"asset_count": 0, ...}

Both halves of the RLS failure mode in one screen: three endpoints that **404 on an
asset you own**, and two that answer 200 with an empty, confident lie. The quiet pair is
worse — an operator reading "asset_count: 0" on a running fleet sees an idle plant, not a
broken query.

`health_index` and `simulation` are the sharper case: both filtered on
`current_user.organization_id` and both were CORRECT to. It made no difference, because
RLS had already removed the rows. Nothing in a code review of those handlers points at
the session, which is exactly why this class survives review. Same shape as `gdpr.py`.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
import pytest_asyncio

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def owned_asset(admin_sync_url, seeded_orgs):
    """One asset belonging to org A."""
    import psycopg2

    conn = psycopg2.connect(admin_sync_url)
    conn.autocommit = True
    asset_id, type_id = uuid4(), uuid4()
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO asset_types (id, name, category) VALUES (%s, %s, 'test')",
            (str(type_id), f"INL-{type_id.hex[:8]}"),
        )
        cur.execute(
            "INSERT INTO assets (id, organization_id, workcell_id, asset_type_id, name, "
            "is_active) VALUES (%s, %s, %s, %s, 'Inline Session Asset', true)",
            (
                str(asset_id),
                str(seeded_orgs["org_a_id"]),
                str(seeded_orgs["workcell_a_id"]),
                str(type_id),
            ),
        )
    yield asset_id
    with conn.cursor() as cur:
        cur.execute("DELETE FROM assets WHERE id = %s", (str(asset_id),))
        cur.execute("DELETE FROM asset_types WHERE id = %s", (str(type_id),))
    conn.close()


class TestTheOwnerCanReachTheirOwnAsset:
    """The loud half: a 404 about an asset that exists and belongs to the caller."""

    @pytest.mark.parametrize("route", ["current", "historical", "losses"])
    async def test_oee_endpoints_find_the_asset(self, client_a, owned_asset, route):
        response = await client_a.get(f"/api/v1/oee/{route}/{owned_asset}")
        assert response.status_code == 200, (
            f"/api/v1/oee/{route} answered {response.status_code} for an asset the "
            f"caller owns — the handler's session has no tenant GUC, so RLS hid the row "
            f"and the lookup concluded it does not exist"
        )
        assert response.json()["asset_id"] == str(owned_asset)


class TestTheQuietHalf:
    """No error, no clue: a populated fleet reported as empty."""

    async def test_health_index_lists_the_asset(self, client_a, owned_asset):
        body = (await client_a.get("/api/v1/health-index")).json()
        assert any(row["asset_id"] == str(owned_asset) for row in body), (
            f"health-index returned {len(body)} rows and none is the caller's asset"
        )

    async def test_fleet_summary_counts_the_asset(self, client_a, owned_asset):
        body = (await client_a.get("/api/v1/simulation/fleet-summary")).json()
        assert body["asset_count"] >= 1, (
            "fleet-summary reports an empty fleet while the caller owns an asset — "
            "which reads as an idle plant rather than a broken query"
        )


class TestTenantIsolationStillHolds:
    """The fix hands these handlers a session that CAN see assets. What must not follow
    is that they can see everyone's."""

    #: ALL THREE, matching the owner half above, which was parametrized over three while
    #: this one checked `current` alone — so two routes were asserted to work for their
    #: owner and never asserted to be closed to anyone else. `losses` is the one the OEE
    #: page calls for its loss breakdown.
    #:
    #: WHAT THE MUTATIONS SHOWED, because it is less than the paragraph above implies.
    #: Neither obvious way of breaking these routes makes these three cases fail. Switching
    #: the handler to `get_db` fails the OWNER half instead (an unscoped session hides the
    #: asset from everybody, so isolation passes for the wrong reason), and deleting the
    #: ownership predicate entirely changes nothing at all, because `assets` is FORCE ROW
    #: LEVEL SECURITY and the session is bound — the schema is the boundary here, not the
    #: handler.
    #:
    #: They are kept as the check on THAT: if `assets` ever loses its policy, or one of
    #: these routes is served from a session that is not tenant-bound while still finding
    #: rows, this is what says so. `operations` is the cautionary case — no org column, no
    #: policy, and four handlers that reached every tenant's rows because nothing under
    #: them was ever going to filter (FS-720). Rule 213: keep the redundant assertion, and
    #: record that the mutation could not move it.
    @pytest.mark.parametrize("route", ["current", "historical", "losses"])
    async def test_another_org_cannot_read_the_asset(self, client_b, owned_asset, route):
        response = await client_b.get(f"/api/v1/oee/{route}/{owned_asset}")
        assert response.status_code == 404, (
            f"org B can read org A's asset through /api/v1/oee/{route}; binding the GUC "
            f"must scope the read, not open it"
        )

    async def test_another_orgs_health_index_does_not_include_it(
        self, client_b, owned_asset
    ):
        body = (await client_b.get("/api/v1/health-index")).json()
        assert not any(row["asset_id"] == str(owned_asset) for row in body)

    async def test_another_orgs_fleet_summary_does_not_count_it(
        self, client_b, owned_asset, seeded_orgs
    ):
        body = (await client_b.get("/api/v1/simulation/fleet-summary")).json()
        assert body["bottleneck_asset_id"] != str(owned_asset)


class TestTheGuardWouldNowCatchThis:
    """The regression that matters most is not these five handlers — it is the next one
    written the same way. `test_tenant_session_guard.py` now sweeps both idioms."""

    def test_the_inline_idiom_is_swept(self):
        from tests.test_tenant_session_guard import _inline_session_offenders

        offenders = _inline_session_offenders()
        assert isinstance(offenders, dict)
        for name in ("oee.py", "health_index.py", "simulation.py"):
            assert name not in offenders, (
                f"{name} still opens an unbound session on an RLS model"
            )

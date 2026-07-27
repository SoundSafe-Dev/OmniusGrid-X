"""The tenant GUC must survive an endpoint's mid-request commit.

THE DEFECT. `get_tenant_db` set `app.current_org_id` exactly once, before yielding
the session, with `set_config(..., false)`. The reasoning — written into the
docstring — was that a session-scoped value survives an endpoint that commits
mid-request, where a transaction-local one would not.

It does not survive. `commit()` ends the transaction *and returns the connection to
the pool*; the next statement checks out a connection that was never configured. The
GUC reads as empty, `NULLIF` turns it into NULL, and every RLS policy fails closed.

So an endpoint that wrote a row and then read it back got **nothing**, for data it had
just committed itself. `create_rollout` in `api/agent_rollouts.py` did exactly that and
returned 404 for a rollout that was sitting in the table. `test_agent_ota_api` and
`test_compliance_report_scheduling_e2e` were both failing on it.

WHY NO EXISTING TEST CAUGHT IT, WHICH IS THE MORE IMPORTANT PART. `conftest` has to
point endpoints at the testcontainers engine, and did so with an override that
hand-copied the body of `get_tenant_db`, under a comment reading *"Mirrors the
production get_tenant_db."* It mirrored the bug as well as the behaviour. Every RLS
test in the suite exercised the copy, so none of them could see this, and fixing
production would not have reached them either. A test double that reimplements the
thing it stands in for can only prove the double works.

Both halves are fixed: the GUC is now re-established per transaction from an
`after_begin` hook (so any number of commits is fine, and it is written
transaction-locally so it cannot leak onto a pooled connection), and the override
delegates to `tenant_session` rather than copying it.

This file tests `tenant_session` DIRECTLY against real Postgres — no override in the
way — because the defect lived in the seam between them.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.pool import NullPool
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine, AsyncSession

from app.core.tenant import tenant_session

pytestmark = pytest.mark.asyncio

# The source-inspection test below is sync; the mark above is harmless there.


@pytest_asyncio.fixture
async def tenant_maker(tenant_async_url):
    """Sessions as the non-superuser role, so RLS actually applies.

    NullPool IS THE POINT, not a detail. With a normal pool this test suite could
    not fail: `commit()` returns the connection to the pool and the very next
    statement checks the same one straight back out, so a session-scoped GUC
    appears to survive. That is precisely why the defect read as intermittent in
    production and was invisible in tests — it needed contention to show up.

    Verified, not assumed: with the old single `set_config(..., false)` restored,
    the assertions below pass under a default pool and fail under NullPool.

    NullPool hands out a fresh connection every time, which is the worst case a
    loaded server produces routinely. A guard that only fails when the pool
    happens to cooperate is not a guard.
    """
    engine = create_async_engine(tenant_async_url, future=True, poolclass=NullPool)
    yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    await engine.dispose()


@pytest_asyncio.fixture
async def org_with_asset(admin_sync_url):
    """An org and one asset, seeded over a superuser connection (bypassing RLS)."""
    import psycopg2

    org_id, workcell_id, asset_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    asset_type_id = uuid.uuid4()
    conn = psycopg2.connect(admin_sync_url)
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO organizations (id, name, slug) VALUES (%s, %s, %s)",
            (str(org_id), "GUC Test Org", f"guc-{org_id.hex[:8]}"),
        )
        # assets.workcell_id is NOT NULL, so the org needs a workcell first.
        cur.execute(
            "INSERT INTO workcells (id, organization_id, name) VALUES (%s, %s, %s)",
            (str(workcell_id), str(org_id), "GUC Test Workcell"),
        )
        # assets.asset_type_id is NOT NULL too; asset_types is org-independent.
        cur.execute(
            "INSERT INTO asset_types (id, name, category) VALUES (%s, %s, %s)",
            (str(asset_type_id), "GUC Test Type", "test"),
        )
        cur.execute(
            "INSERT INTO assets "
            "(id, organization_id, workcell_id, asset_type_id, name, is_active) "
            "VALUES (%s, %s, %s, %s, %s, true)",
            (str(asset_id), str(org_id), str(workcell_id), str(asset_type_id),
             "GUC Test Asset"),
        )
    yield org_id, (workcell_id, asset_type_id)
    with conn.cursor() as cur:
        cur.execute("DELETE FROM assets WHERE organization_id = %s", (str(org_id),))
        cur.execute("DELETE FROM workcells WHERE id = %s", (str(workcell_id),))
        cur.execute("DELETE FROM organizations WHERE id = %s", (str(org_id),))
        cur.execute("DELETE FROM asset_types WHERE id = %s", (str(asset_type_id),))
    conn.close()


async def _guc(session) -> str:
    return (
        await session.execute(text("SELECT current_setting('app.current_org_id', true)"))
    ).scalar()


async def _visible_assets(session) -> int:
    return (await session.execute(text("SELECT count(*) FROM assets"))).scalar()


class TestTheGucIsSetAtAll:
    """If these fail, everything below is meaningless — a zero count would then
    prove nothing about commits."""

    async def test_the_guc_holds_the_org(self, tenant_maker, org_with_asset):
        org_id, _workcell_id = org_with_asset
        async with tenant_session(org_id, tenant_maker) as session:
            assert await _guc(session) == str(org_id)

    async def test_the_org_can_see_its_own_row(self, tenant_maker, org_with_asset):
        org_id, _workcell_id = org_with_asset
        async with tenant_session(org_id, tenant_maker) as session:
            assert await _visible_assets(session) >= 1

    async def test_rls_is_actually_enforced_for_this_role(self, tenant_maker, org_with_asset):
        """Guards the guard: if the session were a superuser or the table had no
        policy, every assertion here would pass while testing nothing."""
        _org_id, _workcell_id = org_with_asset
        stranger = uuid.uuid4()
        async with tenant_session(stranger, tenant_maker) as session:
            assert await _visible_assets(session) == 0, (
                "another org's rows are visible — RLS is not being enforced, so this "
                "file cannot detect a lost GUC"
            )


class TestItSurvivesACommit:
    async def test_the_guc_is_still_set_after_a_commit(self, tenant_maker, org_with_asset):
        """THE ASSERTION THIS FILE EXISTS FOR. This read `''` before the fix."""
        org_id, _workcell_id = org_with_asset
        async with tenant_session(org_id, tenant_maker) as session:
            await session.execute(text("SELECT 1"))
            await session.commit()

            assert await _guc(session) == str(org_id), (
                "the tenant GUC was lost across a mid-request commit; every RLS "
                "policy now fails closed and the endpoint sees zero rows"
            )

    async def test_rows_are_still_visible_after_a_commit(self, tenant_maker, org_with_asset):
        """The consequence, stated as the endpoint experiences it."""
        org_id, _workcell_id = org_with_asset
        async with tenant_session(org_id, tenant_maker) as session:
            before = await _visible_assets(session)
            await session.commit()
            after = await _visible_assets(session)

            assert after == before, (
                f"visible rows dropped from {before} to {after} across a commit — this "
                f"is what made create-then-read endpoints return 404 for rows they had "
                f"just written"
            )

    async def test_a_row_written_then_committed_can_be_read_back(
        self, tenant_maker, org_with_asset
    ):
        """The exact shape of `create_rollout`: INSERT, commit, SELECT it back."""
        org_id, (workcell_id, asset_type_id) = org_with_asset
        new_asset = uuid.uuid4()
        async with tenant_session(org_id, tenant_maker) as session:
            await session.execute(
                text(
                    "INSERT INTO assets "
                    "(id, organization_id, workcell_id, asset_type_id, name, "
                    "is_active) VALUES (:id, :org, :wc, :at, :name, true)"
                ),
                {"id": str(new_asset), "org": str(org_id), "wc": str(workcell_id),
                 "at": str(asset_type_id), "name": "written-then-read"},
            )
            await session.commit()

            found = (
                await session.execute(
                    text("SELECT count(*) FROM assets WHERE id = :id"),
                    {"id": str(new_asset)},
                )
            ).scalar()
            assert found == 1, (
                "the row this session just committed is invisible to it — the 404 that "
                "create_rollout returned for a rollout that was in the table"
            )
            await session.execute(
                text("DELETE FROM assets WHERE id = :id"), {"id": str(new_asset)}
            )
            await session.commit()

    async def test_it_survives_several_commits(self, tenant_maker, org_with_asset):
        """One commit could be survived by luck — the pool handing back the same
        connection. Several makes that much less likely to be the reason."""
        org_id, _workcell_id = org_with_asset
        async with tenant_session(org_id, tenant_maker) as session:
            for round_number in range(5):
                await session.commit()
                assert await _guc(session) == str(org_id), (
                    f"GUC lost after commit #{round_number + 1}"
                )


class TestItDoesNotLeakToTheNextRequest:
    async def test_the_next_session_does_not_inherit_the_previous_tenant(
        self, tenant_maker, org_with_asset
    ):
        """The reason the value is written transaction-locally. A session-scoped GUC
        left on a pooled connection is a cross-tenant read waiting to happen, which is
        strictly worse than the bug this file is about."""
        org_id, _workcell_id = org_with_asset
        async with tenant_session(org_id, tenant_maker) as session:
            assert await _visible_assets(session) >= 1

        stranger = uuid.uuid4()
        async with tenant_session(stranger, tenant_maker) as session:
            assert await _guc(session) == str(stranger)
            assert await _visible_assets(session) == 0, (
                "a later request saw the previous tenant's rows"
            )


class TestTheTestHarnessDoesNotReimplementIt:
    # Source inspection, no database and no event loop — opt out of the
    # module-level asyncio mark.
    pytestmark = []

    def test_the_conftest_override_delegates(self):
        """The bug was invisible because the override was a copy. If it becomes one
        again, this whole file goes back to testing something production does not run.

        Asserts on source text rather than behaviour on purpose: a reimplementation
        that happens to be correct today is still the failure mode — it can drift
        tomorrow, silently, exactly as it did before.
        """
        import inspect
        import pathlib

        source = pathlib.Path(inspect.getfile(TestTheTestHarnessDoesNotReimplementIt))
        conftest = (source.parent / "conftest.py").read_text()
        start = conftest.index("async def _override_get_tenant_db")
        raw = conftest[start:start + 1800]
        # Comments explain the defect and name `set_config`; judge the CODE only.
        body = "\n".join(
            line for line in raw.splitlines() if not line.lstrip().startswith("#")
        )

        assert "tenant_session(" in body, (
            "the tenant-db override no longer delegates to app.core.tenant."
            "tenant_session — a hand-copied override mirrors production's bugs and "
            "hides them from every RLS test in the suite, which is exactly how the "
            "GUC-lost-on-commit defect survived"
        )
        assert "set_config" not in body, (
            "the override is configuring the GUC itself again instead of delegating"
        )

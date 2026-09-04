"""The app refuses to start if its own role can see past row-level security (FS-912).

`docs/engineering/api-contract-gate.md` recorded this as an open question rather than a
decided fact: "if that role is the cluster owner or otherwise carries BYPASSRLS, then
every RLS policy in the schema is decorative in production too". A superuser or a
BYPASSRLS role sees every row regardless of policy, FORCE or not -- Postgres documents
this plainly. Checked here against a REAL database, both ways: the connection this test
container's admin user has (a superuser, since testcontainers bootstraps one), and the
`tenant_user` role `tests/conftest.py` already provisions as NOSUPERUSER NOBYPASSRLS for
exactly this reason.
"""
from __future__ import annotations

import re

import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.startup_checks import TenantIsolationRestsOnNothing, verify_rls_is_not_bypassed


def _async_url(sync_url: str) -> str:
    return sync_url.replace("postgresql://", "postgresql+asyncpg://", 1)


class TestASuperuserConnectionIsRefused:
    @pytest.mark.asyncio
    async def test_the_bootstrap_admin_role_fails_the_check(self, admin_sync_url):
        """testcontainers' own bootstrap user is a superuser -- the exact shape this
        check exists to catch, reproduced without needing a hand-crafted BYPASSRLS role."""
        engine = create_async_engine(_async_url(admin_sync_url))
        try:
            with pytest.raises(TenantIsolationRestsOnNothing) as exc_info:
                await verify_rls_is_not_bypassed(engine)
            assert "rolsuper=True" in str(exc_info.value) or "rolsuper=true" in str(
                exc_info.value
            ).lower()
        finally:
            await engine.dispose()


class TestTheProvisionedAppRolePasses:
    @pytest.mark.asyncio
    async def test_tenant_user_passes_the_check(self, admin_sync_url):
        """The role conftest provisions for the real-DB suite -- NOSUPERUSER
        NOBYPASSRLS, no table ownership -- must sail through this check, or every
        realdb test that runs as this role would be exercising RLS through a
        connection this check would have refused to boot."""
        tenant_url = re.sub(r"://[^@]+@", "://tenant_user:tenant_pass@", admin_sync_url)
        engine = create_async_engine(_async_url(tenant_url))
        try:
            await verify_rls_is_not_bypassed(engine)  # must not raise
        finally:
            await engine.dispose()


class TestSqliteIsSkippedNotFailed:
    @pytest.mark.asyncio
    async def test_sqlite_connections_are_not_checked(self):
        """SQLite has no roles and no RLS at all -- the whole unit-test suite runs on
        it, so this must be a deliberate skip, not an accidental pass-by-exception."""
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        try:
            await verify_rls_is_not_bypassed(engine)  # must not raise, and not query
        finally:
            await engine.dispose()

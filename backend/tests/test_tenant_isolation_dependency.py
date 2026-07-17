"""Focused tests for the tenant-isolation dependency facade."""

from __future__ import annotations

from uuid import uuid4


class TestTenantIsolationFacade:
    def test_facade_reexports_canonical_dependencies(self):
        from app.core import tenant as core_tenant
        from app.middleware import tenant_isolation

        assert tenant_isolation.get_tenant_org_id is core_tenant.get_tenant_org_id
        assert tenant_isolation.get_tenant_db is core_tenant.get_tenant_db

    async def test_user_without_organization_receives_403_on_assets(self, app):
        from types import SimpleNamespace

        from httpx import ASGITransport, AsyncClient

        from app.api.auth import get_current_active_user

        async def _user_without_organization():
            return SimpleNamespace(
                id=uuid4(),
                email="no-org-assets@test.local",
                role="admin",
                is_active=True,
                organization_id=None,
            )

        app.dependency_overrides[get_current_active_user] = _user_without_organization
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport,
                base_url="http://test",
            ) as client:
                response = await client.get("/api/v1/assets/")
        finally:
            app.dependency_overrides.pop(get_current_active_user, None)

        assert response.status_code == 403
        assert response.json()["detail"] == "User is not associated with an organization"

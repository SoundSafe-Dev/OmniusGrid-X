"""API-level tenant-isolation tests for compliance endpoints."""

from __future__ import annotations

from uuid import uuid4

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _create_vendor_assessment(client, vendor_name: str) -> dict:
    response = await client.post(
        "/api/v1/compliance/vendor-assessments",
        json={"vendor_name": vendor_name},  # FS-902: moved into the body model
    )
    assert response.status_code == 200, response.text
    return response.json()


async def _create_security_asset(
    client, asset_name: str, asset_type: str = "software"
) -> dict:
    response = await client.post(
        "/api/v1/compliance/security-assets",
        params={"asset_type": asset_type, "asset_name": asset_name},
    )
    assert response.status_code == 200, response.text
    return response.json()


# ---------------------------------------------------------------------------
# Vendor assessments
# ---------------------------------------------------------------------------

class TestVendorAssessmentTenantIsolation:
    async def test_orgs_create_separate_assessments(self, client_a, client_b):
        suffix = uuid4().hex[:8]
        a = await _create_vendor_assessment(client_a, f"vendor-a-{suffix}")
        b = await _create_vendor_assessment(client_b, f"vendor-b-{suffix}")
        assert a["vendor_name"] != b["vendor_name"]

    async def test_list_returns_only_callers_org(self, client_a, client_b):
        suffix = uuid4().hex[:8]
        a_name = f"list-a-{suffix}"
        b_name = f"list-b-{suffix}"
        await _create_vendor_assessment(client_a, a_name)
        await _create_vendor_assessment(client_b, b_name)

        list_a = await client_a.get("/api/v1/compliance/vendor-assessments")
        assert list_a.status_code == 200
        names_a = {item["vendor_name"] for item in list_a.json()["items"]}
        assert a_name in names_a
        assert b_name not in names_a

        list_b = await client_b.get("/api/v1/compliance/vendor-assessments")
        assert list_b.status_code == 200
        names_b = {item["vendor_name"] for item in list_b.json()["items"]}
        assert b_name in names_b
        assert a_name not in names_b

    async def test_created_assessment_receives_authenticated_org(
        self, client_a, admin_sync_url, seeded_orgs
    ):
        import psycopg2

        suffix = uuid4().hex[:8]
        created = await _create_vendor_assessment(client_a, f"org-check-{suffix}")

        conn = psycopg2.connect(admin_sync_url)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT organization_id::text FROM vendor_risk_assessments WHERE id = %s;",
                    (created["id"],),
                )
                org_id = cur.fetchone()[0]
        finally:
            conn.close()

        assert org_id == str(seeded_orgs["org_a_id"])

    async def test_cross_tenant_update_returns_404(self, client_a, client_b):
        suffix = uuid4().hex[:8]
        created = await _create_vendor_assessment(client_a, f"update-a-{suffix}")

        foreign = await client_b.put(
            f"/api/v1/compliance/vendor-assessments/{created['id']}",
            json={"status": "completed"},  # FS-902: moved into the body model
        )
        assert foreign.status_code == 404


# ---------------------------------------------------------------------------
# Security assets
# ---------------------------------------------------------------------------

class TestSecurityAssetTenantIsolation:
    async def test_orgs_create_separate_assets(self, client_a, client_b):
        suffix = uuid4().hex[:8]
        a = await _create_security_asset(client_a, f"asset-a-{suffix}")
        b = await _create_security_asset(client_b, f"asset-b-{suffix}")
        assert a["asset_name"] != b["asset_name"]

    async def test_list_returns_only_callers_org(self, client_a, client_b):
        suffix = uuid4().hex[:8]
        a_name = f"sec-a-{suffix}"
        b_name = f"sec-b-{suffix}"
        await _create_security_asset(client_a, a_name)
        await _create_security_asset(client_b, b_name)

        list_a = await client_a.get("/api/v1/compliance/security-assets")
        assert list_a.status_code == 200
        names_a = {item["asset_name"] for item in list_a.json()["items"]}
        assert a_name in names_a
        assert b_name not in names_a

        list_b = await client_b.get("/api/v1/compliance/security-assets")
        assert list_b.status_code == 200
        names_b = {item["asset_name"] for item in list_b.json()["items"]}
        assert b_name in names_b
        assert a_name not in names_b

    async def test_created_asset_receives_authenticated_org(
        self, client_a, admin_sync_url, seeded_orgs
    ):
        import psycopg2

        suffix = uuid4().hex[:8]
        created = await _create_security_asset(client_a, f"asset-org-{suffix}")

        conn = psycopg2.connect(admin_sync_url)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT organization_id::text FROM security_assets WHERE id = %s;",
                    (created["id"],),
                )
                org_id = cur.fetchone()[0]
        finally:
            conn.close()

        assert org_id == str(seeded_orgs["org_a_id"])

    async def test_cross_tenant_update_returns_404(self, client_a, client_b):
        suffix = uuid4().hex[:8]
        created = await _create_security_asset(client_a, f"sec-upd-{suffix}")

        foreign = await client_b.put(
            f"/api/v1/compliance/security-assets/{created['id']}",
            params={"classification": "restricted"},
        )
        assert foreign.status_code == 404

    async def test_cross_tenant_delete_returns_404(self, client_a, client_b):
        suffix = uuid4().hex[:8]
        created = await _create_security_asset(client_a, f"sec-del-{suffix}")

        foreign = await client_b.delete(
            f"/api/v1/compliance/security-assets/{created['id']}"
        )
        assert foreign.status_code == 404


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

class TestComplianceSummary:
    async def test_summary_counts_only_callers_rows(self, client_a, client_b):
        suffix = uuid4().hex[:8]
        await _create_security_asset(client_a, f"sum-a-{suffix}")
        await _create_security_asset(client_b, f"sum-b-{suffix}")
        await _create_vendor_assessment(client_a, f"vsum-a-{suffix}")
        await _create_vendor_assessment(client_b, f"vsum-b-{suffix}")
        await _create_vendor_assessment(client_b, f"vsum-b2-{suffix}")

        summary_a = await client_a.get("/api/v1/compliance/compliance-summary")
        assert summary_a.status_code == 200
        body_a = summary_a.json()
        assert body_a["iso_27001"]["total_assets"] == 1
        assert body_a["soc_2"]["total_vendor_assessments"] == 1

        summary_b = await client_b.get("/api/v1/compliance/compliance-summary")
        assert summary_b.status_code == 200
        body_b = summary_b.json()
        assert body_b["iso_27001"]["total_assets"] == 1
        assert body_b["soc_2"]["total_vendor_assessments"] == 2

# ---------------------------------------------------------------------------
# Auth and finalized ownership
# ---------------------------------------------------------------------------

class TestComplianceAuthAndOwnership:
    async def test_unauthenticated_requests_fail(self, app):
        from httpx import ASGITransport, AsyncClient

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            endpoints = [
                ("GET", "/api/v1/compliance/vendor-assessments"),
                ("GET", "/api/v1/compliance/security-assets"),
                ("GET", "/api/v1/compliance/compliance-summary"),
            ]
            for method, path in endpoints:
                response = await client.request(method, path)
                assert response.status_code == 401, f"{method} {path} expected 401"

    async def test_user_without_organization_is_rejected(self, app):
        from types import SimpleNamespace

        from httpx import ASGITransport, AsyncClient

        from app.api.auth import get_current_active_user

        async def _user_without_organization():
            return SimpleNamespace(
                id=uuid4(),
                email="no-org@test.local",
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
                response = await client.get(
                    "/api/v1/compliance/vendor-assessments"
                )
        finally:
            app.dependency_overrides.pop(get_current_active_user, None)

        assert response.status_code == 403
        assert response.json()["detail"] == "User is not associated with an organization"

    async def test_database_rejects_missing_compliance_ownership(self, admin_sync_url):
        import psycopg2

        conn = psycopg2.connect(admin_sync_url)
        conn.autocommit = True
        try:
            with conn.cursor() as cur:
                with pytest.raises(psycopg2.errors.NotNullViolation):
                    cur.execute(
                        "INSERT INTO security_assets "
                        "(id, asset_type, asset_name, organization_id) "
                        "VALUES (%s, 'hardware', 'missing-owner', NULL);",
                        (str(uuid4()),),
                    )
                with pytest.raises(psycopg2.errors.NotNullViolation):
                    cur.execute(
                        "INSERT INTO vendor_risk_assessments "
                        "(id, vendor_name, organization_id) "
                        "VALUES (%s, 'missing-owner', NULL);",
                        (str(uuid4()),),
                    )
        finally:
            conn.close()

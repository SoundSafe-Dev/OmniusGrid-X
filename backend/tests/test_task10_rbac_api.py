"""Integration coverage for the Task 10 RBAC boundary."""

from __future__ import annotations

import hashlib
from contextlib import asynccontextmanager
from types import SimpleNamespace
from uuid import UUID, uuid4

import psycopg2
import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import settings
from tests.conftest import _make_jwt


def _insert_user(
    admin_sync_url: str,
    organization_id,
    role: str,
    *,
    is_active: bool = True,
) -> tuple[UUID, str]:
    user_id = uuid4()
    email = f"{role}-{user_id.hex[:8]}@test.local"
    conn = psycopg2.connect(admin_sync_url)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO users
                    (id, email, hashed_password, organization_id, role, is_active)
                VALUES (%s, %s, %s, %s, %s, %s);
                """,
                (
                    str(user_id),
                    email,
                    "$2b$12$" + "x" * 53,
                    str(organization_id),
                    role,
                    is_active,
                ),
            )
    finally:
        conn.close()
    return user_id, email


@asynccontextmanager
async def _client_for_user(app, user_id: UUID):
    token = _make_jwt(user_id, settings.JWT_SECRET_KEY, settings.JWT_ALGORITHM)
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"Authorization": f"Bearer {token}"},
    ) as client:
        yield client


@pytest.mark.asyncio
async def test_compliance_mutations_reject_operator(
    app, admin_sync_url, seeded_orgs
):
    operator_id, _ = _insert_user(
        admin_sync_url, seeded_orgs["org_a_id"], "operator"
    )
    assessment_id = uuid4()
    asset_id = uuid4()
    requests = [
        ("POST", "/api/v1/compliance/vendor-assessments", {"vendor_name": "blocked"}),
        (
            "PUT",
            f"/api/v1/compliance/vendor-assessments/{assessment_id}",
            {"status": "completed"},
        ),
        (
            "POST",
            "/api/v1/compliance/security-assets",
            {"asset_type": "software", "asset_name": "blocked"},
        ),
        (
            "PUT",
            f"/api/v1/compliance/security-assets/{asset_id}",
            {"classification": "restricted"},
        ),
        ("DELETE", f"/api/v1/compliance/security-assets/{asset_id}", {}),
    ]

    async with _client_for_user(app, operator_id) as client:
        for method, path, params in requests:
            response = await client.request(method, path, params=params)
            assert response.status_code == 403, f"{method} {path}: {response.text}"


@pytest.mark.asyncio
async def test_inactive_admin_is_rejected_before_compliance_rbac(
    app, admin_sync_url, seeded_orgs
):
    inactive_admin_id, _ = _insert_user(
        admin_sync_url,
        seeded_orgs["org_a_id"],
        "admin",
        is_active=False,
    )
    async with _client_for_user(app, inactive_admin_id) as inactive_admin:
        response = await inactive_admin.post(
            "/api/v1/compliance/vendor-assessments",
            params={"vendor_name": "blocked"},
        )

    assert response.status_code == 400
    assert response.json()["detail"] == "Inactive user"


@pytest.mark.asyncio
async def test_viewer_can_read_report_status_and_download_only(
    app, client_a, admin_sync_url, seeded_orgs, monkeypatch, tmp_path
):
    viewer_id, _ = _insert_user(
        admin_sync_url, seeded_orgs["org_a_id"], "viewer"
    )
    created = await client_a.post(
        "/api/v1/compliance/reports",
        json={"framework": "all", "format": "json"},
    )
    assert created.status_code == 202
    job_id = created.json()["job_id"]

    monkeypatch.setattr(
        "app.services.compliance_report_service.settings.EXPORT_STORAGE_PATH",
        str(tmp_path),
    )
    relative = f"compliance/{seeded_orgs['org_a_id']}/{job_id}.json"
    absolute = tmp_path / relative
    absolute.parent.mkdir(parents=True, exist_ok=True)
    payload = b'{"framework":"all"}'
    absolute.write_bytes(payload)

    conn = psycopg2.connect(admin_sync_url)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE compliance_report_jobs
                SET report_status = 'completed',
                    file_path = %s,
                    filename = %s,
                    media_type = 'application/json',
                    file_size = %s,
                    file_sha256 = %s,
                    completed_at = NOW()
                WHERE id = %s;
                """,
                (
                    relative,
                    f"{job_id}.json",
                    len(payload),
                    hashlib.sha256(payload).hexdigest(),
                    job_id,
                ),
            )
    finally:
        conn.close()

    async with _client_for_user(app, viewer_id) as viewer:
        status_response = await viewer.get(f"/api/v1/compliance/reports/{job_id}")
        download_response = await viewer.get(
            f"/api/v1/compliance/reports/{job_id}/download"
        )
        generate_response = await viewer.post(
            "/api/v1/compliance/reports",
            json={"framework": "all", "format": "json"},
        )
        schedules_response = await viewer.get(
            "/api/v1/compliance/reports/schedules"
        )

    assert status_response.status_code == 200
    assert download_response.status_code == 200
    assert download_response.content == payload
    assert generate_response.status_code == 403
    assert schedules_response.status_code == 403


@pytest.mark.asyncio
async def test_report_reader_remains_tenant_scoped(
    app, client_a, admin_sync_url, seeded_orgs
):
    viewer_b_id, _ = _insert_user(
        admin_sync_url, seeded_orgs["org_b_id"], "viewer"
    )
    created = await client_a.post(
        "/api/v1/compliance/reports",
        json={"framework": "all", "format": "json"},
    )
    job_id = created.json()["job_id"]

    async with _client_for_user(app, viewer_b_id) as viewer_b:
        status_response = await viewer_b.get(
            f"/api/v1/compliance/reports/{job_id}"
        )
        download_response = await viewer_b.get(
            f"/api/v1/compliance/reports/{job_id}/download"
        )

    assert status_response.status_code == 404
    assert download_response.status_code == 404


@pytest.mark.asyncio
async def test_gdpr_self_service_remains_available_to_operator(
    app, admin_sync_url, seeded_orgs
):
    operator_id, operator_email = _insert_user(
        admin_sync_url, seeded_orgs["org_a_id"], "operator"
    )
    async with _client_for_user(app, operator_id) as operator:
        response = await operator.get("/api/v1/gdpr/data-export")

    assert response.status_code == 200
    assert response.json()["user"]["id"] == str(operator_id)
    assert response.json()["user"]["email"] == operator_email


@pytest.mark.asyncio
async def test_gdpr_admin_export_is_role_and_tenant_scoped(
    app, client_a, admin_sync_url, seeded_orgs
):
    target_id, target_email = _insert_user(
        admin_sync_url, seeded_orgs["org_a_id"], "operator"
    )
    operator_id, _ = _insert_user(
        admin_sync_url, seeded_orgs["org_a_id"], "operator"
    )

    owner_response = await client_a.get(
        f"/api/v1/gdpr/admin/users/{target_id}/data-export"
    )
    foreign_response = await client_a.get(
        f"/api/v1/gdpr/admin/users/{seeded_orgs['user_b_id']}/data-export"
    )
    foreign_delete = await client_a.delete(
        f"/api/v1/gdpr/admin/users/{seeded_orgs['user_b_id']}/data-delete",
        params={"confirmation": "DELETE"},
    )
    async with _client_for_user(app, operator_id) as operator:
        forbidden_response = await operator.get(
            f"/api/v1/gdpr/admin/users/{target_id}/data-export"
        )
        forbidden_delete = await operator.delete(
            f"/api/v1/gdpr/admin/users/{target_id}/data-delete",
            params={"confirmation": "DELETE"},
        )

    assert owner_response.status_code == 200
    assert owner_response.json()["user"]["email"] == target_email
    assert foreign_response.status_code == 404
    assert foreign_delete.status_code == 404
    assert forbidden_response.status_code == 403
    assert forbidden_delete.status_code == 403


@pytest.mark.asyncio
async def test_gdpr_admin_delete_anonymizes_tenant_user(
    client_a, admin_sync_url, seeded_orgs
):
    target_id, _ = _insert_user(
        admin_sync_url, seeded_orgs["org_a_id"], "operator"
    )
    consent_id = uuid4()
    conn = psycopg2.connect(admin_sync_url)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO consent_records
                    (id, user_id, consent_type, consent_given)
                VALUES (%s, %s, 'analytics', TRUE);
                """,
                (str(consent_id), str(target_id)),
            )
    finally:
        conn.close()

    response = await client_a.delete(
        f"/api/v1/gdpr/admin/users/{target_id}/data-delete",
        params={"confirmation": "DELETE"},
    )
    assert response.status_code == 200

    conn = psycopg2.connect(admin_sync_url)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT email, full_name, is_active FROM users WHERE id = %s;",
                (str(target_id),),
            )
            email, full_name, is_active = cur.fetchone()
            cur.execute(
                "SELECT COUNT(*) FROM consent_records WHERE user_id = %s;",
                (str(target_id),),
            )
            consent_count = cur.fetchone()[0]
    finally:
        conn.close()

    assert email == f"deleted_{target_id}@deleted.local"
    assert full_name == "Deleted User"
    assert is_active is False
    assert consent_count == 0


@pytest.mark.asyncio
async def test_user_cannot_promote_self_through_context(
    app, admin_sync_url, seeded_orgs
):
    operator_id, _ = _insert_user(
        admin_sync_url, seeded_orgs["org_a_id"], "operator"
    )
    async with _client_for_user(app, operator_id) as operator:
        response = await operator.put(
            "/api/v1/user/context",
            json={"role": "admin"},
        )
        legitimate_update = await operator.put(
            "/api/v1/user/context",
            json={"department": "Operations", "priorities": ["safety"]},
        )

    assert response.status_code == 422
    assert legitimate_update.status_code == 200
    assert legitimate_update.json()["role"] == "operator"


@pytest.mark.asyncio
async def test_dev_registration_forces_operator_role(
    app, admin_sync_url, seeded_orgs, monkeypatch
):
    import app.api.auth as auth_api

    monkeypatch.setattr(
        auth_api,
        "get_password_hash",
        lambda _: "$2b$12$" + "x" * 53,
    )
    email = f"registration-{uuid4().hex[:8]}@test.local"
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/auth/register",
            json={
                "email": email,
                "password": "unused-test-password",
                "organization_id": str(seeded_orgs["org_a_id"]),
                "role": "admin",
            },
        )
    assert response.status_code == 200

    conn = psycopg2.connect(admin_sync_url)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT role FROM users WHERE email = %s;", (email,))
            role = cur.fetchone()[0]
    finally:
        conn.close()
    assert role == "operator"


@pytest.mark.asyncio
async def test_admin_maintenance_routes_require_admin(
    app, admin_sync_url, seeded_orgs
):
    operator_id, _ = _insert_user(
        admin_sync_url, seeded_orgs["org_a_id"], "operator"
    )
    asset_id = uuid4()
    routes = [
        ("POST", "/admin/collectors/collector-1/restart"),
        ("POST", f"/admin/assets/{asset_id}/maintenance"),
        ("POST", "/admin/database/vacuum"),
        ("GET", "/admin/system/status"),
    ]

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as anonymous:
        for method, path in routes:
            response = await anonymous.request(method, path)
            assert response.status_code == 401, f"{method} {path}: {response.text}"

    async with _client_for_user(app, operator_id) as operator:
        for method, path in routes:
            response = await operator.request(method, path)
            assert response.status_code == 403, f"{method} {path}: {response.text}"


@pytest.mark.asyncio
async def test_admin_routes_preserve_public_health_endpoints(client_a, app):
    restart = await client_a.post("/admin/collectors/collector-1/restart")
    invalid_asset = await client_a.post(
        "/admin/assets/not-a-uuid/maintenance"
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as anonymous:
        live = await anonymous.get("/health/live")
        startup = await anonymous.get("/health/startup")
        metrics = await anonymous.get("/metrics")

    assert restart.status_code == 200
    assert invalid_asset.status_code == 422
    assert live.status_code == 200
    assert startup.status_code == 200
    assert metrics.status_code == 200


@pytest.mark.asyncio
async def test_maintenance_update_uses_bound_parameters():
    import app.api.health as health_api

    class FakeSession:
        def __init__(self):
            self.statement = None
            self.parameters = None
            self.committed = False

        async def execute(self, statement, parameters):
            self.statement = statement
            self.parameters = parameters

        async def commit(self):
            self.committed = True

    asset_id = uuid4()
    session = FakeSession()
    response = await health_api.set_maintenance_mode.__wrapped__(
        asset_id=asset_id,
        enabled=True,
        current_user=SimpleNamespace(id=uuid4(), role="admin"),
        db=session,
    )

    sql = str(session.statement)
    assert ":asset_id" in sql
    assert str(asset_id) not in sql
    assert session.parameters == {
        "enabled": True,
        "asset_id": str(asset_id),
    }
    assert session.committed is True
    assert response["asset_id"] == str(asset_id)

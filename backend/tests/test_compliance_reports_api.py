"""API tests for async compliance report endpoints."""

from __future__ import annotations

import hashlib
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.mark.asyncio
async def test_legacy_synchronous_get_is_removed(client_a):
    response = await client_a.get("/api/v1/compliance/report/generate")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_admin_enqueue_returns_202(client_a, seeded_orgs):
    response = await client_a.post(
        "/api/v1/compliance/reports",
        json={"framework": "all", "format": "json"},
    )
    assert response.status_code == 202
    body = response.json()
    assert body["report_status"] == "queued"
    assert body["delivery_status"] == "pending"
    assert body["job_id"]
    assert body["status_url"].endswith(body["job_id"])


@pytest.mark.asyncio
async def test_operator_returns_403(admin_sync_url, app, seeded_orgs):
    import psycopg2

    from app.core.config import settings
    from tests.conftest import _make_jwt

    operator_id = uuid4()
    conn = psycopg2.connect(admin_sync_url)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO users
                (id, email, hashed_password, organization_id, role, is_active)
                VALUES (%s, %s, %s, %s, 'operator', %s);
                """,
                (
                    str(operator_id),
                    f"op-{operator_id.hex[:8]}@test.local",
                    "$2b$12$" + "x" * 53,
                    str(seeded_orgs["org_a_id"]),
                    True,
                ),
            )
    finally:
        conn.close()

    token = _make_jwt(operator_id, settings.JWT_SECRET_KEY, settings.JWT_ALGORITHM)
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"Authorization": f"Bearer {token}"},
    ) as client:
        response = await client.post(
            "/api/v1/compliance/reports",
            json={"framework": "all", "format": "json"},
        )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_missing_organization_returns_403(app):
    from app.api.auth import get_current_active_user
    from app.db.models import User

    async def _user_without_org():
        return User(
            id=uuid4(),
            email="noorg@test.local",
            hashed_password="unused",
            organization_id=None,
            role="admin",
            is_active=True,
        )

    app.dependency_overrides[get_current_active_user] = _user_without_org
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/v1/compliance/reports",
                json={"framework": "all", "format": "json"},
            )
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_invalid_input_returns_422(client_a):
    response = await client_a.post(
        "/api/v1/compliance/reports",
        json={"framework": "hipaa", "format": "json"},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_owner_status_works(client_a):
    created = await client_a.post(
        "/api/v1/compliance/reports",
        json={"framework": "gdpr", "format": "pdf"},
    )
    job_id = created.json()["job_id"]
    status_response = await client_a.get(f"/api/v1/compliance/reports/{job_id}")
    assert status_response.status_code == 200
    assert status_response.json()["framework"] == "gdpr"


@pytest.mark.asyncio
async def test_cross_tenant_status_returns_404(client_a, client_b):
    created = await client_a.post(
        "/api/v1/compliance/reports",
        json={"framework": "all", "format": "json"},
    )
    job_id = created.json()["job_id"]
    response = await client_b.get(f"/api/v1/compliance/reports/{job_id}")
    assert response.status_code == 404
    download = await client_b.get(f"/api/v1/compliance/reports/{job_id}/download")
    assert download.status_code == 404


@pytest.mark.asyncio
async def test_unfinished_download_returns_409(client_a):
    created = await client_a.post(
        "/api/v1/compliance/reports",
        json={"framework": "all", "format": "json"},
    )
    job_id = created.json()["job_id"]
    response = await client_a.get(f"/api/v1/compliance/reports/{job_id}/download")
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_completed_download_returns_correct_bytes(
    client_a, admin_sync_url, seeded_orgs, monkeypatch, tmp_path
):
    import psycopg2

    monkeypatch.setattr(
        "app.services.compliance_report_service.settings.EXPORT_STORAGE_PATH",
        str(tmp_path),
    )
    created = await client_a.post(
        "/api/v1/compliance/reports",
        json={"framework": "all", "format": "json"},
    )
    job_id = created.json()["job_id"]
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

    response = await client_a.get(f"/api/v1/compliance/reports/{job_id}/download")
    assert response.status_code == 200
    assert response.content == payload
    assert response.headers["content-type"].startswith("application/json")


@pytest.mark.asyncio
async def test_missing_file_returns_410(client_a, admin_sync_url, seeded_orgs, tmp_path, monkeypatch):
    import psycopg2

    monkeypatch.setattr(
        "app.services.compliance_report_service.settings.EXPORT_STORAGE_PATH",
        str(tmp_path),
    )
    created = await client_a.post(
        "/api/v1/compliance/reports",
        json={"framework": "all", "format": "json"},
    )
    job_id = created.json()["job_id"]
    relative = f"compliance/{seeded_orgs['org_a_id']}/{job_id}.json"

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
                    completed_at = NOW()
                WHERE id = %s;
                """,
                (relative, f"{job_id}.json", job_id),
            )
    finally:
        conn.close()

    response = await client_a.get(f"/api/v1/compliance/reports/{job_id}/download")
    assert response.status_code == 410


@pytest.mark.asyncio
async def test_corrupt_completed_file_returns_410(
    client_a, admin_sync_url, seeded_orgs, tmp_path, monkeypatch
):
    import psycopg2

    monkeypatch.setattr(
        "app.services.compliance_report_service.settings.EXPORT_STORAGE_PATH",
        str(tmp_path),
    )
    created = await client_a.post(
        "/api/v1/compliance/reports",
        json={"framework": "all", "format": "json"},
    )
    job_id = created.json()["job_id"]
    relative = f"compliance/{seeded_orgs['org_a_id']}/{job_id}.json"
    absolute = tmp_path / relative
    absolute.parent.mkdir(parents=True, exist_ok=True)
    absolute.write_bytes(b"corrupt")

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
                    len(b"expected"),
                    hashlib.sha256(b"expected").hexdigest(),
                    job_id,
                ),
            )
    finally:
        conn.close()

    response = await client_a.get(f"/api/v1/compliance/reports/{job_id}/download")
    assert response.status_code == 410


@pytest.mark.asyncio
async def test_unsafe_file_path_is_rejected(client_a, admin_sync_url, monkeypatch, tmp_path):
    created = await client_a.post(
        "/api/v1/compliance/reports",
        json={"framework": "all", "format": "json"},
    )
    job_id = created.json()["job_id"]
    monkeypatch.setattr(
        "app.services.compliance_report_service.settings.EXPORT_STORAGE_PATH",
        str(tmp_path),
    )

    import psycopg2

    conn = psycopg2.connect(admin_sync_url)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE compliance_report_jobs
                SET report_status = 'completed',
                    file_path = %s,
                    filename = 'evil.json',
                    media_type = 'application/json',
                    completed_at = NOW()
                WHERE id = %s;
                """,
                ("../../etc/passwd", job_id),
            )
    finally:
        conn.close()

    response = await client_a.get(f"/api/v1/compliance/reports/{job_id}/download")
    assert response.status_code == 410


@pytest.mark.asyncio
async def test_sibling_prefix_file_path_is_rejected(
    client_a, admin_sync_url, monkeypatch, tmp_path
):
    created = await client_a.post(
        "/api/v1/compliance/reports",
        json={"framework": "all", "format": "json"},
    )
    job_id = created.json()["job_id"]
    monkeypatch.setattr(
        "app.services.compliance_report_service.settings.EXPORT_STORAGE_PATH",
        str(tmp_path),
    )
    sibling = tmp_path.parent / f"{tmp_path.name}-outside" / "secret.json"
    sibling.parent.mkdir()
    sibling.write_text("outside")
    relative = f"../{sibling.relative_to(tmp_path.parent)}"

    import psycopg2

    conn = psycopg2.connect(admin_sync_url)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE compliance_report_jobs
                SET report_status = 'completed',
                    file_path = %s,
                    filename = 'secret.json',
                    media_type = 'application/json',
                    completed_at = NOW()
                WHERE id = %s;
                """,
                (relative, job_id),
            )
    finally:
        conn.close()

    response = await client_a.get(f"/api/v1/compliance/reports/{job_id}/download")
    assert response.status_code == 410

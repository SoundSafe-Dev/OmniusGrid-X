"""API tests for scheduled compliance report CRUD."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient


def _future_iso(days: int = 30) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).replace(microsecond=0).isoformat()


@pytest.mark.asyncio
async def test_admin_creates_inactive_schedule(client_a, seeded_orgs):
    admin_email = f"a-{seeded_orgs['user_a_id'].hex[:8]}@test.local"
    response = await client_a.post(
        "/api/v1/compliance/reports/schedules",
        json={
            "name": "Monthly SOC2",
            "framework": "soc2",
            "format": "pdf",
            "frequency": "monthly",
            "timezone": "UTC",
            "next_run_at": _future_iso(),
            "recipients": [admin_email],
            "is_active": False,
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["is_active"] is False
    assert body["framework"] == "soc2"
    assert body["recipients"] == [admin_email]


@pytest.mark.asyncio
async def test_active_schedule_rejected_when_email_disabled(client_a, seeded_orgs, monkeypatch):
    from app.core import config as config_module

    monkeypatch.setattr(config_module.settings, "COMPLIANCE_REPORT_EMAIL_ENABLED", False)
    monkeypatch.setattr(config_module.settings, "SMTP_HOST", "smtp.test.local")
    admin_email = f"a-{seeded_orgs['user_a_id'].hex[:8]}@test.local"
    response = await client_a.post(
        "/api/v1/compliance/reports/schedules",
        json={
            "name": "Active",
            "framework": "all",
            "format": "json",
            "frequency": "daily",
            "next_run_at": _future_iso(),
            "recipients": [admin_email],
            "is_active": True,
        },
    )
    assert response.status_code == 503
    assert "email delivery is disabled" in response.json()["detail"]


@pytest.mark.asyncio
async def test_active_schedule_rejected_when_smtp_missing(client_a, seeded_orgs, monkeypatch):
    from app.core import config as config_module

    monkeypatch.setattr(config_module.settings, "COMPLIANCE_REPORT_EMAIL_ENABLED", True)
    monkeypatch.setattr(config_module.settings, "SMTP_HOST", "")
    admin_email = f"a-{seeded_orgs['user_a_id'].hex[:8]}@test.local"
    response = await client_a.post(
        "/api/v1/compliance/reports/schedules",
        json={
            "name": "Active",
            "framework": "all",
            "format": "json",
            "frequency": "daily",
            "next_run_at": _future_iso(),
            "recipients": [admin_email],
            "is_active": True,
        },
    )
    assert response.status_code == 503
    assert "SMTP is not configured" in response.json()["detail"]


@pytest.mark.asyncio
async def test_invalid_frequency_rejected(client_a, seeded_orgs):
    admin_email = f"a-{seeded_orgs['user_a_id'].hex[:8]}@test.local"
    response = await client_a.post(
        "/api/v1/compliance/reports/schedules",
        json={
            "name": "Bad frequency",
            "framework": "all",
            "format": "json",
            "frequency": "hourly",
            "next_run_at": _future_iso(),
            "recipients": [admin_email],
        },
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_invalid_timezone_rejected(client_a, seeded_orgs):
    admin_email = f"a-{seeded_orgs['user_a_id'].hex[:8]}@test.local"
    response = await client_a.post(
        "/api/v1/compliance/reports/schedules",
        json={
            "name": "Bad tz",
            "framework": "all",
            "format": "json",
            "frequency": "daily",
            "timezone": "Not/A/Timezone",
            "next_run_at": _future_iso(),
            "recipients": [admin_email],
        },
    )
    assert response.status_code == 400
    assert "timezone" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_naive_datetime_rejected(client_a, seeded_orgs):
    admin_email = f"a-{seeded_orgs['user_a_id'].hex[:8]}@test.local"
    response = await client_a.post(
        "/api/v1/compliance/reports/schedules",
        json={
            "name": "Naive time",
            "framework": "all",
            "format": "json",
            "frequency": "daily",
            "next_run_at": "2030-01-01T08:00:00",
            "recipients": [admin_email],
        },
    )
    assert response.status_code == 400
    assert "timezone offset" in response.json()["detail"]


@pytest.mark.asyncio
async def test_past_next_run_at_rejected(client_a, seeded_orgs):
    admin_email = f"a-{seeded_orgs['user_a_id'].hex[:8]}@test.local"
    response = await client_a.post(
        "/api/v1/compliance/reports/schedules",
        json={
            "name": "Past",
            "framework": "all",
            "format": "json",
            "frequency": "daily",
            "next_run_at": "2020-01-01T08:00:00Z",
            "recipients": [admin_email],
        },
    )
    assert response.status_code == 400
    assert "future" in response.json()["detail"]


@pytest.mark.asyncio
async def test_invalid_recipient_rejected(client_a):
    response = await client_a.post(
        "/api/v1/compliance/reports/schedules",
        json={
            "name": "Bad recipient",
            "framework": "all",
            "format": "json",
            "frequency": "daily",
            "next_run_at": _future_iso(),
            "recipients": ["not-an-email"],
        },
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_non_admin_recipient_rejected(client_a, seeded_orgs, admin_sync_url):
    import psycopg2

    operator_id = uuid4()
    operator_email = f"op-{operator_id.hex[:8]}@test.local"
    conn = psycopg2.connect(admin_sync_url)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO users
                (id, email, hashed_password, organization_id, role, is_active)
                VALUES (%s, %s, %s, %s, 'operator', TRUE);
                """,
                (
                    str(operator_id),
                    operator_email,
                    "$2b$12$" + "x" * 53,
                    str(seeded_orgs["org_a_id"]),
                ),
            )
    finally:
        conn.close()

    response = await client_a.post(
        "/api/v1/compliance/reports/schedules",
        json={
            "name": "Operator recipient",
            "framework": "all",
            "format": "json",
            "frequency": "daily",
            "next_run_at": _future_iso(),
            "recipients": [operator_email],
        },
    )
    assert response.status_code == 400
    assert "active admins" in response.json()["detail"]


@pytest.mark.asyncio
async def test_recipient_from_other_org_rejected(client_a, seeded_orgs):
    other_admin = f"b-{seeded_orgs['user_b_id'].hex[:8]}@test.local"
    response = await client_a.post(
        "/api/v1/compliance/reports/schedules",
        json={
            "name": "Cross org recipient",
            "framework": "all",
            "format": "json",
            "frequency": "daily",
            "next_run_at": _future_iso(),
            "recipients": [other_admin],
        },
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_duplicate_recipients_normalized(client_a, seeded_orgs):
    admin_email = f"a-{seeded_orgs['user_a_id'].hex[:8]}@test.local"
    response = await client_a.post(
        "/api/v1/compliance/reports/schedules",
        json={
            "name": "Dupes",
            "framework": "all",
            "format": "json",
            "frequency": "daily",
            "next_run_at": _future_iso(),
            "recipients": [admin_email.upper(), f"  {admin_email}  "],
        },
    )
    assert response.status_code == 201
    assert response.json()["recipients"] == [admin_email]


@pytest.mark.asyncio
async def test_list_is_tenant_scoped(client_a, client_b, seeded_orgs):
    admin_email = f"a-{seeded_orgs['user_a_id'].hex[:8]}@test.local"
    created = await client_a.post(
        "/api/v1/compliance/reports/schedules",
        json={
            "name": "Org A only",
            "framework": "all",
            "format": "json",
            "frequency": "weekly",
            "next_run_at": _future_iso(),
            "recipients": [admin_email],
        },
    )
    assert created.status_code == 201
    schedule_id = created.json()["id"]

    owner_list = await client_a.get("/api/v1/compliance/reports/schedules")
    foreign_get = await client_b.get(f"/api/v1/compliance/reports/schedules/{schedule_id}")
    foreign_list = await client_b.get("/api/v1/compliance/reports/schedules")

    assert any(item["id"] == schedule_id for item in owner_list.json()["items"])
    assert foreign_get.status_code == 404
    assert foreign_list.json()["items"] == []


@pytest.mark.asyncio
async def test_operator_schedule_forbidden(admin_sync_url, app, seeded_orgs):
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
                VALUES (%s, %s, %s, %s, 'operator', TRUE);
                """,
                (
                    str(operator_id),
                    f"op-{operator_id.hex[:8]}@test.local",
                    "$2b$12$" + "x" * 53,
                    str(seeded_orgs["org_a_id"]),
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
        response = await client.get("/api/v1/compliance/reports/schedules")
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_update_preserves_omitted_fields(client_a, seeded_orgs):
    admin_email = f"a-{seeded_orgs['user_a_id'].hex[:8]}@test.local"
    created = await client_a.post(
        "/api/v1/compliance/reports/schedules",
        json={
            "name": "Original",
            "framework": "gdpr",
            "format": "pdf",
            "frequency": "quarterly",
            "timezone": "UTC",
            "next_run_at": _future_iso(40),
            "recipients": [admin_email],
        },
    )
    schedule_id = created.json()["id"]
    updated = await client_a.put(
        f"/api/v1/compliance/reports/schedules/{schedule_id}",
        json={"name": "Renamed"},
    )
    assert updated.status_code == 200
    body = updated.json()
    assert body["name"] == "Renamed"
    assert body["framework"] == "gdpr"
    assert body["format"] == "pdf"
    assert body["frequency"] == "quarterly"

    persisted = await client_a.get(
        f"/api/v1/compliance/reports/schedules/{schedule_id}"
    )
    assert persisted.status_code == 200
    assert persisted.json()["name"] == "Renamed"


@pytest.mark.asyncio
async def test_cross_tenant_update_and_delete_are_hidden(
    client_a, client_b, seeded_orgs
):
    admin_email = f"a-{seeded_orgs['user_a_id'].hex[:8]}@test.local"
    created = await client_a.post(
        "/api/v1/compliance/reports/schedules",
        json={
            "name": "Org A protected",
            "framework": "all",
            "format": "json",
            "frequency": "daily",
            "next_run_at": _future_iso(),
            "recipients": [admin_email],
        },
    )
    assert created.status_code == 201
    schedule_id = created.json()["id"]

    foreign_update = await client_b.put(
        f"/api/v1/compliance/reports/schedules/{schedule_id}",
        json={"name": "Foreign change"},
    )
    foreign_delete = await client_b.delete(
        f"/api/v1/compliance/reports/schedules/{schedule_id}"
    )
    owner = await client_a.get(
        f"/api/v1/compliance/reports/schedules/{schedule_id}"
    )

    assert foreign_update.status_code == 404
    assert foreign_delete.status_code == 404
    assert owner.status_code == 200
    assert owner.json()["name"] == "Org A protected"


@pytest.mark.asyncio
async def test_deletion_leaves_historical_jobs(client_a, seeded_orgs, admin_sync_url):
    import psycopg2

    admin_email = f"a-{seeded_orgs['user_a_id'].hex[:8]}@test.local"
    created = await client_a.post(
        "/api/v1/compliance/reports/schedules",
        json={
            "name": "To delete",
            "framework": "all",
            "format": "json",
            "frequency": "daily",
            "next_run_at": _future_iso(),
            "recipients": [admin_email],
        },
    )
    schedule_id = created.json()["id"]
    job_id = uuid4()
    conn = psycopg2.connect(admin_sync_url)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO compliance_report_jobs
                (id, organization_id, framework, format, schedule_id, scheduled_for,
                 report_status, delivery_status)
                VALUES (%s, %s, 'all', 'json', %s, now(), 'completed', 'sent');
                """,
                (str(job_id), str(seeded_orgs["org_a_id"]), schedule_id),
            )
    finally:
        conn.close()

    deleted = await client_a.delete(f"/api/v1/compliance/reports/schedules/{schedule_id}")
    assert deleted.status_code == 200

    conn = psycopg2.connect(admin_sync_url)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT schedule_id FROM compliance_report_jobs WHERE id = %s;",
                (str(job_id),),
            )
            assert cur.fetchone()[0] is None
            cur.execute(
                "SELECT count(*) FROM compliance_report_jobs WHERE id = %s;",
                (str(job_id),),
            )
            assert cur.fetchone()[0] == 1
    finally:
        conn.close()

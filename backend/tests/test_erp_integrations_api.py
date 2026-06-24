"""API coverage for ERP integration tenant, RBAC, and action behavior."""

from __future__ import annotations

from contextlib import asynccontextmanager
from uuid import UUID, uuid4

import psycopg2
import pytest
from httpx import ASGITransport, AsyncClient
from psycopg2.extras import Json

from app.core.config import settings
from tests.conftest import _make_jwt


ERP_BASE = "/api/v1/erp/integrations"
SECRET_VALUE = "super-secret-api-key"


def _erp_payload(**overrides):
    payload = {
        "integration_name": "Warehouse ERP",
        "erp_type": "generic",
        "erp_version": "2026.1",
        "auth_type": "api_key",
        "base_url": "https://erp.example.test",
        "auth_config": {"api_key": SECRET_VALUE, "header_name": "X-ERP-Key"},
        "rate_limit": {"requests_per_minute": 60, "burst_limit": 10},
        "timeout": 20,
        "sync_schedule": "*/15 * * * *",
        "sync_frequency_minutes": 15,
        "health_check_path": "/health",
        "headers": {"X-Tenant": "test"},
    }
    payload.update(overrides)
    return payload


def _insert_user(admin_sync_url: str, organization_id, role: str) -> UUID:
    user_id = uuid4()
    conn = psycopg2.connect(admin_sync_url)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO users
                    (id, email, hashed_password, organization_id, role, is_active)
                VALUES (%s, %s, %s, %s, %s, true);
                """,
                (
                    str(user_id),
                    f"{role}-{user_id.hex[:8]}@test.local",
                    "$2b$12$" + "x" * 53,
                    str(organization_id),
                    role,
                ),
            )
    finally:
        conn.close()
    return user_id


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


def _insert_integration(
    admin_sync_url: str,
    organization_id,
    user_id,
    *,
    integration_type: str = "erp",
    is_active: bool = True,
    name: str = "Seeded ERP",
) -> str:
    integration_id = uuid4()
    config = {
        "erp_type": "generic",
        "auth_type": "api_key",
        "base_url": "https://erp.example.test",
        "auth_config": {"api_key": SECRET_VALUE, "header_name": "X-ERP-Key"},
        "rate_limit": {"requests_per_minute": 60, "burst_limit": 10},
        "timeout": 20,
        "health_check_path": "/health",
        "entity_path_template": "/{entity_type}",
        "headers": {},
    }
    conn = psycopg2.connect(admin_sync_url)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO integration_configurations
                    (
                        id, organization_id, integration_type, integration_name,
                        configuration, authentication, is_active, created_by,
                        erp_type, erp_version, sync_schedule,
                        sync_frequency_minutes
                    )
                VALUES
                    (%s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s,
                     'generic', '2026.1', '*/15 * * * *', 15);
                """,
                (
                    str(integration_id),
                    str(organization_id),
                    integration_type,
                    name,
                    Json(config),
                    Json(config["auth_config"]),
                    is_active,
                    str(user_id),
                ),
            )
    finally:
        conn.close()
    return str(integration_id)


def _sync_status_rows(admin_sync_url: str, integration_id: str) -> list[tuple[str, str]]:
    conn = psycopg2.connect(admin_sync_url)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT entity_type, last_sync_status
                FROM erp_sync_status
                WHERE integration_id = %s
                ORDER BY entity_type;
                """,
                (integration_id,),
            )
            return cur.fetchall()
    finally:
        conn.close()


def _erp_entity_rows(admin_sync_url: str, integration_id: str) -> list[tuple[str, dict]]:
    conn = psycopg2.connect(admin_sync_url)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT entity_id, entity_data
                FROM erp_entities
                WHERE integration_id = %s
                ORDER BY entity_id;
                """,
                (integration_id,),
            )
            return cur.fetchall()
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_admin_can_crud_own_erp_integration(client_a):
    created = await client_a.post(ERP_BASE, json=_erp_payload())
    assert created.status_code == 201, created.text
    body = created.json()
    integration_id = body["id"]
    assert body["integration_name"] == "Warehouse ERP"
    assert body["erp_type"] == "generic"
    assert body["auth_type"] == "api_key"
    assert SECRET_VALUE not in created.text

    listing = await client_a.get(ERP_BASE)
    assert listing.status_code == 200
    assert integration_id in {row["id"] for row in listing.json()}
    assert SECRET_VALUE not in listing.text

    fetched = await client_a.get(f"{ERP_BASE}/{integration_id}")
    assert fetched.status_code == 200
    assert fetched.json()["id"] == integration_id
    assert SECRET_VALUE not in fetched.text

    updated = await client_a.put(
        f"{ERP_BASE}/{integration_id}",
        json={
            "integration_name": "Updated ERP",
            "erp_version": "2026.2",
            "timeout": 45,
            "auth_config": {"api_key": "rotated-secret", "header_name": "X-ERP-Key"},
            "is_active": False,
        },
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["integration_name"] == "Updated ERP"
    assert updated.json()["erp_version"] == "2026.2"
    assert updated.json()["is_active"] is False
    assert "rotated-secret" not in updated.text

    deleted = await client_a.delete(f"{ERP_BASE}/{integration_id}")
    assert deleted.status_code == 204

    missing = await client_a.get(f"{ERP_BASE}/{integration_id}")
    assert missing.status_code == 404


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["operator", "viewer"])
async def test_operator_and_viewer_cannot_mutate_or_trigger_erp_actions(
    app, client_a, admin_sync_url, seeded_orgs, monkeypatch, role
):
    created = await client_a.post(ERP_BASE, json=_erp_payload())
    assert created.status_code == 201, created.text
    integration_id = created.json()["id"]
    mapping_id = str(uuid4())
    user_id = _insert_user(admin_sync_url, seeded_orgs["org_a_id"], role)

    def _connector_factory_should_not_run(_integration):
        raise AssertionError("RBAC should reject before ERP connector creation")

    monkeypatch.setattr(
        "app.api.erp_integrations.create_erp_connector",
        _connector_factory_should_not_run,
    )

    requests = [
        ("POST", ERP_BASE, _erp_payload(integration_name=f"{role} blocked")),
        ("PUT", f"{ERP_BASE}/{integration_id}", {"integration_name": "blocked"}),
        ("DELETE", f"{ERP_BASE}/{integration_id}", None),
        ("POST", f"{ERP_BASE}/{integration_id}/test", None),
        ("POST", f"{ERP_BASE}/{integration_id}/sync", {"entity_type": "items"}),
        (
            "POST",
            f"{ERP_BASE}/{integration_id}/mappings",
            {
                "source_entity": "Item",
                "source_field": "id",
                "target_entity": "Asset",
                "target_field": "external_id",
            },
        ),
        (
            "PUT",
            f"{ERP_BASE}/{integration_id}/mappings/{mapping_id}",
            {"target_field": "external_ref"},
        ),
        ("DELETE", f"{ERP_BASE}/{integration_id}/mappings/{mapping_id}", None),
    ]

    async with _client_for_user(app, user_id) as role_client:
        for method, path, payload in requests:
            response = await role_client.request(method, path, json=payload)
            assert response.status_code == 403, f"{method} {path}: {response.text}"


@pytest.mark.asyncio
async def test_cross_tenant_lookup_returns_404_for_erp_endpoints(
    client_a, client_b, monkeypatch
):
    created = await client_a.post(ERP_BASE, json=_erp_payload())
    assert created.status_code == 201, created.text
    integration_id = created.json()["id"]

    async def _sync_should_not_run(**_kwargs):
        raise AssertionError("Cross-tenant sync should not enqueue background work")

    monkeypatch.setattr("app.api.erp_integrations._run_sync_background", _sync_should_not_run)

    requests = [
        ("GET", f"{ERP_BASE}/{integration_id}", None),
        ("PUT", f"{ERP_BASE}/{integration_id}", {"integration_name": "foreign"}),
        ("DELETE", f"{ERP_BASE}/{integration_id}", None),
        ("POST", f"{ERP_BASE}/{integration_id}/test", None),
        ("POST", f"{ERP_BASE}/{integration_id}/sync", {"entity_type": "items"}),
        ("GET", f"{ERP_BASE}/{integration_id}/sync-status", None),
    ]
    for method, path, payload in requests:
        response = await client_b.request(method, path, json=payload)
        assert response.status_code == 404, f"{method} {path}: {response.text}"


@pytest.mark.asyncio
async def test_non_erp_integration_configuration_rows_are_rejected(
    client_a, admin_sync_url, seeded_orgs, monkeypatch
):
    integration_id = _insert_integration(
        admin_sync_url,
        seeded_orgs["org_a_id"],
        seeded_orgs["user_a_id"],
        integration_type="geotab",
        name="Not ERP",
    )

    async def _sync_should_not_run(**_kwargs):
        raise AssertionError("Non-ERP row should not enqueue background work")

    monkeypatch.setattr("app.api.erp_integrations._run_sync_background", _sync_should_not_run)

    requests = [
        ("GET", f"{ERP_BASE}/{integration_id}", None),
        ("PUT", f"{ERP_BASE}/{integration_id}", {"integration_name": "blocked"}),
        ("DELETE", f"{ERP_BASE}/{integration_id}", None),
        ("POST", f"{ERP_BASE}/{integration_id}/test", None),
        ("POST", f"{ERP_BASE}/{integration_id}/sync", {"entity_type": "items"}),
        ("GET", f"{ERP_BASE}/{integration_id}/sync-status", None),
    ]
    for method, path, payload in requests:
        response = await client_a.request(method, path, json=payload)
        assert response.status_code == 404, f"{method} {path}: {response.text}"


class _FakeConnector:
    def __init__(self, status: str):
        self.status = status

    def validate_config(self) -> bool:
        return True

    async def health_check(self) -> dict[str, str]:
        return {"status": self.status, "message": f"{self.status} check"}


@pytest.mark.asyncio
async def test_connection_test_persists_health_without_leaking_secrets(
    client_a, monkeypatch
):
    created = await client_a.post(ERP_BASE, json=_erp_payload())
    assert created.status_code == 201, created.text
    integration_id = created.json()["id"]

    statuses = iter(["healthy", "unhealthy"])

    def _fake_connector_factory(_integration):
        return _FakeConnector(next(statuses))

    monkeypatch.setattr(
        "app.api.erp_integrations.create_erp_connector",
        _fake_connector_factory,
    )

    healthy = await client_a.post(f"{ERP_BASE}/{integration_id}/test")
    assert healthy.status_code == 200, healthy.text
    assert healthy.json()["status"] == "healthy"
    assert SECRET_VALUE not in healthy.text

    fetched_after_healthy = await client_a.get(f"{ERP_BASE}/{integration_id}")
    assert fetched_after_healthy.status_code == 200
    assert fetched_after_healthy.json()["health_status"] == "healthy"
    assert SECRET_VALUE not in fetched_after_healthy.text

    unhealthy = await client_a.post(f"{ERP_BASE}/{integration_id}/test")
    assert unhealthy.status_code == 200, unhealthy.text
    assert unhealthy.json()["status"] == "unhealthy"
    assert SECRET_VALUE not in unhealthy.text

    fetched_after_unhealthy = await client_a.get(f"{ERP_BASE}/{integration_id}")
    assert fetched_after_unhealthy.status_code == 200
    assert fetched_after_unhealthy.json()["health_status"] == "unhealthy"


@pytest.mark.asyncio
async def test_connection_test_rejects_invalid_connector_config(client_a, monkeypatch):
    created = await client_a.post(ERP_BASE, json=_erp_payload())
    assert created.status_code == 201, created.text
    integration_id = created.json()["id"]

    class InvalidConnector:
        def validate_config(self) -> bool:
            return False

        async def health_check(self):
            raise AssertionError("health_check should not run for invalid config")

    monkeypatch.setattr(
        "app.api.erp_integrations.create_erp_connector",
        lambda _integration: InvalidConnector(),
    )

    response = await client_a.post(f"{ERP_BASE}/{integration_id}/test")

    assert response.status_code == 400
    assert response.json()["detail"] == "ERP integration configuration is invalid"
    assert SECRET_VALUE not in response.text


@pytest.mark.asyncio
async def test_manual_sync_trigger_creates_queued_status(
    client_a, admin_sync_url, monkeypatch
):
    created = await client_a.post(ERP_BASE, json=_erp_payload())
    assert created.status_code == 201, created.text
    integration_id = created.json()["id"]
    captured = {}

    async def _fake_background_sync(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr("app.api.erp_integrations._run_sync_background", _fake_background_sync)

    response = await client_a.post(
        f"{ERP_BASE}/{integration_id}/sync",
        json={"entity_type": "items", "filters": {"updated_since": "2026-01-01"}, "limit": 25},
    )

    assert response.status_code == 200, response.text
    assert response.json()["integration_id"] == integration_id
    assert response.json()["entity_type"] == "items"
    assert response.json()["status"] == "queued"
    assert captured["integration_id"] == integration_id
    assert captured["entity_type"] == "items"
    assert captured["filters"] == {"updated_since": "2026-01-01"}
    assert captured["limit"] == 25
    assert _sync_status_rows(admin_sync_url, integration_id) == [("items", "queued")]

    status_response = await client_a.get(f"{ERP_BASE}/{integration_id}/sync-status")
    assert status_response.status_code == 200
    assert status_response.json()[0]["entity_type"] == "items"
    assert status_response.json()[0]["last_sync_status"] == "queued"


@pytest.mark.asyncio
async def test_manual_sync_trigger_rejects_inactive_integration(
    client_a, admin_sync_url, seeded_orgs, monkeypatch
):
    integration_id = _insert_integration(
        admin_sync_url,
        seeded_orgs["org_a_id"],
        seeded_orgs["user_a_id"],
        is_active=False,
        name="Inactive ERP",
    )

    async def _sync_should_not_run(**_kwargs):
        raise AssertionError("Inactive integration should not enqueue background work")

    monkeypatch.setattr("app.api.erp_integrations._run_sync_background", _sync_should_not_run)

    response = await client_a.post(
        f"{ERP_BASE}/{integration_id}/sync",
        json={"entity_type": "items"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "ERP integration is inactive"
    assert _sync_status_rows(admin_sync_url, integration_id) == []


@pytest.mark.asyncio
async def test_background_sync_upserts_entities_and_resets_tenant_context(
    app, client_a, admin_sync_url, seeded_orgs, monkeypatch
):
    from sqlalchemy import text

    from app.api import erp_integrations as erp_api

    created = await client_a.post(ERP_BASE, json=_erp_payload())
    assert created.status_code == 201, created.text
    integration_id = created.json()["id"]

    class FetchingConnector:
        def __init__(self):
            self.calls = 0

        async def fetch_data(self, entity_type, filters=None, limit=None):
            self.calls += 1
            assert entity_type == "items"
            assert filters == {"updated_since": "2026-01-01"}
            assert limit == 50
            return [
                {"id": "item-1", "name": f"Widget v{self.calls}"},
                {"id": "item-2", "name": "Bolt"},
            ]

    connector = FetchingConnector()
    monkeypatch.setattr(
        "app.api.erp_integrations.create_erp_connector",
        lambda _integration: connector,
    )

    for _ in range(2):
        await erp_api._run_sync_background(
            integration_id=integration_id,
            org_id=str(seeded_orgs["org_a_id"]),
            entity_type="items",
            filters={"updated_since": "2026-01-01"},
            limit=50,
        )

    assert _sync_status_rows(admin_sync_url, integration_id) == [("items", "success")]
    rows = _erp_entity_rows(admin_sync_url, integration_id)
    assert rows == [
        ("item-1", {"id": "item-1", "name": "Widget v2"}),
        ("item-2", {"id": "item-2", "name": "Bolt"}),
    ]

    async with erp_api.AsyncSessionLocal() as session:
        value = await session.scalar(text("SELECT current_setting('app.current_org_id', true)"))
    assert value in ("", None)


@pytest.mark.asyncio
async def test_background_sync_records_failure_and_alerts(
    app, client_a, admin_sync_url, seeded_orgs, monkeypatch
):
    from app.api import erp_integrations as erp_api

    created = await client_a.post(ERP_BASE, json=_erp_payload())
    assert created.status_code == 201, created.text
    integration_id = created.json()["id"]
    alerts = []

    class FailingConnector:
        async def fetch_data(self, entity_type, filters=None, limit=None):
            raise TimeoutError("ERP timeout")

    class CapturingErrorHandler:
        def __init__(self, org_id, captured_integration_id):
            self.org_id = org_id
            self.integration_id = captured_integration_id

        async def _send_alert(self, failure_count):
            alerts.append(
                {
                    "organization_id": self.org_id,
                    "integration_id": self.integration_id,
                    "failure_count": failure_count,
                }
            )

    monkeypatch.setattr(
        "app.api.erp_integrations.create_erp_connector",
        lambda _integration: FailingConnector(),
    )
    monkeypatch.setattr("app.api.erp_integrations.ERPErrorHandler", CapturingErrorHandler)

    await erp_api._run_sync_background(
        integration_id=integration_id,
        org_id=str(seeded_orgs["org_a_id"]),
        entity_type="items",
        filters={},
        limit=50,
    )

    assert _sync_status_rows(admin_sync_url, integration_id) == [("items", "failed")]
    assert alerts == [
        {
            "organization_id": str(seeded_orgs["org_a_id"]),
            "integration_id": integration_id,
            "failure_count": 1,
        }
    ]

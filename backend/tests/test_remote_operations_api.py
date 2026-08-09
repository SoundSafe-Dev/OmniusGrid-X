"""Real PostgreSQL coverage for Fleet remote-operation RBAC and durability."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

import psycopg2
import pytest
import pytest_asyncio
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient
from limits.storage import MemoryStorage
from limits.strategies import FixedWindowRateLimiter
from slowapi.errors import RateLimitExceeded
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import settings
from app.core.tenant import get_tenant_db, get_tenant_org_id
from app.db import database as db_module
from app.middleware.rate_limit import (
    limiter,
    rate_limit_exceeded_handler,
    remote_operation_limiter,
)
from app.services.command_executor import CommandExecutor, command_executor
from tests.conftest import _make_jwt


@pytest.fixture
def remote_operation_rate_store():
    old_enabled = remote_operation_limiter.enabled
    old_storage = remote_operation_limiter._storage
    old_strategy = remote_operation_limiter._limiter
    storage = MemoryStorage()
    remote_operation_limiter._storage = storage
    remote_operation_limiter._limiter = FixedWindowRateLimiter(storage)
    remote_operation_limiter.enabled = True
    remote_operation_limiter.reset()
    try:
        yield
    finally:
        remote_operation_limiter.reset()
        remote_operation_limiter.enabled = old_enabled
        remote_operation_limiter._storage = old_storage
        remote_operation_limiter._limiter = old_strategy


@pytest_asyncio.fixture
async def remote_operations_app(
    tenant_async_url,
    remote_operation_rate_store,
    monkeypatch,
):
    from app.api import commands, fleet_agents

    engine = create_async_engine(tenant_async_url, future=True)
    session_maker = async_sessionmaker(
        engine,
        expire_on_commit=False,
        autoflush=False,
    )

    async def override_get_db():
        async with session_maker() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    async def override_tenant_db(
        org_id: UUID = Depends(get_tenant_org_id),
    ):
        async with session_maker() as session:
            try:
                await session.execute(
                    text(
                        "SELECT set_config("
                        "'app.current_org_id', :org_id, false)"
                    ),
                    {"org_id": str(org_id)},
                )
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise
            finally:
                await session.execute(
                    text("SELECT set_config('app.current_org_id', '', false)")
                )
                await session.commit()

    old_factory = command_executor._session_factory
    command_executor._session_factory = session_maker
    monkeypatch.setattr(command_executor, "_broadcast_safely", _noop_broadcast)

    app = FastAPI()
    app.state.remote_operation_limiter = remote_operation_limiter
    app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)
    app.include_router(fleet_agents.router, prefix="/api/v1/fleet")
    app.include_router(commands.router, prefix="/api/v1/commands")
    app.dependency_overrides[db_module.get_db] = override_get_db
    app.dependency_overrides[get_tenant_db] = override_tenant_db
    try:
        yield app, session_maker
    finally:
        app.dependency_overrides.clear()
        command_executor._session_factory = old_factory
        await engine.dispose()


async def _noop_broadcast(*_args, **_kwargs):
    return None


def _seed_remote_assets(admin_sync_url: str, seeded_orgs: dict) -> dict[str, UUID]:
    asset_type_id = uuid4()
    asset_a = uuid4()
    asset_b = uuid4()
    conn = psycopg2.connect(admin_sync_url)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO asset_types (id, name, category)
                VALUES (%s, %s, 'collector');
                """,
                (str(asset_type_id), f"Collector {asset_type_id.hex[:8]}"),
            )
            cur.execute(
                """
                INSERT INTO assets
                    (id, organization_id, workcell_id, asset_type_id, name,
                     is_active, agent_id, agent_version,
                     agent_last_heartbeat, agent_version_valid,
                     agent_version_major, agent_version_minor,
                     agent_version_patch)
                VALUES
                    (%s, %s, %s, %s, 'Org A collector', TRUE,
                     'agent-a', '1.0.0', NOW(), TRUE, 1, 0, 0),
                    (%s, %s, %s, %s, 'Org B collector', TRUE,
                     'agent-b', '1.0.0', NOW(), TRUE, 1, 0, 0);
                """,
                (
                    str(asset_a),
                    str(seeded_orgs["org_a_id"]),
                    str(seeded_orgs["workcell_a_id"]),
                    str(asset_type_id),
                    str(asset_b),
                    str(seeded_orgs["org_b_id"]),
                    str(seeded_orgs["workcell_b_id"]),
                    str(asset_type_id),
                ),
            )
    finally:
        conn.close()
    return {"asset_a": asset_a, "asset_b": asset_b}


def _create_user(
    admin_sync_url: str,
    organization_id: UUID,
    role: str,
) -> UUID:
    user_id = uuid4()
    conn = psycopg2.connect(admin_sync_url)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO users
                    (id, email, hashed_password, organization_id, role, is_active)
                VALUES (%s, %s, %s, %s, %s, TRUE);
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


def _token(user_id: UUID) -> str:
    return _make_jwt(
        user_id,
        settings.JWT_SECRET_KEY,
        settings.JWT_ALGORITHM,
    )


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_operator_can_submit_but_viewer_and_cross_tenant_cannot(
    remote_operations_app,
    seeded_orgs,
    admin_sync_url,
):
    app, _ = remote_operations_app
    assets = _seed_remote_assets(admin_sync_url, seeded_orgs)
    operator_id = _create_user(
        admin_sync_url,
        seeded_orgs["org_a_id"],
        "operator",
    )
    viewer_id = _create_user(
        admin_sync_url,
        seeded_orgs["org_a_id"],
        "viewer",
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        submitted = await client.post(
            f"/api/v1/fleet/agents/{assets['asset_a']}/operations/logs",
            headers=_headers(_token(operator_id)),
            json={"schema_version": 1, "limit": 10, "levels": ["error"]},
        )
        viewer = await client.post(
            f"/api/v1/fleet/agents/{assets['asset_a']}/operations/diagnostics",
            headers=_headers(_token(viewer_id)),
            json={"schema_version": 1},
        )
        cross_tenant = await client.post(
            f"/api/v1/fleet/agents/{assets['asset_b']}/operations/diagnostics",
            headers=_headers(_token(operator_id)),
            json={"schema_version": 1},
        )
        generic_bypass = await client.post(
            "/api/v1/commands/submit",
            headers=_headers(_token(operator_id)),
            json={
                "asset_id": str(assets["asset_a"]),
                "command_type": "system",
                "action_id": "agent_fetch_logs",
                "parameters": {"schema_version": 1},
            },
        )

    assert submitted.status_code == 202, submitted.text
    assert submitted.json()["action"] == "agent_fetch_logs"
    assert viewer.status_code == 403
    assert cross_tenant.status_code == 404
    assert generic_bypass.status_code == 400

    conn = psycopg2.connect(admin_sync_url)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT c.action_id, c.parameters, a.action, a.details
                FROM commands c
                JOIN audit_logs a ON a.resource_id = c.id::text
                WHERE c.id = %s;
                """,
                (submitted.json()["command_id"],),
            )
            action_id, parameters, audit_action, details = cur.fetchone()
    finally:
        conn.close()
    assert action_id == "agent_fetch_logs"
    assert parameters == {
        "schema_version": 1,
        "limit": 10,
        "levels": ["error"],
    }
    assert audit_action == "remote_agent_operation_requested"
    assert details["status"] == "requested"
    assert "result" not in details


@pytest.mark.asyncio
async def test_ack_result_survives_another_executor_and_terminal_audit_is_safe(
    remote_operations_app,
    seeded_orgs,
    admin_sync_url,
):
    app, session_maker = remote_operations_app
    assets = _seed_remote_assets(admin_sync_url, seeded_orgs)
    operator_id = _create_user(
        admin_sync_url,
        seeded_orgs["org_a_id"],
        "operator",
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        submitted = await client.post(
            f"/api/v1/fleet/agents/{assets['asset_a']}/operations/logs",
            headers=_headers(_token(operator_id)),
            json={"schema_version": 1, "limit": 1, "levels": []},
        )
        assert submitted.status_code == 202, submitted.text
        command_id = submitted.json()["command_id"]

        second_replica = CommandExecutor(session_factory=session_maker)
        second_replica._broadcast_safely = _noop_broadcast
        handled = await second_replica.handle_command_ack(
            {
                "command_id": command_id,
                "organization_id": str(seeded_orgs["org_a_id"]),
                "asset_id": str(assets["asset_a"]),
                "agent_id": "agent-a",
                "status": "completed",
                "success": True,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "result": {
                    "schema_version": 1,
                    "action": "agent_fetch_logs",
                    "agent_id": "agent-a",
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                    "entries": [
                        {
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                            "level": "error",
                            "event": "collector_error",
                            "fields": {"password": "must-not-persist"},
                        }
                    ],
                    "returned_count": 1,
                    "available_count": 1,
                    "truncated": False,
                    "redacted_fields": 0,
                },
            }
        )
        status_response = await client.get(
            (
                f"/api/v1/fleet/agents/{assets['asset_a']}"
                f"/operations/{command_id}"
            ),
            headers=_headers(_token(operator_id)),
        )

    assert handled is True
    assert status_response.status_code == 200, status_response.text
    result = status_response.json()["result"]
    assert result["entries"][0]["fields"]["password"] == "<redacted>"

    conn = psycopg2.connect(admin_sync_url)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT action, details::text
                FROM audit_logs
                WHERE resource_id = %s
                ORDER BY timestamp;
                """,
                (command_id,),
            )
            audits = cur.fetchall()
    finally:
        conn.close()
    assert [row[0] for row in audits] == [
        "remote_agent_operation_requested",
        "remote_agent_operation_completed",
    ]
    assert "collector_error" not in audits[1][1]
    assert "must-not-persist" not in audits[1][1]


@pytest.mark.asyncio
async def test_restart_is_single_flight_then_cooldown(
    remote_operations_app,
    seeded_orgs,
    admin_sync_url,
):
    app, _ = remote_operations_app
    assets = _seed_remote_assets(admin_sync_url, seeded_orgs)
    operator_id = _create_user(
        admin_sync_url,
        seeded_orgs["org_a_id"],
        "operator",
    )
    headers = _headers(_token(operator_id))
    path = (
        f"/api/v1/fleet/agents/{assets['asset_a']}"
        "/operations/restart-collector"
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        first = await client.post(
            path,
            headers=headers,
            json={"schema_version": 1, "readiness_timeout_seconds": 5},
        )
        second = await client.post(
            path,
            headers=headers,
            json={"schema_version": 1, "readiness_timeout_seconds": 5},
        )
        assert first.status_code == 202, first.text
        assert second.status_code == 409, second.text

        conn = psycopg2.connect(admin_sync_url)
        conn.autocommit = True
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE commands
                    SET status = 'completed', completed_at = NOW()
                    WHERE id = %s;
                    """,
                    (first.json()["command_id"],),
                )
        finally:
            conn.close()

        cooldown = await client.post(
            path,
            headers=headers,
            json={"schema_version": 1, "readiness_timeout_seconds": 5},
        )

    assert cooldown.status_code == 429
    assert int(cooldown.headers["Retry-After"]) > 0


@pytest.mark.asyncio
async def test_remote_limit_stays_enabled_when_global_limit_is_off(
    remote_operations_app,
    seeded_orgs,
    admin_sync_url,
):
    app, _ = remote_operations_app
    assets = _seed_remote_assets(admin_sync_url, seeded_orgs)
    operator_id = _create_user(
        admin_sync_url,
        seeded_orgs["org_a_id"],
        "operator",
    )
    headers = _headers(_token(operator_id))
    path = (
        f"/api/v1/fleet/agents/{assets['asset_a']}"
        "/operations/diagnostics"
    )
    old_global_enabled = limiter.enabled
    limiter.enabled = False
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            responses = [
                await client.post(
                    path,
                    headers=headers,
                    json={"schema_version": 1},
                )
                for _ in range(9)
            ]
    finally:
        limiter.enabled = old_global_enabled

    assert [response.status_code for response in responses[:8]] == [202] * 8
    assert responses[8].status_code == 429

"""PostgreSQL coverage for maintenance-window CRUD and scheduled rollouts."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from uuid import UUID, uuid4

import psycopg2
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.core.config import settings
from tests.conftest import MIGRATIONS_DIR, _make_jwt


@pytest_asyncio.fixture
async def maintenance_app(tenant_async_url):
    from fastapi import Depends, FastAPI
    from slowapi.errors import RateLimitExceeded
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.api import agent_rollouts, fleet_targeting, maintenance_windows
    from app.core.tenant import get_tenant_db, get_tenant_org_id
    from app.db import database as db_module
    from app.middleware.rate_limit import (
        limiter,
        rate_limit_exceeded_handler,
    )

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
                    text("SELECT set_config('app.current_org_id', :org_id, false)"),
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

    app = FastAPI()
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)
    app.include_router(fleet_targeting.router, prefix="/api/v1/fleet")
    app.include_router(maintenance_windows.router, prefix="/api/v1/fleet")
    app.include_router(agent_rollouts.router, prefix="/api/v1/fleet")
    app.dependency_overrides[db_module.get_db] = override_get_db
    app.dependency_overrides[get_tenant_db] = override_tenant_db
    try:
        yield app
    finally:
        app.dependency_overrides.clear()
        await engine.dispose()


@pytest_asyncio.fixture
async def maintenance_client_a(maintenance_app, jwt_for_user):
    transport = ASGITransport(app=maintenance_app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"Authorization": f"Bearer {jwt_for_user['a']}"},
    ) as client:
        yield client


@pytest_asyncio.fixture
async def maintenance_client_b(maintenance_app, jwt_for_user):
    transport = ASGITransport(app=maintenance_app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"Authorization": f"Bearer {jwt_for_user['b']}"},
    ) as client:
        yield client


def _insert_user(admin_sync_url: str, organization_id: UUID, role: str) -> UUID:
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


@asynccontextmanager
async def _client_for_user(app, user_id: UUID):
    token = _make_jwt(
        user_id,
        settings.JWT_SECRET_KEY,
        settings.JWT_ALGORITHM,
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"Authorization": f"Bearer {token}"},
    ) as client:
        yield client


def _seed_agent_asset_and_release(
    admin_sync_url: str,
    seeded_orgs: dict,
) -> tuple[UUID, UUID]:
    asset_type_id = uuid4()
    asset_id = uuid4()
    release_id = uuid4()
    conn = psycopg2.connect(admin_sync_url)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO asset_types (id, name, category)
                VALUES (%s, %s, 'video');
                """,
                (
                    str(asset_type_id),
                    f"Scheduled video {asset_type_id.hex[:8]}",
                ),
            )
            cur.execute(
                """
                INSERT INTO assets
                    (id, organization_id, workcell_id, asset_type_id, name,
                     is_active, agent_id, agent_version, agent_last_heartbeat,
                     agent_version_valid, agent_version_major,
                     agent_version_minor, agent_version_patch)
                VALUES
                    (%s, %s, %s, %s, 'Scheduled camera',
                     TRUE, 'agent-scheduled', '1.0.0', NOW(),
                     TRUE, 1, 0, 0);
                """,
                (
                    str(asset_id),
                    str(seeded_orgs["org_a_id"]),
                    str(seeded_orgs["workcell_a_id"]),
                    str(asset_type_id),
                ),
            )
            cur.execute(
                """
                INSERT INTO agent_releases
                    (id, organization_id, version, channel, artifact_type,
                     artifact_format, artifact_filename, artifact_size_bytes,
                     package_name, bundle_storage_key, checksum_sha256,
                     signature_ed25519, signing_key_id, status, created_by)
                VALUES
                    (%s, %s, '2.0.0', 'stable', 'agent', 'wheel',
                     'opsgrid_agent-2.0.0-py3-none-any.whl', 1,
                     'opsgrid-agent', %s, %s, 'signature',
                     'test-key', 'published', %s);
                """,
                (
                    str(release_id),
                    str(seeded_orgs["org_a_id"]),
                    f"tests/{release_id}.whl",
                    "a" * 64,
                    str(seeded_orgs["user_a_id"]),
                ),
            )
    finally:
        conn.close()
    return asset_id, release_id


def test_maintenance_window_schema_is_force_rls(admin_sync_url):
    conn = psycopg2.connect(admin_sync_url)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            migration_sql = (
                MIGRATIONS_DIR / "066_maintenance_windows.sql"
            ).read_text()
            cur.execute(migration_sql)
            cur.execute(migration_sql)
            cur.execute(
                """
                SELECT relrowsecurity, relforcerowsecurity
                FROM pg_class
                WHERE oid = 'maintenance_windows'::regclass;
                """
            )
            assert cur.fetchone() == (True, True)
            cur.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = 'agent_rollouts'
                  AND column_name IN (
                      'scheduled_start_at',
                      'enforce_maintenance_windows',
                      'pause_reason',
                      'next_eligible_at'
                  )
                ORDER BY column_name;
                """
            )
            assert {row[0] for row in cur.fetchall()} == {
                "scheduled_start_at",
                "enforce_maintenance_windows",
                "pause_reason",
                "next_eligible_at",
            }
            cur.execute(
                """
                SELECT 1
                FROM information_schema.columns
                WHERE table_name = 'agent_rollout_targets'
                  AND column_name = 'site_id';
                """
            )
            assert cur.fetchone() == (1,)
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_window_crud_rbac_tenant_scope_and_preview(
    maintenance_app,
    maintenance_client_a,
    maintenance_client_b,
    admin_sync_url,
    seeded_orgs,
):
    site_response = await maintenance_client_a.post(
        "/api/v1/fleet/sites",
        json={"name": "Plant A", "key": "plant-a"},
    )
    assert site_response.status_code == 201
    site_id = site_response.json()["id"]

    invalid_timezone = await maintenance_client_a.post(
        "/api/v1/fleet/maintenance-windows",
        json={
            "name": "Invalid timezone",
            "site_id": site_id,
            "timezone": "Factory/Nowhere",
            "weekdays": [0],
            "local_start_time": "02:00:00",
            "local_end_time": "04:00:00",
        },
    )
    assert invalid_timezone.status_code == 422

    zero_duration = await maintenance_client_a.post(
        "/api/v1/fleet/maintenance-windows",
        json={
            "name": "Zero duration",
            "site_id": site_id,
            "timezone": "UTC",
            "weekdays": [0],
            "local_start_time": "02:00:00",
            "local_end_time": "02:00:00",
        },
    )
    assert zero_duration.status_code == 422

    created = await maintenance_client_a.post(
        "/api/v1/fleet/maintenance-windows",
        json={
            "name": "Plant A night",
            "site_id": site_id,
            "timezone": "America/Chicago",
            "weekdays": [0, 1, 2, 3, 4],
            "local_start_time": "22:00:00",
            "local_end_time": "02:00:00",
        },
    )
    assert created.status_code == 201, created.text
    window = created.json()
    assert window["overnight"] is True
    assert window["weekdays"] == [0, 1, 2, 3, 4]

    duplicate = await maintenance_client_a.post(
        "/api/v1/fleet/maintenance-windows",
        json={
            "name": "Plant A night",
            "timezone": "UTC",
            "weekdays": [0],
            "local_start_time": "01:00:00",
            "local_end_time": "03:00:00",
        },
    )
    assert duplicate.status_code == 409

    assert (
        await maintenance_client_b.get(
            "/api/v1/fleet/maintenance-windows",
            params={"include_disabled": True},
        )
    ).json() == []

    viewer_id = _insert_user(
        admin_sync_url,
        seeded_orgs["org_a_id"],
        "viewer",
    )
    async with _client_for_user(maintenance_app, viewer_id) as viewer:
        assert (
            await viewer.post(
                "/api/v1/fleet/maintenance-windows",
                json={
                    "name": "Viewer denied",
                    "timezone": "UTC",
                    "weekdays": [0],
                    "local_start_time": "01:00:00",
                    "local_end_time": "03:00:00",
                },
            )
        ).status_code == 403
        assert (
            await viewer.post(
                "/api/v1/fleet/maintenance-windows/preview",
                json={"site_ids": [site_id]},
            )
        ).status_code == 403
        assert (
            await viewer.patch(
                f"/api/v1/fleet/maintenance-windows/{window['id']}",
                json={"enabled": False},
            )
        ).status_code == 403
        assert (
            await viewer.delete(
                f"/api/v1/fleet/maintenance-windows/{window['id']}"
            )
        ).status_code == 403
        assert (
            await viewer.get("/api/v1/fleet/maintenance-windows")
        ).status_code == 200

    preview = await maintenance_client_a.post(
        "/api/v1/fleet/maintenance-windows/preview",
        json={
            "site_ids": [site_id],
            "at": "2026-07-25T04:00:00Z",
            "horizon_days": 8,
        },
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["is_open"] is True

    updated = await maintenance_client_a.patch(
        f"/api/v1/fleet/maintenance-windows/{window['id']}",
        json={"weekdays": [6, 5, 5], "enabled": True},
    )
    assert updated.status_code == 200
    assert updated.json()["weekdays"] == [5, 6]

    disabled = await maintenance_client_a.delete(
        f"/api/v1/fleet/maintenance-windows/{window['id']}"
    )
    assert disabled.status_code == 200
    assert disabled.json()["enabled"] is False

    conn = psycopg2.connect(admin_sync_url)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT action
                FROM audit_logs
                WHERE organization_id = %s
                  AND resource_id = %s
                ORDER BY timestamp;
                """,
                (str(seeded_orgs["org_a_id"]), window["id"]),
            )
            assert [row[0] for row in cur.fetchall()] == [
                "maintenance_window_created",
                "maintenance_window_updated",
                "maintenance_window_disabled",
            ]
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_scheduled_rollout_requires_windows_and_snapshots_site(
    monkeypatch,
    maintenance_client_a,
    admin_sync_url,
    seeded_orgs,
):
    from app.api import agent_rollouts

    now = datetime(2026, 7, 24, 1, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(agent_rollouts, "_utcnow", lambda: now)
    asset_id, release_id = _seed_agent_asset_and_release(
        admin_sync_url,
        seeded_orgs,
    )

    site_response = await maintenance_client_a.post(
        "/api/v1/fleet/sites",
        json={"name": "Scheduled Plant", "key": "scheduled-plant"},
    )
    assert site_response.status_code == 201
    site_id = site_response.json()["id"]
    assigned = await maintenance_client_a.patch(
        f"/api/v1/fleet/workcells/{seeded_orgs['workcell_a_id']}/site",
        json={"site_id": site_id},
    )
    assert assigned.status_code == 200

    preview = await maintenance_client_a.post(
        "/api/v1/fleet/target-previews",
        json={"release_id": str(release_id), "selector": {"all": True}},
    )
    assert preview.status_code == 201, preview.text
    preview_body = preview.json()
    assert preview_body["asset_ids"] == [str(asset_id)]

    rollout_payload = {
        "name": "Nightly rollout",
        "release_id": str(release_id),
        "target_selector": {"all": True},
        "preview_id": preview_body["id"],
        "membership_hash": preview_body["membership_hash"],
        "strategy": {"wave_size": 1},
        "scheduled_start_at": "2026-07-24T01:00:00Z",
        "enforce_maintenance_windows": True,
    }
    missing = await maintenance_client_a.post(
        "/api/v1/fleet/rollouts",
        json=rollout_payload,
    )
    assert missing.status_code == 422
    assert "applicable" in missing.json()["detail"]

    window = await maintenance_client_a.post(
        "/api/v1/fleet/maintenance-windows",
        json={
            "name": "Daily 02-04",
            "site_id": site_id,
            "timezone": "UTC",
            "weekdays": [0, 1, 2, 3, 4, 5, 6],
            "local_start_time": "02:00:00",
            "local_end_time": "04:00:00",
        },
    )
    assert window.status_code == 201, window.text

    created = await maintenance_client_a.post(
        "/api/v1/fleet/rollouts",
        json=rollout_payload,
    )
    assert created.status_code == 201, created.text
    rollout = created.json()
    assert rollout["scheduled_start_at"] == "2026-07-24T01:00:00Z"
    assert rollout["enforce_maintenance_windows"] is True
    assert rollout["next_eligible_at"] == "2026-07-24T02:00:00Z"
    assert rollout["targets"][0]["site_id"] == site_id

    paused = await maintenance_client_a.post(
        f"/api/v1/fleet/rollouts/{rollout['id']}/pause"
    )
    assert paused.status_code == 200
    assert paused.json()["pause_reason"] == "manual"

    deferred = await maintenance_client_a.post(
        f"/api/v1/fleet/rollouts/{rollout['id']}/resume"
    )
    assert deferred.status_code == 200
    assert deferred.json()["status"] == "paused"
    assert deferred.json()["pause_reason"] == "maintenance_window"
    assert deferred.json()["next_eligible_at"] == "2026-07-24T02:00:00Z"

    monkeypatch.setattr(
        agent_rollouts,
        "_utcnow",
        lambda: datetime(2026, 7, 24, 2, 0, tzinfo=timezone.utc),
    )
    resumed = await maintenance_client_a.post(
        f"/api/v1/fleet/rollouts/{rollout['id']}/resume"
    )
    assert resumed.status_code == 200
    assert resumed.json()["status"] == "running"
    assert resumed.json()["pause_reason"] is None
    assert resumed.json()["next_eligible_at"] is None

    cancelled = await maintenance_client_a.post(
        f"/api/v1/fleet/rollouts/{rollout['id']}/cancel"
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    assert cancelled.json()["pause_reason"] is None
    assert cancelled.json()["next_eligible_at"] is None

    naive_schedule = dict(rollout_payload)
    naive_schedule["preview_id"] = str(uuid4())
    naive_schedule["scheduled_start_at"] = "2026-07-24T03:00:00"
    naive = await maintenance_client_a.post(
        "/api/v1/fleet/rollouts",
        json=naive_schedule,
    )
    assert naive.status_code == 422


@pytest.mark.asyncio
async def test_worker_restart_resumes_persisted_rollout_on_next_night(
    monkeypatch,
    maintenance_client_a,
    tenant_async_url,
    admin_sync_url,
    seeded_orgs,
):
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.api import agent_rollouts
    from app.services import rollout_orchestrator as orchestrator_module
    from app.services.rollout_orchestrator import RolloutOrchestrator
    from tests.test_rollout_orchestrator_unit import FakeCommandClient

    now_state = {
        "value": datetime(2026, 7, 24, 1, 0, tzinfo=timezone.utc)
    }
    monkeypatch.setattr(
        agent_rollouts,
        "_utcnow",
        lambda: now_state["value"],
    )
    first_asset_id, release_id = _seed_agent_asset_and_release(
        admin_sync_url,
        seeded_orgs,
    )
    second_asset_id = uuid4()
    conn = psycopg2.connect(admin_sync_url)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT asset_type_id FROM assets WHERE id = %s",
                (str(first_asset_id),),
            )
            asset_type_id = cur.fetchone()[0]
            cur.execute(
                """
                INSERT INTO assets
                    (id, organization_id, workcell_id, asset_type_id, name,
                     is_active, agent_id, agent_version, agent_last_heartbeat,
                     agent_version_valid, agent_version_major,
                     agent_version_minor, agent_version_patch)
                VALUES
                    (%s, %s, %s, %s, 'Second scheduled camera',
                     TRUE, 'agent-scheduled-two', '1.0.0', NOW(),
                     TRUE, 1, 0, 0);
                """,
                (
                    str(second_asset_id),
                    str(seeded_orgs["org_a_id"]),
                    str(seeded_orgs["workcell_a_id"]),
                    str(asset_type_id),
                ),
            )
    finally:
        conn.close()

    site = await maintenance_client_a.post(
        "/api/v1/fleet/sites",
        json={"name": "Restart Plant", "key": "restart-plant"},
    )
    assert site.status_code == 201
    site_id = site.json()["id"]
    assert (
        await maintenance_client_a.patch(
            f"/api/v1/fleet/workcells/{seeded_orgs['workcell_a_id']}/site",
            json={"site_id": site_id},
        )
    ).status_code == 200
    assert (
        await maintenance_client_a.post(
            "/api/v1/fleet/maintenance-windows",
            json={
                "name": "Restart 02-04",
                "site_id": site_id,
                "timezone": "UTC",
                "weekdays": [0, 1, 2, 3, 4, 5, 6],
                "local_start_time": "02:00:00",
                "local_end_time": "04:00:00",
            },
        )
    ).status_code == 201
    preview = await maintenance_client_a.post(
        "/api/v1/fleet/target-previews",
        json={"release_id": str(release_id), "selector": {"all": True}},
    )
    assert preview.status_code == 201
    preview_body = preview.json()
    rollout_response = await maintenance_client_a.post(
        "/api/v1/fleet/rollouts",
        json={
            "name": "Restart-safe rollout",
            "release_id": str(release_id),
            "target_selector": {"all": True},
            "preview_id": preview_body["id"],
            "membership_hash": preview_body["membership_hash"],
            "strategy": {"wave_size": 1},
            "scheduled_start_at": "2026-07-24T01:00:00Z",
            "enforce_maintenance_windows": True,
        },
    )
    assert rollout_response.status_code == 201, rollout_response.text
    rollout_id = UUID(rollout_response.json()["id"])

    engine = create_async_engine(tenant_async_url, future=True)
    session_maker = async_sessionmaker(
        engine,
        expire_on_commit=False,
        autoflush=False,
    )
    monkeypatch.setattr(orchestrator_module, "AsyncSessionLocal", session_maker)
    commands = FakeCommandClient()

    async def healthy(_session, _target, _release, _strategy):
        return True

    first_worker = RolloutOrchestrator(
        command_client=commands,
        clock=lambda: now_state["value"],
    )
    monkeypatch.setattr(first_worker, "_target_healthy", healthy)
    await first_worker.dispatch_rollout(
        rollout_id,
        seeded_orgs["org_a_id"],
    )
    assert commands.submissions == []

    now_state["value"] = datetime(
        2026,
        7,
        24,
        2,
        0,
        tzinfo=timezone.utc,
    )
    await first_worker.dispatch_rollout(
        rollout_id,
        seeded_orgs["org_a_id"],
    )
    assert len(commands.submissions) == 1

    commands.statuses["cmd-1"] = {"status": "completed", "result": {}}
    now_state["value"] = datetime(
        2026,
        7,
        24,
        4,
        1,
        tzinfo=timezone.utc,
    )
    await first_worker.dispatch_rollout(
        rollout_id,
        seeded_orgs["org_a_id"],
    )
    closed = await maintenance_client_a.get(
        f"/api/v1/fleet/rollouts/{rollout_id}"
    )
    assert closed.status_code == 200
    assert closed.json()["status"] == "paused"
    assert closed.json()["pause_reason"] == "maintenance_window"
    assert len(commands.submissions) == 1

    now_state["value"] = datetime(
        2026,
        7,
        25,
        2,
        0,
        tzinfo=timezone.utc,
    )
    restarted_worker = RolloutOrchestrator(
        command_client=commands,
        clock=lambda: now_state["value"],
    )
    monkeypatch.setattr(restarted_worker, "_target_healthy", healthy)
    await restarted_worker.dispatch_rollout(
        rollout_id,
        seeded_orgs["org_a_id"],
    )
    resumed = await maintenance_client_a.get(
        f"/api/v1/fleet/rollouts/{rollout_id}"
    )
    assert resumed.status_code == 200
    assert resumed.json()["status"] == "running"
    assert len(commands.submissions) == 2
    assert sorted(
        target["wave_index"] for target in resumed.json()["targets"]
    ) == [0, 1]
    await engine.dispose()

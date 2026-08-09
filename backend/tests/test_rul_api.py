"""RUL API tenant-isolation and notification integration tests."""

from __future__ import annotations

from uuid import uuid4

import psycopg2
import pytest
import pytest_asyncio


@pytest_asyncio.fixture
async def app(tenant_async_url, admin_sync_url):
    """Mount the production RUL router without unrelated application modules."""
    from fastapi import Depends, FastAPI
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.api import rul
    from app.db import database as db_module
    from app.middleware.tenant_isolation import get_tenant_db, get_tenant_org_id

    # The current converged migration chain predates these existing User ORM
    # fields. Keep this compatibility repair inside the ephemeral test DB; T3
    # does not own Hamad's migration sequence.
    conn = psycopg2.connect(admin_sync_url)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                ALTER TABLE users
                    ADD COLUMN IF NOT EXISTS department VARCHAR(100),
                    ADD COLUMN IF NOT EXISTS priorities JSON,
                    ADD COLUMN IF NOT EXISTS user_context JSON,
                    ADD COLUMN IF NOT EXISTS user_goals JSON
                """
            )
    finally:
        conn.close()

    test_engine = create_async_engine(tenant_async_url, future=True)
    session_maker = async_sessionmaker(
        test_engine, expire_on_commit=False, autoflush=False
    )
    original_session_maker = db_module.AsyncSessionLocal
    db_module.AsyncSessionLocal = session_maker

    fastapi_app = FastAPI()
    fastapi_app.include_router(rul.router, prefix="/api/v1/rul")

    async def _get_tenant_db(org_id=Depends(get_tenant_org_id)):
        # DELEGATES to the production implementation, swapping only the session
        # maker — it must not reimplement it. This was a byte-identical copy of
        # get_tenant_db's old body, and it carried the same defect: a single
        # `set_config(..., false)` does not survive an endpoint's mid-request
        # commit, because commit returns the connection to the pool. Every
        # assertion in this file ran against the copy, so the bug was invisible
        # here. See tests/test_tenant_guc_survives_commit_realdb.py.
        from app.core.tenant import tenant_session

        async with tenant_session(org_id, session_maker) as session:
            yield session

    fastapi_app.dependency_overrides[get_tenant_db] = _get_tenant_db
    yield fastapi_app
    fastapi_app.dependency_overrides.clear()
    db_module.AsyncSessionLocal = original_session_maker
    await test_engine.dispose()


def _seed_asset(admin_sync_url: str, organization_id, workcell_id) -> str:
    asset_type_id = str(uuid4())
    asset_id = str(uuid4())
    conn = psycopg2.connect(admin_sync_url)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO asset_types (id, name, category) VALUES (%s, %s, %s)",
                (asset_type_id, f"RUL-{asset_type_id[:8]}", "test"),
            )
            cur.execute(
                """
                INSERT INTO assets (
                    id, organization_id, workcell_id, asset_type_id, name
                ) VALUES (%s, %s, %s, %s, %s)
                """,
                (
                    asset_id,
                    str(organization_id),
                    str(workcell_id),
                    asset_type_id,
                    f"RUL asset {asset_id[:8]}",
                ),
            )
    finally:
        conn.close()
    return asset_id


@pytest.mark.asyncio
async def test_rul_get_and_list_are_tenant_scoped(
    client_a,
    client_b,
    admin_sync_url,
    seeded_orgs,
    monkeypatch,
):
    from app.api import rul as rul_api
    from app.services.health_index import HealthResult

    asset_a = _seed_asset(
        admin_sync_url,
        seeded_orgs["org_a_id"],
        seeded_orgs["workcell_a_id"],
    )
    asset_b = _seed_asset(
        admin_sync_url,
        seeded_orgs["org_b_id"],
        seeded_orgs["workcell_b_id"],
    )

    async def get_asset_health(asset_id, hours=24):
        return HealthResult(
            asset_id=asset_id,
            health_score=82.0,
            drivers=[],
            confidence=1.0,
            computed_at="2026-07-13T08:00:00+00:00",
        )

    monkeypatch.setattr(
        rul_api.rul_service.health_calculator,
        "get_asset_health",
        get_asset_health,
    )

    owner = await client_a.get(
        f"/api/v1/rul/{asset_a}", params={"notify": "false"}
    )
    assert owner.status_code == 200, owner.text
    assert owner.json()["asset_id"] == asset_a
    assert 0.0 <= owner.json()["failure_probability"] <= 1.0
    assert owner.json()["remaining_useful_life_hours"] > 0.0
    assert owner.json()["recommended_maintenance_window"]["start"]

    foreign = await client_b.get(
        f"/api/v1/rul/{asset_a}", params={"notify": "false"}
    )
    assert foreign.status_code == 404

    listing = await client_a.get("/api/v1/rul")
    assert listing.status_code == 200, listing.text
    assert [row["asset_id"] for row in listing.json()] == [asset_a]
    assert asset_b not in {row["asset_id"] for row in listing.json()}


@pytest.mark.asyncio
async def test_rul_endpoint_records_real_notification_delivery(
    client_a,
    admin_sync_url,
    seeded_orgs,
    monkeypatch,
):
    from app.api import rul as rul_api
    from app.core.config import settings
    from app.services.health_index import HealthResult

    asset_id = _seed_asset(
        admin_sync_url,
        seeded_orgs["org_a_id"],
        seeded_orgs["workcell_a_id"],
    )
    subscription_id = str(uuid4())
    conn = psycopg2.connect(admin_sync_url)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO notification_subscriptions (
                    id, organization_id, name, channel, target,
                    min_severity, domain, asset_id, enabled
                ) VALUES (%s, %s, %s, 'email', %s, 'warning',
                          'maintenance', %s, true)
                """,
                (
                    subscription_id,
                    str(seeded_orgs["org_a_id"]),
                    "RUL maintenance",
                    "maintenance@example.test",
                    asset_id,
                ),
            )
    finally:
        conn.close()

    async def get_asset_health(requested_asset_id, hours=24):
        return HealthResult(
            asset_id=requested_asset_id,
            health_score=10.0,
            drivers=[
                {
                    "factor": "alarm_rate",
                    "impact": -30.0,
                    "detail": "6 alarms/hr",
                }
            ],
            confidence=1.0,
            computed_at="2026-07-13T08:00:00+00:00",
        )

    monkeypatch.setattr(
        rul_api.rul_service.health_calculator,
        "get_asset_health",
        get_asset_health,
    )
    monkeypatch.setattr(settings, "SMTP_HOST", "")

    response = await client_a.get(f"/api/v1/rul/{asset_id}")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["risk_level"] == "critical"
    assert body["notification_dispatched"] is True
    assert body["notification_delivery_count"] == 1

    conn = psycopg2.connect(admin_sync_url)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT organization_id, subscription_id, delivered, title
                FROM notification_deliveries
                WHERE subscription_id = %s
                """,
                (subscription_id,),
            )
            delivery = cur.fetchone()
    finally:
        conn.close()

    assert delivery is not None
    assert str(delivery[0]) == str(seeded_orgs["org_a_id"])
    assert str(delivery[1]) == subscription_id
    assert delivery[2] is True
    assert delivery[3] == "Predictive maintenance: critical risk"

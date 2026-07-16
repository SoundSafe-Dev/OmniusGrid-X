"""Digital-twin optimizer API tenant and strategic-queue integration tests."""

from __future__ import annotations

from uuid import uuid4

import psycopg2
import pytest
import pytest_asyncio


@pytest_asyncio.fixture
async def app(tenant_async_url, admin_sync_url):
    """Mount the production optimizer router without unrelated modules."""
    from fastapi import Depends, FastAPI
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.api import twin_optimizer
    from app.db import database as db_module
    from app.middleware.tenant_isolation import get_tenant_db, get_tenant_org_id

    # Existing converged ORM fields are absent from its migration chain. This
    # repair is confined to the ephemeral test database; Task 4 owns no schema.
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
    fastapi_app.include_router(twin_optimizer.router, prefix="/api/v1/twin")

    async def _get_tenant_db(org_id=Depends(get_tenant_org_id)):
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
                (asset_type_id, f"Twin-{asset_type_id[:8]}", "test"),
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
                    f"Twin asset {asset_id[:8]}",
                ),
            )
    finally:
        conn.close()
    return asset_id


def _request(asset_id: str) -> dict:
    return {
        "asset_ids": [asset_id],
        "baseline": {
            "horizon_hours": 168,
            "cycle_time_seconds": 60,
            "mtbf_hours": 12,
            "mttr_hours": 4,
            "performance": 0.8,
            "quality": 0.95,
        },
        "candidates": [
            {
                "action_id": "reduce-cycle-time",
                "name": "Reduce cycle time",
                "description": "Reduce cycle time from 60 to 30 seconds.",
                "target_asset_id": asset_id,
                "recommendation_type": "parameter_tuning",
                "overrides": {"cycle_time_seconds": 30},
            }
        ],
        "runs": 200,
        "seed": 7,
        "emit_recommendations": True,
    }


@pytest.mark.asyncio
async def test_optimize_is_tenant_scoped_and_feeds_real_strategic_queue(
    client_a,
    client_b,
    admin_sync_url,
    seeded_orgs,
    monkeypatch,
):
    from app.api import twin_optimizer as twin_api
    from app.services.oee_calculator import OEEMetrics

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

    async def calculate_oee(asset_id, time_window_hours=1.0):
        return OEEMetrics(oee=72.0 if asset_id == asset_a else 55.0)

    monkeypatch.setattr(
        twin_api.oee_calculator,
        "calculate_oee",
        calculate_oee,
    )
    recommendation_engine = twin_api.twin_optimizer.recommendation_engine
    monkeypatch.setattr(recommendation_engine, "pending_recommendations", [])

    owner = await client_a.post(
        "/api/v1/twin/optimize", json=_request(asset_a)
    )
    assert owner.status_code == 200, owner.text
    body = owner.json()
    assert body["organization_id"] == str(seeded_orgs["org_a_id"])
    assert body["objective"] == "mean_throughput"
    assert body["evaluated_candidates"] == 1
    assert body["fleet_summary"]["asset_count"] == 1
    assert body["fleet_summary"]["bottleneck_asset_id"] == asset_a
    assert len(body["recommendations"]) == 1
    assert body["recommendations"][0]["strategic_engine_emitted"] is True

    assert len(recommendation_engine.pending_recommendations) == 1
    queued = recommendation_engine.pending_recommendations[0]
    assert queued.asset_id == asset_a
    assert queued.expected_impact["organization_id"] == str(
        seeded_orgs["org_a_id"]
    )

    foreign = await client_b.post(
        "/api/v1/twin/optimize", json=_request(asset_a)
    )
    assert foreign.status_code == 404
    assert len(recommendation_engine.pending_recommendations) == 1

    foreign_target = await client_a.post(
        "/api/v1/twin/optimize", json=_request(asset_b)
    )
    assert foreign_target.status_code == 404
    assert len(recommendation_engine.pending_recommendations) == 1

    unsafe_request = _request(asset_a)
    unsafe_request["candidates"][0]["requires_approval"] = False
    unsafe = await client_a.post(
        "/api/v1/twin/optimize", json=unsafe_request
    )
    assert unsafe.status_code == 422
    assert len(recommendation_engine.pending_recommendations) == 1

    conn = psycopg2.connect(admin_sync_url)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE users SET role = 'viewer' WHERE id = %s",
                (str(seeded_orgs["user_a_id"]),),
            )
    finally:
        conn.close()

    forbidden = await client_a.post(
        "/api/v1/twin/optimize", json=_request(asset_a)
    )
    assert forbidden.status_code == 403
    assert len(recommendation_engine.pending_recommendations) == 1

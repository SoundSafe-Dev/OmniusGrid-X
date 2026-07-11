"""Historian query and tenant retention API integration tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import psycopg2
import pytest
import pytest_asyncio


@pytest_asyncio.fixture
async def app(tenant_async_url):
    """Minimal production-router app isolated from unrelated optional modules."""
    from fastapi import Depends, FastAPI
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.api import data_retention, historian
    from app.db import database as db_module
    from app.middleware.tenant_isolation import get_tenant_db, get_tenant_org_id

    test_engine = create_async_engine(tenant_async_url, future=True)
    session_maker = async_sessionmaker(
        test_engine, expire_on_commit=False, autoflush=False
    )
    fastapi_app = FastAPI()
    fastapi_app.include_router(
        historian.router, prefix="/api/v1/historian", tags=["Historian"]
    )
    fastapi_app.include_router(
        data_retention.tenant_router,
        prefix="/api/v1/data-retention",
        tags=["Data Retention"],
    )

    async def _get_db():
        async with session_maker() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    async def _get_tenant_db(
        org_id=Depends(get_tenant_org_id),
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

    fastapi_app.dependency_overrides[db_module.get_db] = _get_db
    fastapi_app.dependency_overrides[get_tenant_db] = _get_tenant_db
    yield fastapi_app
    fastapi_app.dependency_overrides.clear()
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
                (asset_type_id, f"Historian-{asset_type_id[:8]}", "test"),
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
                    f"Historian asset {asset_id[:8]}",
                ),
            )
    finally:
        conn.close()
    return asset_id


def _insert_telemetry(
    admin_sync_url: str,
    asset_id: str,
    recorded_at: datetime,
    value: float,
    metric: str = "temp_nozzle",
) -> None:
    conn = psycopg2.connect(admin_sync_url)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO telemetry (
                    time, asset_id, metric_name, value, unit, metadata
                ) VALUES (%s, %s, %s, %s, 'C', '{}'::jsonb)
                """,
                (recorded_at, asset_id, metric, value),
            )
    finally:
        conn.close()


def _refresh_rollups(
    admin_sync_url: str,
    window_start: datetime,
    window_end: datetime,
) -> None:
    conn = psycopg2.connect(admin_sync_url)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            for view_name in ("telemetry_1min", "telemetry_1hour", "telemetry_1day"):
                cur.execute(
                    f"CALL refresh_continuous_aggregate('{view_name}', %s, %s)",
                    (window_start, window_end),
                )
    finally:
        conn.close()


def _query_params(asset_id: str, start: datetime, end: datetime, **extra):
    return {
        "asset_id": asset_id,
        "metric": "temp_nozzle",
        "start": start.isoformat(),
        "end": end.isoformat(),
        **extra,
    }


@pytest.mark.asyncio
async def test_historian_returns_correct_raw_and_rollup_series(
    client_a, admin_sync_url, seeded_orgs
):
    asset_id = _seed_asset(
        admin_sync_url,
        seeded_orgs["org_a_id"],
        seeded_orgs["workcell_a_id"],
    )
    base = (datetime.now(timezone.utc) - timedelta(hours=2)).replace(
        minute=15, second=5, microsecond=0
    )
    _insert_telemetry(admin_sync_url, asset_id, base, 10.0)
    _insert_telemetry(admin_sync_url, asset_id, base + timedelta(seconds=30), 20.0)

    window_start = base.replace(hour=0, minute=0, second=0) - timedelta(days=1)
    window_end = window_start + timedelta(days=3)
    _refresh_rollups(admin_sync_url, window_start, window_end)

    raw = await client_a.get(
        "/api/v1/historian/query",
        params=_query_params(asset_id, window_start, window_end),
    )
    assert raw.status_code == 200, raw.text
    assert [point["average"] for point in raw.json()["points"]] == [10.0, 20.0]
    assert raw.json()["count"] == 2

    for granularity in ("1m", "1h", "1d"):
        response = await client_a.get(
            "/api/v1/historian/query",
            params=_query_params(
                asset_id,
                window_start,
                window_end,
                granularity=granularity,
            ),
        )
        assert response.status_code == 200, response.text
        points = response.json()["points"]
        assert len(points) == 1
        assert points[0]["average"] == pytest.approx(15.0)
        assert points[0]["minimum"] == pytest.approx(10.0)
        assert points[0]["maximum"] == pytest.approx(20.0)
        assert points[0]["sample_count"] == 2


@pytest.mark.asyncio
async def test_historian_paginates_and_hides_cross_tenant_assets(
    client_a, client_b, admin_sync_url, seeded_orgs
):
    asset_id = _seed_asset(
        admin_sync_url,
        seeded_orgs["org_a_id"],
        seeded_orgs["workcell_a_id"],
    )
    start = datetime.now(timezone.utc) - timedelta(hours=1)
    _insert_telemetry(admin_sync_url, asset_id, start + timedelta(minutes=1), 1.0)
    _insert_telemetry(admin_sync_url, asset_id, start + timedelta(minutes=2), 2.0)
    end = start + timedelta(hours=2)

    first = await client_a.get(
        "/api/v1/historian/query",
        params=_query_params(asset_id, start, end, limit=1),
    )
    assert first.status_code == 200
    assert first.json()["count"] == 1
    assert first.json()["has_more"] is True
    assert first.json()["points"][0]["average"] == 1.0

    second = await client_a.get(
        "/api/v1/historian/query",
        params=_query_params(asset_id, start, end, limit=1, offset=1),
    )
    assert second.status_code == 200
    assert second.json()["points"][0]["average"] == 2.0
    assert second.json()["has_more"] is False

    foreign = await client_b.get(
        "/api/v1/historian/query",
        params=_query_params(asset_id, start, end),
    )
    assert foreign.status_code == 404


@pytest.mark.asyncio
async def test_historian_applies_resolution_specific_retention_windows(
    client_a, admin_sync_url, seeded_orgs
):
    asset_id = _seed_asset(
        admin_sync_url,
        seeded_orgs["org_a_id"],
        seeded_orgs["workcell_a_id"],
    )
    recorded_at = (datetime.now(timezone.utc) - timedelta(days=2)).replace(
        second=5, microsecond=0
    )
    _insert_telemetry(admin_sync_url, asset_id, recorded_at, 42.0)
    window_start = recorded_at - timedelta(hours=1)
    window_end = datetime.now(timezone.utc) + timedelta(hours=1)
    _refresh_rollups(admin_sync_url, window_start, window_end)

    policy = await client_a.post(
        "/api/v1/data-retention/policies",
        json={
            "metric_name": "temp_nozzle",
            "hot_retention_days": 1,
            "warm_retention_days": 3,
            "cold_retention_days": 30,
        },
    )
    assert policy.status_code == 201, policy.text

    raw = await client_a.get(
        "/api/v1/historian/query",
        params=_query_params(asset_id, window_start, window_end),
    )
    minute = await client_a.get(
        "/api/v1/historian/query",
        params=_query_params(
            asset_id, window_start, window_end, granularity="1m"
        ),
    )
    assert raw.status_code == 200
    assert raw.json()["points"] == []
    assert minute.status_code == 200
    assert minute.json()["points"][0]["average"] == 42.0


@pytest.mark.asyncio
async def test_retention_policy_crud_is_tenant_scoped_and_admin_only(
    client_a, client_b, admin_sync_url, seeded_orgs
):
    created = await client_a.post(
        "/api/v1/data-retention/policies",
        json={
            "metric_name": "temp_nozzle",
            "hot_retention_days": 7,
            "warm_retention_days": 30,
            "cold_retention_days": 365,
            "ingestion_priority": 2,
            "ingestion_sample_rate": 1.0,
            "max_ingest_age_seconds": 60,
            "archival_enabled": True,
        },
    )
    assert created.status_code == 201, created.text
    assert created.json()["organization_id"] == str(seeded_orgs["org_a_id"])

    own = await client_a.get("/api/v1/data-retention/policies/temp_nozzle")
    assert own.status_code == 200
    foreign = await client_b.get("/api/v1/data-retention/policies/temp_nozzle")
    assert foreign.status_code == 404

    updated = await client_a.put(
        "/api/v1/data-retention/policies/temp_nozzle",
        json={
            "hot_retention_days": 14,
            "warm_retention_days": 90,
            "cold_retention_days": 730,
            "ingestion_priority": 3,
            "ingestion_sample_rate": 0.5,
            "max_ingest_age_seconds": 120,
            "archival_enabled": False,
        },
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["hot_retention_days"] == 14
    assert updated.json()["ingestion_sample_rate"] == 0.5

    deleted = await client_a.delete(
        "/api/v1/data-retention/policies/temp_nozzle"
    )
    assert deleted.status_code == 204
    assert (
        await client_a.get("/api/v1/data-retention/policies/temp_nozzle")
    ).status_code == 404

    conn = psycopg2.connect(admin_sync_url)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE users SET role = 'operator' WHERE id = %s",
                (str(seeded_orgs["user_a_id"]),),
            )
    finally:
        conn.close()

    forbidden = await client_a.post(
        "/api/v1/data-retention/policies",
        json={"metric_name": "pressure"},
    )
    assert forbidden.status_code == 403


@pytest.mark.asyncio
async def test_retention_enforcement_deletes_only_callers_expired_raw_data(
    client_a, admin_sync_url, seeded_orgs
):
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
    old = datetime.now(timezone.utc) - timedelta(days=2)
    recent = datetime.now(timezone.utc) - timedelta(minutes=5)
    _insert_telemetry(admin_sync_url, asset_a, old, 1.0)
    _insert_telemetry(admin_sync_url, asset_a, recent, 2.0)
    _insert_telemetry(admin_sync_url, asset_b, old, 3.0)

    policy = await client_a.post(
        "/api/v1/data-retention/policies",
        json={
            "metric_name": "temp_nozzle",
            "hot_retention_days": 1,
            "warm_retention_days": 30,
            "cold_retention_days": 365,
        },
    )
    assert policy.status_code == 201, policy.text

    enforced = await client_a.post("/api/v1/data-retention/enforce")
    assert enforced.status_code == 200, enforced.text
    assert enforced.json()["deleted_rows"] == 1

    conn = psycopg2.connect(admin_sync_url)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT asset_id::text, count(*) FROM telemetry "
                "WHERE asset_id IN (%s, %s) GROUP BY asset_id",
                (asset_a, asset_b),
            )
            counts = dict(cur.fetchall())
    finally:
        conn.close()
    assert counts[asset_a] == 1
    assert counts[asset_b] == 1

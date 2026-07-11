"""Agent heartbeat ingestion and fleet-version visibility tests."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import pytest

MIGRATION_PATH = (
    Path(__file__).resolve().parents[2]
    / "database"
    / "migrations"
    / "026_agent_versioning.sql"
)


def _admin_async_url(admin_sync_url: str) -> str:
    parts = urlsplit(admin_sync_url)
    return urlunsplit(("postgresql+asyncpg", parts.netloc, parts.path, "", ""))


def _seed_assets(admin_sync_url, seeded_orgs):
    import psycopg2

    asset_type_id = uuid4()
    asset_a1 = uuid4()
    asset_a2 = uuid4()
    asset_a3 = uuid4()
    asset_b = uuid4()
    conn = psycopg2.connect(admin_sync_url)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO asset_types (id, name, category)
                VALUES (%s, %s, %s);
                """,
                (str(asset_type_id), f"Fleet type {asset_type_id.hex[:8]}", "test"),
            )
            cur.execute(
                """
                INSERT INTO assets
                    (id, organization_id, workcell_id, asset_type_id, name,
                     agent_id, agent_version, agent_config_hash, agent_build_id,
                     agent_last_heartbeat)
                VALUES
                    (%s, %s, %s, %s, 'Org A Asset 1',
                     'agent-a', '1.2.3', 'hash-a', 'build-a', now()),
                    (%s, %s, %s, %s, 'Org A Asset 2',
                     'agent-a', '1.2.3', 'hash-a', 'build-a', now()),
                    (%s, %s, %s, %s, 'Org A Asset 3',
                     NULL, NULL, NULL, NULL, NULL),
                    (%s, %s, %s, %s, 'Org B Asset',
                     'agent-b', '9.9.9', 'hash-b', 'build-b', now());
                """,
                (
                    str(asset_a1),
                    str(seeded_orgs["org_a_id"]),
                    str(seeded_orgs["workcell_a_id"]),
                    str(asset_type_id),
                    str(asset_a2),
                    str(seeded_orgs["org_a_id"]),
                    str(seeded_orgs["workcell_a_id"]),
                    str(asset_type_id),
                    str(asset_a3),
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
    return {
        "asset_a1": asset_a1,
        "asset_a2": asset_a2,
        "asset_a3": asset_a3,
        "asset_b": asset_b,
    }


def test_migration_020_adds_agent_visibility_columns(admin_sync_url):
    import psycopg2

    schema = f"migration_020_{uuid4().hex}"
    conn = psycopg2.connect(admin_sync_url)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(f'CREATE SCHEMA "{schema}";')
            cur.execute(f'SET search_path TO "{schema}";')
            cur.execute(
                """
                CREATE TABLE assets (
                    id UUID PRIMARY KEY,
                    organization_id UUID NOT NULL
                );
                """
            )
            cur.execute(MIGRATION_PATH.read_text())
            cur.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = %s AND table_name = 'assets';
                """,
                (schema,),
            )
            columns = {row[0] for row in cur.fetchall()}
            assert {
                "agent_id",
                "agent_version",
                "agent_config_hash",
                "agent_build_id",
                "agent_last_heartbeat",
            } <= columns
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_agent_heartbeat_updates_only_assets_in_payload_org(
    admin_sync_url,
    seeded_orgs,
):
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.db.models import Asset
    from app.workers.ingestion import IngestionWorker

    assets = _seed_assets(admin_sync_url, seeded_orgs)
    engine = create_async_engine(_admin_async_url(admin_sync_url), future=True)
    session_maker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with session_maker() as session:
            worker = IngestionWorker()
            await worker._process_agent_heartbeat(
                session,
                {
                    "message_type": "agent_heartbeat",
                    "agent_id": "agent-a-new",
                    "organization_id": str(seeded_orgs["org_a_id"]),
                    "asset_ids": [str(assets["asset_a1"]), str(assets["asset_b"])],
                    "agent_version": "2.0.0",
                    "config_hash": "hash-new",
                    "build_id": "build-new",
                    "timestamp": "2030-01-01T00:00:00+00:00",
                },
            )
            await session.commit()

        async with session_maker() as session:
            asset_a = (
                await session.execute(
                    select(Asset).where(Asset.id == assets["asset_a1"])
                )
            ).scalar_one()
            asset_b = (
                await session.execute(
                    select(Asset).where(Asset.id == assets["asset_b"])
                )
            ).scalar_one()
            assert asset_a.agent_id == "agent-a-new"
            assert asset_a.agent_version == "2.0.0"
            assert asset_a.agent_config_hash == "hash-new"
            assert asset_a.agent_build_id == "build-new"
            assert asset_a.agent_last_heartbeat is not None
            assert asset_b.agent_id == "agent-b"
            assert asset_b.agent_version == "9.9.9"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_agent_versions_endpoint_is_tenant_scoped(
    client_a,
    client_b,
    admin_sync_url,
    seeded_orgs,
):
    _seed_assets(admin_sync_url, seeded_orgs)

    response_a = await client_a.get("/api/v1/fleet/agents/versions")
    response_b = await client_b.get("/api/v1/fleet/agents/versions")

    assert response_a.status_code == 200, response_a.text
    assert response_b.status_code == 200, response_b.text

    items_a = {item["agent_version"]: item for item in response_a.json()["items"]}
    assert response_a.json()["total_assets"] == 3
    assert items_a["1.2.3"]["asset_count"] == 2
    assert items_a["1.2.3"]["agent_count"] == 1
    assert items_a["1.2.3"]["config_hash_count"] == 1
    assert items_a["unknown"]["asset_count"] == 1
    assert "9.9.9" not in items_a

    items_b = {item["agent_version"]: item for item in response_b.json()["items"]}
    assert response_b.json()["total_assets"] == 1
    assert items_b["9.9.9"]["asset_count"] == 1
    assert "1.2.3" not in items_b

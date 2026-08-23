"""Integration coverage for tenant-safe fleet targeting and exact previews."""

from __future__ import annotations

from contextlib import asynccontextmanager
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID, uuid4

import psycopg2
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.core.config import settings
from tests.conftest import _make_jwt


@pytest_asyncio.fixture
async def fleet_app(tenant_async_url):
    """Build the fleet slice without importing unrelated application routers."""
    from fastapi import Depends, FastAPI
    from slowapi.errors import RateLimitExceeded
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.api import agent_rollouts, fleet_targeting
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
    app.include_router(agent_rollouts.router, prefix="/api/v1/fleet")
    app.dependency_overrides[db_module.get_db] = override_get_db
    app.dependency_overrides[get_tenant_db] = override_tenant_db
    try:
        yield app
    finally:
        app.dependency_overrides.clear()
        await engine.dispose()


@pytest_asyncio.fixture
async def fleet_client_a(fleet_app, jwt_for_user):
    transport = ASGITransport(app=fleet_app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"Authorization": f"Bearer {jwt_for_user['a']}"},
    ) as client:
        yield client


@pytest_asyncio.fixture
async def fleet_client_b(fleet_app, jwt_for_user):
    transport = ASGITransport(app=fleet_app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"Authorization": f"Bearer {jwt_for_user['b']}"},
    ) as client:
        yield client


def _admin_async_url(admin_sync_url: str) -> str:
    parts = urlsplit(admin_sync_url)
    return urlunsplit(("postgresql+asyncpg", parts.netloc, parts.path, "", ""))


def _insert_user(
    admin_sync_url: str,
    organization_id: UUID,
    *,
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


def _seed_assets(admin_sync_url: str, seeded_orgs: dict) -> dict[str, UUID]:
    asset_type_id = uuid4()
    asset_a1 = uuid4()
    asset_a2 = uuid4()
    asset_b = uuid4()
    conn = psycopg2.connect(admin_sync_url)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO asset_types (id, name, category)
                VALUES (%s, %s, 'video');
                """,
                (str(asset_type_id), f"Video collector {asset_type_id.hex[:8]}"),
            )
            cur.execute(
                """
                INSERT INTO assets
                    (id, organization_id, workcell_id, asset_type_id, name,
                     is_active, agent_id, agent_version, agent_last_heartbeat,
                     agent_version_valid, agent_version_major,
                     agent_version_minor, agent_version_patch)
                VALUES
                    (%s, %s, %s, %s, 'Org A camera one',
                     TRUE, 'agent-shared', '1.5.0', NOW(), TRUE, 1, 5, 0),
                    (%s, %s, %s, %s, 'Org A camera two',
                     TRUE, 'agent-shared', '2.5.0', NOW(), TRUE, 2, 5, 0),
                    (%s, %s, %s, %s, 'Org B camera',
                     TRUE, 'agent-foreign', '1.0.0', NOW(), TRUE, 1, 0, 0);
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
                    str(asset_b),
                    str(seeded_orgs["org_b_id"]),
                    str(seeded_orgs["workcell_b_id"]),
                    str(asset_type_id),
                ),
            )
            cur.execute(
                """
                INSERT INTO asset_agent_collectors
                    (organization_id, asset_id, collector_type, enabled,
                     running, heartbeat_at)
                VALUES
                    (%s, %s, 'video', TRUE, TRUE, NOW()),
                    (%s, %s, 'video', TRUE, TRUE, NOW()),
                    (%s, %s, 'video', TRUE, TRUE, NOW());
                """,
                (
                    str(seeded_orgs["org_a_id"]),
                    str(asset_a1),
                    str(seeded_orgs["org_a_id"]),
                    str(asset_a2),
                    str(seeded_orgs["org_b_id"]),
                    str(asset_b),
                ),
            )
    finally:
        conn.close()
    return {
        "asset_type_id": asset_type_id,
        "asset_a1": asset_a1,
        "asset_a2": asset_a2,
        "asset_b": asset_b,
    }


def _seed_published_agent_release(
    admin_sync_url: str,
    seeded_orgs: dict,
) -> UUID:
    release_id = uuid4()
    conn = psycopg2.connect(admin_sync_url)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO agent_releases
                    (id, organization_id, version, channel, artifact_type,
                     artifact_format, artifact_filename, artifact_size_bytes,
                     package_name, bundle_storage_key, checksum_sha256,
                     signature_ed25519, signing_key_id, status, created_by)
                VALUES
                    (%s, %s, '2.1.0', 'stable', 'agent', 'wheel',
                     'opsgrid_agent-2.1.0-py3-none-any.whl', 1,
                     'opsgrid-agent', %s, %s, 'test-signature',
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
    return release_id


def test_fleet_targeting_schema_has_tenant_constraints_and_forced_rls(
    admin_sync_url,
):
    expected_tables = {
        "sites",
        "asset_agent_collectors",
        "fleet_tags",
        "asset_fleet_tags",
        "fleet_groups",
        "asset_fleet_groups",
        "fleet_cohorts",
        "fleet_target_previews",
    }
    expected_constraints = {
        "fk_workcells_site_org",
        "fk_assets_workcell_org",
        "fk_asset_agent_collectors_asset_org",
        "fk_asset_fleet_tags_asset_org",
        "fk_asset_fleet_tags_tag_org",
        "fk_asset_fleet_groups_asset_org",
        "fk_asset_fleet_groups_group_org",
        "fk_fleet_target_previews_release_org",
        "fk_agent_rollouts_preview_org",
        "fk_agent_rollout_targets_route_asset_org",
        "ck_assets_agent_semver_components",
    }
    conn = psycopg2.connect(admin_sync_url)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT relname, relrowsecurity, relforcerowsecurity
                FROM pg_class
                WHERE relname = ANY(%s);
                """,
                (list(expected_tables),),
            )
            table_security = {
                row[0]: (row[1], row[2])
                for row in cur.fetchall()
            }
            assert set(table_security) == expected_tables
            assert all(flags == (True, True) for flags in table_security.values())

            cur.execute(
                """
                SELECT conname
                FROM pg_constraint
                WHERE conname = ANY(%s);
                """,
                (list(expected_constraints),),
            )
            assert {row[0] for row in cur.fetchall()} == expected_constraints

            cur.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND (
                    (table_name = 'assets'
                     AND column_name LIKE 'agent_version_%')
                    OR
                    (table_name = 'agent_rollout_targets'
                     AND column_name IN ('agent_id', 'route_asset_id'))
                    OR
                    (table_name = 'agent_rollouts'
                     AND column_name IN
                         ('target_preview_id', 'target_membership_hash'))
                  );
                """
            )
            columns = {row[0] for row in cur.fetchall()}
            assert {
                "agent_version_valid",
                "agent_version_major",
                "agent_version_minor",
                "agent_version_patch",
                "agent_version_prerelease",
                "agent_id",
                "route_asset_id",
                "target_preview_id",
                "target_membership_hash",
            } <= columns
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_heartbeat_persists_semver_and_replaces_collector_facts(
    admin_sync_url,
    seeded_orgs,
):
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.db.models import Asset, AssetAgentCollector
    from app.workers.ingestion import IngestionWorker

    assets = _seed_assets(admin_sync_url, seeded_orgs)
    engine = create_async_engine(_admin_async_url(admin_sync_url), future=True)
    session_maker = async_sessionmaker(engine, expire_on_commit=False)
    worker = IngestionWorker()
    try:
        async with session_maker() as session:
            await worker._process_agent_heartbeat(
                session,
                {
                    "message_type": "agent_heartbeat",
                    "organization_id": str(seeded_orgs["org_a_id"]),
                    "agent_id": "heartbeat-agent",
                    "asset_ids": [
                        str(assets["asset_a1"]),
                        str(assets["asset_a2"]),
                    ],
                    "agent_version": "2.1.0-rc.2+build.7",
                    "timestamp": "2030-01-01T00:00:00Z",
                    "collector_status": {
                        "collectors": {
                            str(assets["asset_a1"]): {
                                "type": "mqtt",
                                "enabled": True,
                                "running": True,
                            },
                            str(assets["asset_a2"]): {
                                "type": "opcua",
                                "enabled": True,
                                "running": False,
                            },
                        }
                    },
                },
            )
            await session.commit()

        async with session_maker() as session:
            rows = (
                await session.execute(
                    select(Asset)
                    .where(Asset.id.in_([assets["asset_a1"], assets["asset_a2"]]))
                    .order_by(Asset.id)
                )
            ).scalars().all()
            assert len(rows) == 2
            for asset in rows:
                assert asset.agent_id == "heartbeat-agent"
                assert asset.agent_version == "2.1.0-rc.2+build.7"
                assert asset.agent_version_valid is True
                assert (
                    asset.agent_version_major,
                    asset.agent_version_minor,
                    asset.agent_version_patch,
                    asset.agent_version_prerelease,
                ) == (2, 1, 0, "rc.2")
                assert asset.agent_reported_at is not None

            facts = (
                await session.execute(
                    select(
                        AssetAgentCollector.asset_id,
                        AssetAgentCollector.collector_type,
                        AssetAgentCollector.running,
                    )
                    .where(
                        AssetAgentCollector.organization_id
                        == seeded_orgs["org_a_id"]
                    )
                    .order_by(
                        AssetAgentCollector.asset_id,
                        AssetAgentCollector.collector_type,
                    )
                )
            ).all()
            assert {
                (str(asset_id), collector_type, running)
                for asset_id, collector_type, running in facts
            } == {
                (str(assets["asset_a1"]), "mqtt", True),
                (str(assets["asset_a2"]), "opcua", False),
            }

        async with session_maker() as session:
            await worker._process_agent_heartbeat(
                session,
                {
                    "message_type": "agent_heartbeat",
                    "organization_id": str(seeded_orgs["org_a_id"]),
                    "agent_id": "heartbeat-agent",
                    "asset_ids": [str(assets["asset_a1"])],
                    "agent_version": "legacy-v2",
                    "timestamp": "2030-01-01T00:01:00Z",
                    "collector_status": {
                        "collectors": {
                            str(assets["asset_a1"]): {
                                "type": "video",
                                "enabled": True,
                                "running": True,
                            }
                        }
                    },
                },
            )
            await session.commit()

        async with session_maker() as session:
            current = await session.get(Asset, assets["asset_a1"])
            retired = await session.get(Asset, assets["asset_a2"])
            assert current.agent_version == "legacy-v2"
            assert current.agent_version_valid is False
            assert current.agent_version_major is None
            assert current.agent_version_minor is None
            assert current.agent_version_patch is None
            assert current.agent_version_prerelease is None
            assert retired.agent_id is None
            assert retired.agent_version is None

            remaining_facts = (
                await session.execute(
                    select(
                        AssetAgentCollector.asset_id,
                        AssetAgentCollector.collector_type,
                    ).where(
                        AssetAgentCollector.organization_id
                        == seeded_orgs["org_a_id"]
                    )
                )
            ).all()
            assert remaining_facts == [(str(assets["asset_a1"]), "video")]
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_metadata_crud_assignments_are_tenant_and_role_scoped(
    fleet_app,
    fleet_client_a,
    fleet_client_b,
    admin_sync_url,
    seeded_orgs,
):
    client_a = fleet_client_a
    client_b = fleet_client_b
    assets = _seed_assets(admin_sync_url, seeded_orgs)
    operator_id = _insert_user(
        admin_sync_url,
        seeded_orgs["org_a_id"],
        role="operator",
    )

    site_response = await client_a.post(
        "/api/v1/fleet/sites",
        json={"name": "Plant A", "description": "Primary plant"},
    )
    tag_response = await client_a.post(
        "/api/v1/fleet/tags",
        json={"name": "Video Collectors", "color": "#112233"},
    )
    group_response = await client_a.post(
        "/api/v1/fleet/groups",
        json={"name": "Night Shift"},
    )
    assert site_response.status_code == 201, site_response.text
    assert tag_response.status_code == 201, tag_response.text
    assert group_response.status_code == 201, group_response.text
    site = site_response.json()
    tag = tag_response.json()
    group = group_response.json()
    assert site["key"] == "plant-a"
    assert tag["key"] == "video-collectors"
    assert group["key"] == "night-shift"
    duplicate_site = await client_a.post(
        "/api/v1/fleet/sites",
        json={"name": "Plant A"},
    )
    assert duplicate_site.status_code == 409, duplicate_site.text

    assign_site = await client_a.patch(
        f"/api/v1/fleet/workcells/{seeded_orgs['workcell_a_id']}/site",
        json={"site_id": site["id"]},
    )
    bulk_tag = await client_a.post(
        "/api/v1/fleet/tags/bulk-assignments",
        json={
            "tag_id": tag["id"],
            "asset_ids": [
                str(assets["asset_a1"]),
                str(assets["asset_a2"]),
                str(assets["asset_b"]),
            ],
            "operation": "add",
        },
    )
    add_group = await client_a.put(
        f"/api/v1/fleet/groups/{group['id']}/assets/{assets['asset_a1']}"
    )
    assert assign_site.status_code == 200, assign_site.text
    assert bulk_tag.status_code == 200, bulk_tag.text
    assert bulk_tag.json()["changed_count"] == 2
    assert {
        result["status"]
        for result in bulk_tag.json()["results"]
    } == {"added", "error"}
    assert add_group.status_code == 200, add_group.text
    assert add_group.json()["created"] is True
    repeat_bulk_tag = await client_a.post(
        "/api/v1/fleet/tags/bulk-assignments",
        json={
            "tag_id": tag["id"],
            "asset_ids": [
                str(assets["asset_a1"]),
                str(assets["asset_a2"]),
            ],
            "operation": "add",
        },
    )
    assert repeat_bulk_tag.status_code == 200, repeat_bulk_tag.text
    assert repeat_bulk_tag.json()["changed_count"] == 0
    assert {item["status"] for item in repeat_bulk_tag.json()["results"]} == {
        "unchanged"
    }
    repeat_group = await client_a.put(
        f"/api/v1/fleet/groups/{group['id']}/assets/{assets['asset_a1']}"
    )
    assert repeat_group.status_code == 200, repeat_group.text
    assert repeat_group.json()["created"] is False

    cohort_response = await client_a.post(
        "/api/v1/fleet/cohorts",
        json={
            "name": "Plant A videos",
            "query": {
                "all_of": [
                    {
                        "field": "tag",
                        "operator": "any",
                        "value": [tag["id"]],
                    },
                    {
                        "field": "group",
                        "operator": "any",
                        "value": [group["id"]],
                    },
                    {
                        "field": "site_id",
                        "operator": "eq",
                        "value": site["id"],
                    },
                ]
            },
        },
    )
    assert cohort_response.status_code == 201, cohort_response.text
    cohort = cohort_response.json()

    assert (
        await client_a.patch(
            f"/api/v1/fleet/sites/{site['id']}",
            json={"description": "Updated plant"},
        )
    ).status_code == 200
    assert (
        await client_a.patch(
            f"/api/v1/fleet/tags/{tag['id']}",
            json={"color": "#445566"},
        )
    ).status_code == 200
    assert (
        await client_a.patch(
            f"/api/v1/fleet/groups/{group['id']}",
            json={"description": "Updated group"},
        )
    ).status_code == 200
    assert (
        await client_a.patch(
            f"/api/v1/fleet/cohorts/{cohort['id']}",
            json={"description": "Updated cohort"},
        )
    ).status_code == 200
    for resource, resource_id in (
        ("sites", site["id"]),
        ("tags", tag["id"]),
        ("groups", group["id"]),
        ("cohorts", cohort["id"]),
    ):
        null_update = await client_a.patch(
            f"/api/v1/fleet/{resource}/{resource_id}",
            json={"is_active": None},
        )
        assert null_update.status_code == 422, null_update.text

    assert [row["id"] for row in (await client_a.get("/api/v1/fleet/sites")).json()] == [
        site["id"]
    ]
    assert [row["id"] for row in (await client_a.get("/api/v1/fleet/tags")).json()] == [
        tag["id"]
    ]
    assert [row["id"] for row in (await client_a.get("/api/v1/fleet/groups")).json()] == [
        group["id"]
    ]
    assert [
        row["id"] for row in (await client_a.get("/api/v1/fleet/cohorts")).json()
    ] == [cohort["id"]]

    assert (await client_b.get("/api/v1/fleet/sites")).json() == []
    assert (await client_b.get("/api/v1/fleet/tags")).json() == []
    assert (await client_b.get("/api/v1/fleet/groups")).json() == []
    assert (await client_b.get("/api/v1/fleet/cohorts")).json() == []
    assert (
        await client_b.get(f"/api/v1/fleet/cohorts/{cohort['id']}")
    ).status_code == 404
    assert (
        await client_b.put(
            f"/api/v1/fleet/groups/{group['id']}/assets/{assets['asset_b']}"
        )
    ).status_code == 404

    async with _client_for_user(fleet_app, operator_id) as operator:
        assert (await operator.get("/api/v1/fleet/sites")).status_code == 200
        assert (
            await operator.post(
                "/api/v1/fleet/tags",
                json={"name": "Operator cannot create"},
            )
        ).status_code == 403
        assert (
            await operator.put(
                f"/api/v1/fleet/groups/{group['id']}/assets/{assets['asset_a2']}"
            )
        ).status_code == 403
        assert (
            await operator.post(
                "/api/v1/fleet/cohorts",
                json={
                    "name": "Operator cannot create",
                    "query": {
                        "field": "active",
                        "operator": "eq",
                        "value": True,
                    },
                },
            )
        ).status_code == 403

    assert (
        await client_a.delete(
            f"/api/v1/fleet/groups/{group['id']}/assets/{assets['asset_a1']}"
        )
    ).json()["removed"] is True
    assert (
        await client_a.delete(
            f"/api/v1/fleet/tags/{tag['id']}/assets/{assets['asset_a1']}"
        )
    ).json()["removed"] is True
    assert (
        await client_a.delete(f"/api/v1/fleet/cohorts/{cohort['id']}")
    ).json()["is_active"] is False
    assert (
        await client_a.delete(f"/api/v1/fleet/groups/{group['id']}")
    ).json()["is_active"] is False
    assert (
        await client_a.delete(f"/api/v1/fleet/tags/{tag['id']}")
    ).json()["is_active"] is False
    assert (
        await client_a.delete(f"/api/v1/fleet/sites/{site['id']}")
    ).json()["is_active"] is False


@pytest.mark.asyncio
async def test_membership_queries_preserve_any_all_active_and_tenant_scope(
    fleet_client_a,
    fleet_client_b,
    admin_sync_url,
    seeded_orgs,
):
    client_a = fleet_client_a
    client_b = fleet_client_b
    assets = _seed_assets(admin_sync_url, seeded_orgs)
    release_id = _seed_published_agent_release(admin_sync_url, seeded_orgs)

    async def create_resources(client, resource: str, label: str) -> list[str]:
        resource_ids: list[str] = []
        for suffix in ("One", "Two"):
            response = await client.post(
                f"/api/v1/fleet/{resource}",
                json={"name": f"{label} {suffix}"},
            )
            assert response.status_code == 201, response.text
            resource_ids.append(response.json()["id"])
        return resource_ids

    tag_ids = await create_resources(client_a, "tags", "Membership tag")
    group_ids = await create_resources(client_a, "groups", "Membership group")
    foreign_tag_id = (await create_resources(client_b, "tags", "Foreign tag"))[0]
    foreign_group_id = (await create_resources(client_b, "groups", "Foreign group"))[0]

    for resource, resource_ids in (("tags", tag_ids), ("groups", group_ids)):
        for resource_id, asset_id in (
            (resource_ids[0], assets["asset_a1"]),
            (resource_ids[1], assets["asset_a1"]),
            (resource_ids[1], assets["asset_a2"]),
        ):
            response = await client_a.put(
                f"/api/v1/fleet/{resource}/{resource_id}/assets/{asset_id}"
            )
            assert response.status_code == 200, response.text

    async def preview(field: str, operator: str, resource_ids: list[str]):
        return await client_a.post(
            "/api/v1/fleet/target-previews",
            json={
                "release_id": str(release_id),
                "selector": {
                    "query": {
                        "field": field,
                        "operator": operator,
                        "value": resource_ids,
                    }
                },
            },
        )

    resources = (
        ("tag", "tags", tag_ids, foreign_tag_id),
        ("group", "groups", group_ids, foreign_group_id),
    )
    for field, resource, resource_ids, foreign_resource_id in resources:
        any_response = await preview(field, "any", resource_ids)
        assert any_response.status_code == 201, any_response.text
        assert set(any_response.json()["asset_ids"]) == {
            str(assets["asset_a1"]),
            str(assets["asset_a2"]),
        }

        all_response = await preview(field, "all", resource_ids)
        assert all_response.status_code == 201, all_response.text
        assert all_response.json()["asset_ids"] == [str(assets["asset_a1"])]

        deactivate = await client_a.delete(
            f"/api/v1/fleet/{resource}/{resource_ids[0]}"
        )
        assert deactivate.status_code == 200, deactivate.text
        assert deactivate.json()["is_active"] is False

        unavailable_detail = f"one or more referenced {field} values are unavailable"
        inactive_response = await preview(field, "any", [resource_ids[0]])
        foreign_response = await preview(field, "any", [foreign_resource_id])
        assert inactive_response.status_code == 422, inactive_response.text
        assert foreign_response.status_code == 422, foreign_response.text
        assert inactive_response.json()["detail"] == unavailable_detail
        assert foreign_response.json()["detail"] == unavailable_detail


@pytest.mark.asyncio
async def test_dynamic_cohort_stale_preview_and_exact_multi_asset_rollout(
    fleet_client_a,
    admin_sync_url,
    seeded_orgs,
):
    client_a = fleet_client_a
    assets = _seed_assets(admin_sync_url, seeded_orgs)
    release_id = _seed_published_agent_release(admin_sync_url, seeded_orgs)

    site_response = await client_a.post(
        "/api/v1/fleet/sites",
        json={"name": "Plant A"},
    )
    tag_response = await client_a.post(
        "/api/v1/fleet/tags",
        json={"name": "Production Video"},
    )
    assert site_response.status_code == 201, site_response.text
    assert tag_response.status_code == 201, tag_response.text
    site_id = site_response.json()["id"]
    tag_id = tag_response.json()["id"]
    assert (
        await client_a.patch(
            f"/api/v1/fleet/workcells/{seeded_orgs['workcell_a_id']}/site",
            json={"site_id": site_id},
        )
    ).status_code == 200
    assert (
        await client_a.put(
            f"/api/v1/fleet/tags/{tag_id}/assets/{assets['asset_a1']}"
        )
    ).status_code == 200

    query = {
        "all_of": [
            {"field": "tag", "operator": "any", "value": [tag_id]},
            {"field": "site_id", "operator": "eq", "value": site_id},
            {"field": "collector_type", "operator": "eq", "value": "video"},
            {"field": "agent_version", "operator": "lt", "value": "2.1.0"},
        ]
    }
    cohort_response = await client_a.post(
        "/api/v1/fleet/cohorts",
        json={"name": "Plant A video agents below 2.1", "query": query},
    )
    assert cohort_response.status_code == 201, cohort_response.text
    cohort_id = cohort_response.json()["id"]

    no_preview_rollout = await client_a.post(
        "/api/v1/fleet/rollouts",
        json={
            "name": "Preview is mandatory",
            "release_id": str(release_id),
            "target_selector": {"cohort_id": cohort_id},
        },
    )
    assert no_preview_rollout.status_code == 422
    missing_fields = {
        error["loc"][-1]
        for error in no_preview_rollout.json()["detail"]
        if error.get("type") == "missing"
    }
    assert {"preview_id", "membership_hash"} <= missing_fields

    first_preview_response = await client_a.post(
        "/api/v1/fleet/target-previews",
        json={
            "release_id": str(release_id),
            "selector": {"cohort_id": cohort_id},
        },
    )
    assert first_preview_response.status_code == 201, first_preview_response.text
    first_preview = first_preview_response.json()
    assert first_preview["asset_count"] == 1
    assert first_preview["agent_count"] == 1
    assert first_preview["asset_ids"] == [str(assets["asset_a1"])]

    assert (
        await client_a.put(
            f"/api/v1/fleet/tags/{tag_id}/assets/{assets['asset_a2']}"
        )
    ).status_code == 200
    conn = psycopg2.connect(admin_sync_url)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE assets
                SET agent_version = '2.0.0',
                    agent_version_valid = TRUE,
                    agent_version_major = 2,
                    agent_version_minor = 0,
                    agent_version_patch = 0,
                    agent_version_prerelease = NULL
                WHERE id = %s;
                """,
                (str(assets["asset_a2"]),),
            )
    finally:
        conn.close()

    stale_rollout = await client_a.post(
        "/api/v1/fleet/rollouts",
        json={
            "name": "Stale rollout",
            "release_id": str(release_id),
            "target_selector": {"cohort_id": cohort_id},
            "preview_id": first_preview["id"],
            "membership_hash": first_preview["membership_hash"],
            "strategy": {"wave_size": 1},
        },
    )
    assert stale_rollout.status_code == 409
    assert "Target membership changed" in stale_rollout.json()["detail"]

    second_preview_response = await client_a.post(
        "/api/v1/fleet/target-previews",
        json={
            "release_id": str(release_id),
            "selector": {"cohort_id": cohort_id},
        },
    )
    assert second_preview_response.status_code == 201, second_preview_response.text
    second_preview = second_preview_response.json()
    assert second_preview["asset_count"] == 2
    assert second_preview["agent_count"] == 1
    assert set(second_preview["asset_ids"]) == {
        str(assets["asset_a1"]),
        str(assets["asset_a2"]),
    }
    assert len(second_preview["agents"]) == 1
    agent_snapshot = second_preview["agents"][0]
    assert agent_snapshot["agent_id"] == "agent-shared"
    assert set(agent_snapshot["asset_ids"]) == set(second_preview["asset_ids"])
    assert agent_snapshot["route_asset_id"] in second_preview["asset_ids"]

    rollout_response = await client_a.post(
        "/api/v1/fleet/rollouts",
        json={
            "name": "Exact preview rollout",
            "release_id": str(release_id),
            "target_selector": {"cohort_id": cohort_id},
            "preview_id": second_preview["id"],
            "membership_hash": second_preview["membership_hash"],
            "strategy": {"wave_size": 1},
        },
    )
    assert rollout_response.status_code == 201, rollout_response.text
    rollout = rollout_response.json()
    assert rollout["target_preview_id"] == second_preview["id"]
    assert rollout["target_membership_hash"] == second_preview["membership_hash"]
    assert set(target["asset_id"] for target in rollout["targets"]) == set(
        second_preview["asset_ids"]
    )
    assert {target["agent_id"] for target in rollout["targets"]} == {
        "agent-shared"
    }
    assert {target["route_asset_id"] for target in rollout["targets"]} == {
        agent_snapshot["route_asset_id"]
    }
    assert {target["wave_index"] for target in rollout["targets"]} == {0}

    reused_preview = await client_a.post(
        "/api/v1/fleet/rollouts",
        json={
            "name": "Cannot reuse preview",
            "release_id": str(release_id),
            "target_selector": {"cohort_id": cohort_id},
            "preview_id": second_preview["id"],
            "membership_hash": second_preview["membership_hash"],
        },
    )
    assert reused_preview.status_code == 409
    assert reused_preview.json()["detail"] == "Target preview was already used"

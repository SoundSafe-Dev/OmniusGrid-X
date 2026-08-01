"""Regression coverage for ERP background sync under real PostgreSQL RLS."""
from __future__ import annotations

from uuid import uuid4

import pytest


@pytest.mark.asyncio
async def test_background_sync_writes_as_non_owner_without_leaking_tenant_guc(
    admin_sync_url,
    tenant_async_url,
    seeded_orgs,
    monkeypatch,
):
    """The worker must see/write its tenant even when the DB role owns nothing."""
    import psycopg2
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.api import erp_integrations
    from app.core import tenant as tenant_module

    integration_id = uuid4()
    conn = psycopg2.connect(admin_sync_url)
    conn.autocommit = True
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "INSERT INTO integration_configurations "
                "(id, integration_type, integration_name, organization_id, "
                "configuration, is_active, created_by, erp_type) "
                "VALUES (%s, 'erp', 'background-rls', %s, '{}'::jsonb, true, %s, 'generic')",
                (
                    str(integration_id),
                    str(seeded_orgs["org_a_id"]),
                    str(seeded_orgs["user_a_id"]),
                ),
            )
    finally:
        conn.close()

    class FakeConnector:
        closed = False

        async def fetch_data(self, entity_type):
            assert entity_type == "purchase_orders"
            return [{"id": "PO-RLS-1", "amount": 125}]

        async def close(self):
            self.closed = True

    connector = FakeConnector()
    engine = create_async_engine(
        tenant_async_url,
        future=True,
        pool_size=1,
        max_overflow=0,
    )
    session_maker = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(tenant_module, "AsyncSessionLocal", session_maker)
    monkeypatch.setattr(
        erp_integrations.ERPConnectorFactory,
        "create",
        staticmethod(lambda _integration: connector),
    )

    try:
        # A mid-session commit starts a new transaction. The tenant setting
        # must be reinstalled automatically on that new transaction.
        async with tenant_module.tenant_session(seeded_orgs["org_a_id"]) as session:
            before_commit = (
                await session.execute(
                    text("SELECT current_setting('app.current_org_id', true)")
                )
            ).scalar_one()
            await session.commit()
            after_commit = (
                await session.execute(
                    text("SELECT current_setting('app.current_org_id', true)")
                )
            ).scalar_one()
        assert before_commit == str(seeded_orgs["org_a_id"])
        assert after_commit == str(seeded_orgs["org_a_id"])

        summary = await erp_integrations.run_erp_sync(
            str(integration_id),
            str(seeded_orgs["org_a_id"]),
            ["purchase_orders"],
        )
        assert summary["purchase_orders"]["status"] == "success"
        assert summary["purchase_orders"]["records_synced"] == 1
        assert connector.closed is True

        # A tenant hint cannot be used to reach an integration in another org.
        cross_tenant = await erp_integrations.run_erp_sync(
            str(integration_id),
            str(seeded_orgs["org_b_id"]),
            ["purchase_orders"],
        )
        assert cross_tenant == {"error": "integration not found"}

        # Transaction-local set_config must not survive connection-pool reuse.
        async with session_maker() as unscoped_session:
            leaked = (
                await unscoped_session.execute(
                    text("SELECT current_setting('app.current_org_id', true)")
                )
            ).scalar_one_or_none()
        assert leaked in (None, "")
    finally:
        await engine.dispose()

    conn = psycopg2.connect(admin_sync_url)
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT organization_id::text, entity_id "
                "FROM erp_entities WHERE integration_id = %s",
                (str(integration_id),),
            )
            entities = cursor.fetchall()
            cursor.execute(
                "SELECT organization_id::text, entity_type, records_synced "
                "FROM erp_sync_status WHERE integration_id = %s",
                (str(integration_id),),
            )
            statuses = cursor.fetchall()
    finally:
        conn.close()

    assert entities == [(str(seeded_orgs["org_a_id"]), "PO-RLS-1")]
    assert statuses == [
        (str(seeded_orgs["org_a_id"]), "purchase_orders", 1)
    ]

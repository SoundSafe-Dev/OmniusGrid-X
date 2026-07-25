"""End-to-end compliance report flow with Redpanda and mocked SMTP."""

from __future__ import annotations

import asyncio
import json
import os
import tarfile
import time
from io import BytesIO
from textwrap import dedent
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest


# Uses the SESSION-scoped redpanda fixture from conftest.py. This module used
# to carry its own copy of _RedpandaContainer with a MODULE-scoped fixture,
# which a third module then imported — so one pytest run started multiple
# brokers that interfered with each other.
@pytest.fixture()
def compliance_redpanda(redpanda_bootstrap_server) -> str:
    return redpanda_bootstrap_server


@pytest.mark.asyncio
async def test_enqueue_dispatch_worker_download_and_email(
    app,
    client_a,
    seeded_orgs,
    compliance_redpanda,
    monkeypatch,
    tmp_path,
    bind_worker_db,
):
    from app.core import config as config_module
    from app.services.compliance_report_queue import ComplianceReportDispatcher
    from app.workers import compliance_reports as worker_module

    monkeypatch.setattr(config_module.settings, "REDPANDA_URL", compliance_redpanda)
    monkeypatch.setattr(config_module.settings, "EXPORT_STORAGE_PATH", str(tmp_path))
    monkeypatch.setattr(
        config_module.settings,
        "REDPANDA_COMPLIANCE_REPORTS_TOPIC",
        f"opsgrid.compliance-reports-{uuid4()}",
    )
    monkeypatch.setattr(
        config_module.settings,
        "COMPLIANCE_REPORT_EMAIL_ENABLED",
        True,
    )
    email_mock = AsyncMock()
    monkeypatch.setattr(worker_module, "send_compliance_report_email", email_mock)

    worker_task = asyncio.create_task(worker_module.run(max_messages=1))
    await asyncio.sleep(1)
    created = await client_a.post(
        "/api/v1/compliance/reports",
        json={"framework": "all", "format": "json"},
    )
    assert created.status_code == 202
    job_id = created.json()["job_id"]

    dispatcher = ComplianceReportDispatcher()
    assert await dispatcher._ensure_producer()
    await dispatcher._publish_queued_for_org(seeded_orgs["org_a_id"])
    await asyncio.wait_for(worker_task, timeout=30)
    await dispatcher.stop()

    status = await client_a.get(f"/api/v1/compliance/reports/{job_id}")
    assert status.json()["report_status"] == "completed"

    download = await client_a.get(f"/api/v1/compliance/reports/{job_id}/download")
    assert download.status_code == 200
    payload = json.loads(download.content)
    assert payload["framework"] == "all"
    email_mock.assert_awaited_once()


@pytest.fixture
async def bind_worker_db(tenant_async_url, monkeypatch):
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    engine = create_async_engine(tenant_async_url, future=True)
    session_maker = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr("app.db.database.AsyncSessionLocal", session_maker)
    monkeypatch.setattr("app.services.compliance_report_queue.AsyncSessionLocal", session_maker)
    monkeypatch.setattr("app.workers.compliance_reports.AsyncSessionLocal", session_maker)
    yield session_maker
    await engine.dispose()


@pytest.mark.asyncio
async def test_broker_outage_leaves_job_queued_then_recovers(
    seeded_orgs,
    compliance_redpanda,
    monkeypatch,
    tmp_path,
    bind_worker_db,
):
    from app.core import config as config_module
    from app.services.compliance_report_queue import (
        ComplianceReportDispatcher,
        enqueue_compliance_report_job,
    )
    from sqlalchemy import select, text
    from app.db.database import AsyncSessionLocal
    from app.db.models import ComplianceReportJob

    dispatcher = ComplianceReportDispatcher()
    monkeypatch.setattr(dispatcher, "_ensure_producer", AsyncMock(return_value=False))

    job = await enqueue_compliance_report_job(
        organization_id=seeded_orgs["org_a_id"],
        requested_by=seeded_orgs["user_a_id"],
        framework="all",
        report_format="json",
        recipients=["admin@example.com"],
    )
    await dispatcher.dispatch_queued()

    async with AsyncSessionLocal() as session:
        await session.execute(
            text("SELECT set_config('app.current_org_id', :org, false)"),
            {"org": str(seeded_orgs["org_a_id"])},
        )
        row = (
            await session.execute(
                select(ComplianceReportJob).where(ComplianceReportJob.id == job.id)
            )
        ).scalar_one()
        assert row.report_status == "queued"

    recovery_dispatcher = ComplianceReportDispatcher()
    monkeypatch.setattr(config_module.settings, "REDPANDA_URL", compliance_redpanda)
    monkeypatch.setattr(
        config_module.settings,
        "REDPANDA_COMPLIANCE_REPORTS_TOPIC",
        f"opsgrid.compliance-reports-recovery-{uuid4()}",
    )
    assert await recovery_dispatcher._ensure_producer()
    await recovery_dispatcher._publish_queued_for_org(seeded_orgs["org_a_id"])
    await recovery_dispatcher.stop()

    async with AsyncSessionLocal() as session:
        await session.execute(
            text("SELECT set_config('app.current_org_id', :org, false)"),
            {"org": str(seeded_orgs["org_a_id"])},
        )
        row = (
            await session.execute(
                select(ComplianceReportJob).where(ComplianceReportJob.id == job.id)
            )
        ).scalar_one()
        assert row.report_status == "published"


@pytest.mark.asyncio
async def test_duplicate_delivery_does_not_create_second_report_or_email(
    seeded_orgs,
    compliance_redpanda,
    monkeypatch,
    tmp_path,
    bind_worker_db,
):
    from app.core import config as config_module
    from app.services.compliance_report_queue import (
        ComplianceReportDispatcher,
        MESSAGE_SCHEMA_VERSION,
    )
    from app.services.compliance_report_queue import enqueue_compliance_report_job
    from app.workers import compliance_reports as worker_module
    from sqlalchemy import select, text
    from app.db.database import AsyncSessionLocal
    from app.db.models import ComplianceReportJob

    monkeypatch.setattr(
        "app.services.compliance_report_service.settings.EXPORT_STORAGE_PATH",
        str(tmp_path),
    )
    monkeypatch.setattr(config_module.settings, "REDPANDA_URL", compliance_redpanda)
    monkeypatch.setattr(
        config_module.settings,
        "REDPANDA_COMPLIANCE_REPORTS_TOPIC",
        f"opsgrid.compliance-reports-duplicate-{uuid4()}",
    )
    monkeypatch.setattr(
        config_module.settings,
        "COMPLIANCE_REPORT_EMAIL_ENABLED",
        True,
    )
    email_mock = AsyncMock()
    monkeypatch.setattr(worker_module, "send_compliance_report_email", email_mock)

    job = await enqueue_compliance_report_job(
        organization_id=seeded_orgs["org_a_id"],
        requested_by=seeded_orgs["user_a_id"],
        framework="all",
        report_format="json",
        recipients=["admin@example.com"],
    )
    worker_task = asyncio.create_task(worker_module.run(max_messages=2))
    await asyncio.sleep(1)
    dispatcher = ComplianceReportDispatcher()
    assert await dispatcher._ensure_producer()
    await dispatcher._publish_queued_for_org(seeded_orgs["org_a_id"])
    await dispatcher._producer.send_and_wait(
        config_module.settings.REDPANDA_COMPLIANCE_REPORTS_TOPIC,
        {
            "schema_version": MESSAGE_SCHEMA_VERSION,
            "job_id": str(job.id),
            "organization_id": str(seeded_orgs["org_a_id"]),
        },
        key=str(job.id).encode("utf-8"),
    )
    await asyncio.wait_for(worker_task, timeout=30)
    await dispatcher.stop()

    async with AsyncSessionLocal() as session:
        await session.execute(
            text("SELECT set_config('app.current_org_id', :org, false)"),
            {"org": str(seeded_orgs["org_a_id"])},
        )
        row = (
            await session.execute(
                select(ComplianceReportJob).where(ComplianceReportJob.id == job.id)
            )
        ).scalar_one()
        assert row.generation_attempts == 1
    assert email_mock.await_count == 1

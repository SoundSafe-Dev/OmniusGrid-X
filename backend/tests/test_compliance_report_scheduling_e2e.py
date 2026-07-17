"""End-to-end scheduled compliance report flow."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy import select, text

from tests.test_compliance_reports_e2e import compliance_redpanda


@pytest.fixture
async def bind_scheduling_db(tenant_async_url, monkeypatch):
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    engine = create_async_engine(tenant_async_url, future=True)
    session_maker = async_sessionmaker(engine, expire_on_commit=False)
    for module in (
        "app.db.database",
        "app.services.report_scheduler",
        "app.services.compliance_report_queue",
        "app.workers.compliance_reports",
    ):
        monkeypatch.setattr(f"{module}.AsyncSessionLocal", session_maker)
    yield session_maker
    await engine.dispose()


@pytest.mark.asyncio
async def test_schedule_dispatch_worker_email_and_no_duplicate(
    app,
    client_a,
    seeded_orgs,
    compliance_redpanda,
    monkeypatch,
    tmp_path,
    bind_scheduling_db,
    admin_sync_url,
):
    from app.core import config as config_module
    from app.db.models import ComplianceReportJob, ScheduledComplianceReport
    from app.services.compliance_report_queue import ComplianceReportDispatcher
    from app.services.report_scheduler import ComplianceReportScheduler
    from app.workers import compliance_reports as worker_module

    monkeypatch.setattr(config_module.settings, "REDPANDA_URL", compliance_redpanda)
    monkeypatch.setattr(config_module.settings, "EXPORT_STORAGE_PATH", str(tmp_path))
    monkeypatch.setattr(
        config_module.settings,
        "REDPANDA_COMPLIANCE_REPORTS_TOPIC",
        f"opsgrid.compliance-reports-{uuid4()}",
    )
    monkeypatch.setattr(config_module.settings, "COMPLIANCE_REPORT_EMAIL_ENABLED", True)
    monkeypatch.setattr(config_module.settings, "SMTP_HOST", "smtp.test.local")

    admin_email = f"a-{seeded_orgs['user_a_id'].hex[:8]}@test.local"
    due = (datetime.now(timezone.utc) - timedelta(minutes=1)).replace(microsecond=0)
    future = (datetime.now(timezone.utc) + timedelta(days=7)).replace(microsecond=0)
    create = await client_a.post(
        "/api/v1/compliance/reports/schedules",
        json={
            "name": "Due now",
            "framework": "all",
            "format": "json",
            "frequency": "daily",
            "timezone": "UTC",
            "next_run_at": future.isoformat(),
            "recipients": [admin_email],
            "is_active": True,
        },
    )
    assert create.status_code == 201, create.text
    schedule_id = create.json()["id"]

    import psycopg2

    conn = psycopg2.connect(admin_sync_url)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE scheduled_compliance_reports
                SET next_run_at = %s
                WHERE id = %s;
                """,
                (due, schedule_id),
            )
    finally:
        conn.close()

    scheduler = ComplianceReportScheduler()
    await scheduler.dispatch_due(now=datetime.now(timezone.utc))

    async with bind_scheduling_db() as session:
        await session.execute(
            text("SELECT set_config('app.current_org_id', :org, false)"),
            {"org": str(seeded_orgs["org_a_id"])},
        )
        job = (
            await session.execute(
                select(ComplianceReportJob).where(
                    ComplianceReportJob.schedule_id == schedule_id
                )
            )
        ).scalar_one()
        job_id = job.id

    email_mock = AsyncMock()
    monkeypatch.setattr(worker_module, "send_compliance_report_email", email_mock)
    worker_task = asyncio.create_task(worker_module.run(max_messages=1))
    await asyncio.sleep(1)

    dispatcher = ComplianceReportDispatcher()
    assert await dispatcher._ensure_producer()
    await dispatcher._publish_queued_for_org(seeded_orgs["org_a_id"])
    await asyncio.wait_for(worker_task, timeout=30)
    await dispatcher.stop()

    status = await client_a.get(f"/api/v1/compliance/reports/{job_id}")
    body = status.json()
    assert body["report_status"] == "completed"
    assert body["delivery_status"] == "sent"
    email_mock.assert_awaited_once()
    download_url = email_mock.await_args.args[3]
    assert "/signed-download?token=" in download_url

    async with bind_scheduling_db() as session:
        await session.execute(
            text("SELECT set_config('app.current_org_id', :org, false)"),
            {"org": str(seeded_orgs["org_a_id"])},
        )
        schedule = (
            await session.execute(
                select(ScheduledComplianceReport).where(
                    ScheduledComplianceReport.id == schedule_id
                )
            )
        ).scalar_one()
        jobs = (
            await session.execute(
                select(ComplianceReportJob).where(
                    ComplianceReportJob.schedule_id == schedule_id
                )
            )
        ).scalars().all()

    assert schedule.last_status == "completed"
    assert len(jobs) == 1

    await scheduler.dispatch_due(now=datetime.now(timezone.utc))
    async with bind_scheduling_db() as session:
        await session.execute(
            text("SELECT set_config('app.current_org_id', :org, false)"),
            {"org": str(seeded_orgs["org_a_id"])},
        )
        jobs_after = (
            await session.execute(
                select(ComplianceReportJob).where(
                    ComplianceReportJob.schedule_id == schedule_id
                )
            )
        ).scalars().all()
    assert len(jobs_after) == 1

"""Unit tests for compliance report recurrence and scheduler dispatch."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import select, text

from app.db.models import ComplianceReportJob, ScheduledComplianceReport
from app.services.report_scheduler import (
    ComplianceReportScheduler,
    first_next_run_after,
    next_compliance_run_at,
)


def test_daily_recurrence_returns_aware_utc():
    current = datetime(2028, 3, 15, 9, 30, tzinfo=timezone.utc)
    result = next_compliance_run_at(current, "daily", "UTC")
    assert result == datetime(2028, 3, 16, 9, 30, tzinfo=timezone.utc)
    assert result.tzinfo is not None


def test_weekly_recurrence():
    current = datetime(2028, 3, 15, 9, 30, tzinfo=timezone.utc)
    assert next_compliance_run_at(current, "weekly", "UTC") == datetime(
        2028, 3, 22, 9, 30, tzinfo=timezone.utc
    )


def test_monthly_recurrence_january_31_to_february_end():
    current = datetime(2028, 1, 31, 8, tzinfo=timezone.utc)
    assert next_compliance_run_at(current, "monthly", "UTC") == datetime(
        2028, 2, 29, 8, tzinfo=timezone.utc
    )


def test_quarterly_recurrence():
    current = datetime(2028, 1, 31, 8, tzinfo=timezone.utc)
    assert next_compliance_run_at(current, "quarterly", "UTC") == datetime(
        2028, 4, 30, 8, tzinfo=timezone.utc
    )


def test_annual_recurrence_february_29_clamps_in_non_leap_year():
    current = datetime(2028, 2, 29, 12, tzinfo=timezone.utc)
    assert next_compliance_run_at(current, "annually", "UTC") == datetime(
        2029, 2, 28, 12, tzinfo=timezone.utc
    )


def test_non_utc_timezone_preserves_wall_clock():
    from zoneinfo import ZoneInfo

    zone = ZoneInfo("America/New_York")
    current = datetime(2028, 6, 1, 14, 0, tzinfo=zone)
    result = next_compliance_run_at(current, "daily", "America/New_York")
    assert result.astimezone(zone).hour == 14
    assert result.tzinfo is not None


def test_dst_boundary_spring_forward():
    from zoneinfo import ZoneInfo

    zone = ZoneInfo("America/New_York")
    current = datetime(2028, 3, 12, 1, 30, tzinfo=zone)
    result = next_compliance_run_at(current, "daily", "America/New_York")
    assert result.tzinfo is not None
    assert result.astimezone(zone).date() == datetime(2028, 3, 13).date()


def test_first_next_run_after_coalesces_missed_runs():
    now = datetime(2028, 3, 10, 12, 0, tzinfo=timezone.utc)
    due = datetime(2028, 3, 1, 8, 0, tzinfo=timezone.utc)
    result = first_next_run_after(now, due, "daily", "UTC")
    assert result > now
    assert result == datetime(2028, 3, 11, 8, 0, tzinfo=timezone.utc)


@pytest.fixture
async def scheduler_db(tenant_async_url, monkeypatch):
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    engine = create_async_engine(tenant_async_url, future=True)
    session_maker = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr("app.services.report_scheduler.AsyncSessionLocal", session_maker)
    monkeypatch.setattr("app.workers.compliance_reports.AsyncSessionLocal", session_maker)
    yield session_maker
    await engine.dispose()


async def _insert_schedule(
    admin_sync_url,
    *,
    org_id,
    user_id,
    next_run_at: datetime,
    is_active: bool = True,
    framework: str = "all",
    report_format: str = "json",
    frequency: str = "daily",
):
    import psycopg2

    schedule_id = uuid4()
    conn = psycopg2.connect(admin_sync_url)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT email FROM users WHERE id = %s;",
                (str(user_id),),
            )
            row = cur.fetchone()
            assert row is not None
            admin_email = row[0]
            cur.execute(
                """
                INSERT INTO scheduled_compliance_reports
                (id, organization_id, name, framework, format, frequency, timezone,
                 next_run_at, recipients, is_active, created_by)
                VALUES (%s, %s, %s, %s, %s, %s, 'UTC', %s, %s::jsonb, %s, %s);
                """,
                (
                    str(schedule_id),
                    str(org_id),
                    "Weekly SOC2",
                    framework,
                    report_format,
                    frequency,
                    next_run_at,
                    f'["{admin_email}"]',
                    is_active,
                    str(user_id),
                ),
            )
    finally:
        conn.close()
    return schedule_id, admin_email


@pytest.mark.asyncio
async def test_due_active_schedule_creates_job(
    admin_sync_url, seeded_orgs, scheduler_db
):
    org_id = seeded_orgs["org_a_id"]
    user_id = seeded_orgs["user_a_id"]
    due = datetime.now(timezone.utc) - timedelta(minutes=5)
    schedule_id, _ = await _insert_schedule(
        admin_sync_url,
        org_id=org_id,
        user_id=user_id,
        next_run_at=due,
    )

    scheduler = ComplianceReportScheduler()
    await scheduler.dispatch_due(now=datetime.now(timezone.utc))

    async with scheduler_db() as session:
        await session.execute(
            text("SELECT set_config('app.current_org_id', :org, false)"),
            {"org": str(org_id)},
        )
        jobs = (
            await session.execute(
                select(ComplianceReportJob).where(
                    ComplianceReportJob.schedule_id == schedule_id
                )
            )
        ).scalars().all()
        schedule = (
            await session.execute(
                select(ScheduledComplianceReport).where(
                    ScheduledComplianceReport.id == schedule_id
                )
            )
        ).scalar_one()

    assert len(jobs) == 1
    job = jobs[0]
    assert job.framework == "all"
    assert job.format == "json"
    # UUIDString reads back a canonical dashed str on every dialect (FS-55, so
    # JSON output is uniform), so compare as strings — not str vs uuid.UUID.
    assert str(job.organization_id) == str(org_id)
    assert str(job.requested_by) == str(user_id)
    assert job.scheduled_for == due
    assert job.report_status == "queued"
    assert schedule.last_status == "queued"
    assert schedule.next_run_at > datetime.now(timezone.utc)


@pytest.mark.asyncio
async def test_future_and_inactive_schedules_create_no_jobs(
    admin_sync_url, seeded_orgs, scheduler_db
):
    org_id = seeded_orgs["org_a_id"]
    user_id = seeded_orgs["user_a_id"]
    future_id, _ = await _insert_schedule(
        admin_sync_url,
        org_id=org_id,
        user_id=user_id,
        next_run_at=datetime.now(timezone.utc) + timedelta(days=1),
    )
    inactive_id, _ = await _insert_schedule(
        admin_sync_url,
        org_id=org_id,
        user_id=user_id,
        next_run_at=datetime.now(timezone.utc) - timedelta(minutes=1),
        is_active=False,
    )

    scheduler = ComplianceReportScheduler()
    await scheduler.dispatch_due(now=datetime.now(timezone.utc))

    async with scheduler_db() as session:
        await session.execute(
            text("SELECT set_config('app.current_org_id', :org, false)"),
            {"org": str(org_id)},
        )
        count = (
            await session.execute(
                select(ComplianceReportJob).where(
                    ComplianceReportJob.schedule_id.in_([future_id, inactive_id])
                )
            )
        ).scalars().all()

    assert count == []


@pytest.mark.asyncio
async def test_concurrent_dispatch_produces_one_job(
    admin_sync_url, seeded_orgs, scheduler_db
):
    org_id = seeded_orgs["org_a_id"]
    user_id = seeded_orgs["user_a_id"]
    due = datetime.now(timezone.utc) - timedelta(minutes=1)
    schedule_id, _ = await _insert_schedule(
        admin_sync_url,
        org_id=org_id,
        user_id=user_id,
        next_run_at=due,
    )

    scheduler = ComplianceReportScheduler()
    now = datetime.now(timezone.utc)
    await asyncio.gather(
        scheduler.dispatch_due(now=now),
        scheduler.dispatch_due(now=now),
    )

    async with scheduler_db() as session:
        await session.execute(
            text("SELECT set_config('app.current_org_id', :org, false)"),
            {"org": str(org_id)},
        )
        jobs = (
            await session.execute(
                select(ComplianceReportJob).where(
                    ComplianceReportJob.schedule_id == schedule_id
                )
            )
        ).scalars().all()

    assert len(jobs) == 1


@pytest.mark.asyncio
async def test_locked_schedule_is_skipped_without_blocking(
    admin_sync_url, seeded_orgs, scheduler_db
):
    org_id = seeded_orgs["org_a_id"]
    user_id = seeded_orgs["user_a_id"]
    due = datetime.now(timezone.utc) - timedelta(minutes=1)
    schedule_id, _ = await _insert_schedule(
        admin_sync_url,
        org_id=org_id,
        user_id=user_id,
        next_run_at=due,
    )

    async with scheduler_db() as locking_session:
        await locking_session.execute(
            text("SELECT set_config('app.current_org_id', :org, true)"),
            {"org": str(org_id)},
        )
        await locking_session.execute(
            select(ScheduledComplianceReport)
            .where(ScheduledComplianceReport.id == schedule_id)
            .with_for_update()
        )

        scheduler = ComplianceReportScheduler()
        result = await asyncio.wait_for(
            scheduler._enqueue_due_schedule(
                org_id,
                schedule_id,
                datetime.now(timezone.utc),
            ),
            timeout=2,
        )

    assert result is None


@pytest.mark.asyncio
async def test_scheduler_tenant_context_is_transaction_local(
    tenant_async_url, seeded_orgs, monkeypatch
):
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    engine = create_async_engine(
        tenant_async_url,
        pool_size=1,
        max_overflow=0,
        future=True,
    )
    session_maker = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(
        "app.services.report_scheduler.AsyncSessionLocal",
        session_maker,
    )
    try:
        scheduler = ComplianceReportScheduler()
        await scheduler._dispatch_due_for_org(
            seeded_orgs["org_a_id"],
            datetime.now(timezone.utc),
        )

        async with session_maker() as session:
            current_org = (
                await session.execute(
                    text("SELECT current_setting('app.current_org_id', true)")
                )
            ).scalar_one()
        assert current_org in (None, "")
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_scheduler_start_and_stop_are_idempotent(monkeypatch):
    from app.core import config as config_module

    monkeypatch.setattr(
        config_module.settings,
        "COMPLIANCE_REPORT_SCHEDULER_ENABLED",
        True,
    )
    monkeypatch.setattr(
        config_module.settings,
        "COMPLIANCE_REPORT_SCHEDULER_INTERVAL_SECONDS",
        3600,
    )
    scheduler = ComplianceReportScheduler()

    await scheduler.start()
    await scheduler.start()
    assert scheduler._scheduler.running is True

    await scheduler.stop()
    await scheduler.stop()
    assert scheduler._scheduler.running is False


@pytest.mark.asyncio
async def test_overdue_schedule_creates_one_job_and_advances_beyond_now(
    admin_sync_url, seeded_orgs, scheduler_db
):
    org_id = seeded_orgs["org_a_id"]
    user_id = seeded_orgs["user_a_id"]
    due = datetime.now(timezone.utc) - timedelta(days=10)
    schedule_id, _ = await _insert_schedule(
        admin_sync_url,
        org_id=org_id,
        user_id=user_id,
        next_run_at=due,
        frequency="daily",
    )

    now = datetime.now(timezone.utc)
    scheduler = ComplianceReportScheduler()
    await scheduler.dispatch_due(now=now)

    async with scheduler_db() as session:
        await session.execute(
            text("SELECT set_config('app.current_org_id', :org, false)"),
            {"org": str(org_id)},
        )
        jobs = (
            await session.execute(
                select(ComplianceReportJob).where(
                    ComplianceReportJob.schedule_id == schedule_id
                )
            )
        ).scalars().all()
        schedule = (
            await session.execute(
                select(ScheduledComplianceReport).where(
                    ScheduledComplianceReport.id == schedule_id
                )
            )
        ).scalar_one()

    assert len(jobs) == 1
    assert jobs[0].scheduled_for == due
    assert schedule.next_run_at > now


@pytest.mark.asyncio
async def test_org_b_schedule_unaffected_when_dispatching_org_a(
    admin_sync_url, seeded_orgs, scheduler_db
):
    due = datetime.now(timezone.utc) - timedelta(minutes=1)
    schedule_a, _ = await _insert_schedule(
        admin_sync_url,
        org_id=seeded_orgs["org_a_id"],
        user_id=seeded_orgs["user_a_id"],
        next_run_at=due,
    )
    schedule_b, _ = await _insert_schedule(
        admin_sync_url,
        org_id=seeded_orgs["org_b_id"],
        user_id=seeded_orgs["user_b_id"],
        next_run_at=due,
    )

    scheduler = ComplianceReportScheduler()
    await scheduler.dispatch_due(now=datetime.now(timezone.utc))

    async with scheduler_db() as session:
        await session.execute(
            text("SELECT set_config('app.current_org_id', :org, false)"),
            {"org": str(seeded_orgs["org_a_id"])},
        )
        jobs_a = (
            await session.execute(
                select(ComplianceReportJob).where(
                    ComplianceReportJob.schedule_id == schedule_a
                )
            )
        ).scalars().all()
        await session.execute(
            text("SELECT set_config('app.current_org_id', :org, false)"),
            {"org": str(seeded_orgs["org_b_id"])},
        )
        jobs_b = (
            await session.execute(
                select(ComplianceReportJob).where(
                    ComplianceReportJob.schedule_id == schedule_b
                )
            )
        ).scalars().all()

    assert len(jobs_a) == 1
    assert len(jobs_b) == 1
    # See note above: UUIDString reads are str, the fixture holds uuid.UUID.
    assert str(jobs_a[0].organization_id) == str(seeded_orgs["org_a_id"])
    assert str(jobs_b[0].organization_id) == str(seeded_orgs["org_b_id"])


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("report_status", "delivery_status", "expected"),
    [
        ("failed", "pending", "failed"),
        ("completed", "failed", "delivery_failed"),
        ("completed", "skipped", "skipped"),
        ("completed", "sent", "completed"),
    ],
)
async def test_worker_updates_scheduled_terminal_status(
    admin_sync_url,
    seeded_orgs,
    scheduler_db,
    report_status,
    delivery_status,
    expected,
):
    from app.workers.compliance_reports import (
        _best_effort_finalize_schedule_status,
    )

    org_id = seeded_orgs["org_a_id"]
    user_id = seeded_orgs["user_a_id"]
    schedule_id, _ = await _insert_schedule(
        admin_sync_url,
        org_id=org_id,
        user_id=user_id,
        next_run_at=datetime.now(timezone.utc) + timedelta(days=1),
    )
    job_id = uuid4()

    import psycopg2

    conn = psycopg2.connect(admin_sync_url)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO compliance_report_jobs
                    (id, organization_id, requested_by, schedule_id, scheduled_for,
                     framework, format, recipients, report_status, delivery_status)
                VALUES
                    (%s, %s, %s, %s, now(), 'all', 'json', '[]'::jsonb, %s, %s);
                """,
                (
                    str(job_id),
                    str(org_id),
                    str(user_id),
                    str(schedule_id),
                    report_status,
                    delivery_status,
                ),
            )
    finally:
        conn.close()

    async with scheduler_db() as session:
        await session.execute(
            text("SELECT set_config('app.current_org_id', :org, true)"),
            {"org": str(org_id)},
        )
        job = (
            await session.execute(
                select(ComplianceReportJob).where(ComplianceReportJob.id == job_id)
            )
        ).scalar_one()

    await _best_effort_finalize_schedule_status(job)

    async with scheduler_db() as session:
        await session.execute(
            text("SELECT set_config('app.current_org_id', :org, true)"),
            {"org": str(org_id)},
        )
        last_status = (
            await session.execute(
                select(ScheduledComplianceReport.last_status).where(
                    ScheduledComplianceReport.id == schedule_id
                )
            )
        ).scalar_one()

    assert last_status == expected

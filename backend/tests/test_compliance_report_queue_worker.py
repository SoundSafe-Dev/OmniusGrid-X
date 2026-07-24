"""Queue dispatcher and worker unit tests for compliance reports."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.services.compliance_report_queue import (
    ComplianceReportDispatcher,
    enqueue_compliance_report_job,
)
from app.workers import compliance_reports as worker_module


@pytest.fixture(autouse=True)
def enable_compliance_email(monkeypatch):
    monkeypatch.setattr(
        worker_module.settings,
        "COMPLIANCE_REPORT_EMAIL_ENABLED",
        True,
    )


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
async def test_enqueue_persists_queued_job(seeded_orgs, bind_worker_db):
    job = await enqueue_compliance_report_job(
        organization_id=seeded_orgs["org_a_id"],
        requested_by=seeded_orgs["user_a_id"],
        framework="all",
        report_format="json",
        recipients=["admin@example.com"],
    )
    assert job.report_status == "queued"
    assert job.delivery_status == "pending"
    # UUIDString reads back a dashed str on every dialect (FS-55); the fixture
    # holds a uuid.UUID, so compare as strings.
    assert str(job.organization_id) == str(seeded_orgs["org_a_id"])


@pytest.mark.asyncio
async def test_successful_dispatch(monkeypatch, seeded_orgs, bind_worker_db):
    dispatcher = ComplianceReportDispatcher()
    send = AsyncMock()
    producer = SimpleNamespace(send_and_wait=send)
    monkeypatch.setattr(dispatcher, "_ensure_producer", AsyncMock(return_value=True))
    dispatcher._producer = producer

    job = await enqueue_compliance_report_job(
        organization_id=seeded_orgs["org_a_id"],
        requested_by=seeded_orgs["user_a_id"],
        framework="soc2",
        report_format="pdf",
        recipients=["admin@example.com"],
    )

    await dispatcher._publish_queued_for_org(seeded_orgs["org_a_id"])
    send.assert_awaited_once()
    payload = send.await_args.args[1]
    assert payload["job_id"] == str(job.id)
    assert payload["organization_id"] == str(seeded_orgs["org_a_id"])


@pytest.mark.asyncio
async def test_concurrent_dispatchers_publish_job_once(
    monkeypatch, seeded_orgs, bind_worker_db
):
    first = ComplianceReportDispatcher()
    second = ComplianceReportDispatcher()
    first_send = AsyncMock()
    second_send = AsyncMock()
    first._producer = SimpleNamespace(send_and_wait=first_send)
    second._producer = SimpleNamespace(send_and_wait=second_send)
    monkeypatch.setattr(first, "_ensure_producer", AsyncMock(return_value=True))
    monkeypatch.setattr(second, "_ensure_producer", AsyncMock(return_value=True))

    job = await enqueue_compliance_report_job(
        organization_id=seeded_orgs["org_a_id"],
        requested_by=seeded_orgs["user_a_id"],
        framework="all",
        report_format="json",
        recipients=["admin@example.com"],
    )

    import asyncio

    await asyncio.gather(
        first._publish_queued_for_org(seeded_orgs["org_a_id"]),
        second._publish_queued_for_org(seeded_orgs["org_a_id"]),
    )
    assert first_send.await_count + second_send.await_count == 1


@pytest.mark.asyncio
async def test_redpanda_unavailable_leaves_durable_queued_job(monkeypatch, seeded_orgs, bind_worker_db):
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

    from app.db.database import AsyncSessionLocal
    from app.db.models import ComplianceReportJob
    from sqlalchemy import select, text

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


@pytest.mark.asyncio
async def test_publish_failure_returns_claimed_job_to_queue(
    monkeypatch, seeded_orgs, bind_worker_db
):
    dispatcher = ComplianceReportDispatcher()
    producer = SimpleNamespace(
        send_and_wait=AsyncMock(side_effect=RuntimeError("broker dropped")),
        stop=AsyncMock(),
    )
    dispatcher._producer = producer
    monkeypatch.setattr(dispatcher, "_ensure_producer", AsyncMock(return_value=True))

    job = await enqueue_compliance_report_job(
        organization_id=seeded_orgs["org_a_id"],
        requested_by=seeded_orgs["user_a_id"],
        framework="all",
        report_format="json",
        recipients=["admin@example.com"],
    )
    await dispatcher._publish_queued_for_org(seeded_orgs["org_a_id"])

    from sqlalchemy import select, text
    from app.db.database import AsyncSessionLocal
    from app.db.models import ComplianceReportJob

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
        assert row.publication_attempts == 1
        assert "broker dropped" in row.error_report


@pytest.mark.asyncio
async def test_reconnect_and_later_dispatch(monkeypatch, seeded_orgs, bind_worker_db):
    dispatcher = ComplianceReportDispatcher()
    attempts = {"connected": False}

    async def _ensure():
        if not attempts["connected"]:
            return False
        if dispatcher._producer is None:
            dispatcher._producer = SimpleNamespace(
                send_and_wait=AsyncMock(),
            )
        return True

    monkeypatch.setattr(dispatcher, "_ensure_producer", _ensure)
    job = await enqueue_compliance_report_job(
        organization_id=seeded_orgs["org_a_id"],
        requested_by=seeded_orgs["user_a_id"],
        framework="all",
        report_format="json",
        recipients=["admin@example.com"],
    )
    await dispatcher.dispatch_queued()

    attempts["connected"] = True
    await dispatcher.dispatch_queued()
    payloads = [call.args[1] for call in dispatcher._producer.send_and_wait.await_args_list]
    assert sum(payload["job_id"] == str(job.id) for payload in payloads) == 1


@pytest.mark.asyncio
async def test_stale_publishing_recovery(monkeypatch, seeded_orgs, admin_sync_url, bind_worker_db):
    import psycopg2

    job = await enqueue_compliance_report_job(
        organization_id=seeded_orgs["org_a_id"],
        requested_by=seeded_orgs["user_a_id"],
        framework="all",
        report_format="json",
        recipients=["admin@example.com"],
    )
    conn = psycopg2.connect(admin_sync_url)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE compliance_report_jobs
                SET report_status = 'publishing',
                    updated_at = NOW() - INTERVAL '1 hour'
                WHERE id = %s;
                """,
                (str(job.id),),
            )
    finally:
        conn.close()

    dispatcher = ComplianceReportDispatcher()
    await dispatcher.recover_stale_publications()

    from sqlalchemy import select, text
    from app.db.database import AsyncSessionLocal
    from app.db.models import ComplianceReportJob

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


@pytest.mark.asyncio
async def test_duplicate_kafka_message_skips_regeneration(
    monkeypatch, seeded_orgs, tenant_async_url, tmp_path, bind_worker_db
):
    monkeypatch.setattr(
        "app.services.compliance_report_service.settings.EXPORT_STORAGE_PATH",
        str(tmp_path),
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
    org_id = seeded_orgs["org_a_id"]
    await worker_module.process_job(job.id, org_id)
    await worker_module.process_job(job.id, org_id)
    assert email_mock.await_count == 1


@pytest.mark.asyncio
async def test_email_retry_without_regeneration(monkeypatch, seeded_orgs, tmp_path, bind_worker_db):
    monkeypatch.setattr(
        "app.services.compliance_report_service.settings.EXPORT_STORAGE_PATH",
        str(tmp_path),
    )
    calls = {"count": 0}

    async def flaky_email(*args, **kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            from app.services.email_service import EmailDeliveryError

            raise EmailDeliveryError("smtp down")

    monkeypatch.setattr(worker_module, "send_compliance_report_email", flaky_email)

    job = await enqueue_compliance_report_job(
        organization_id=seeded_orgs["org_a_id"],
        requested_by=seeded_orgs["user_a_id"],
        framework="all",
        report_format="json",
        recipients=["admin@example.com"],
    )
    org_id = seeded_orgs["org_a_id"]

    with pytest.raises(worker_module.RetryableComplianceReportError):
        await worker_module.process_job(job.id, org_id)
    await worker_module.process_job(job.id, org_id)
    assert calls["count"] == 2

    from sqlalchemy import select, text
    from app.db.database import AsyncSessionLocal
    from app.db.models import ComplianceReportJob

    async with AsyncSessionLocal() as session:
        await session.execute(
            text("SELECT set_config('app.current_org_id', :org, false)"),
            {"org": str(org_id)},
        )
        row = (
            await session.execute(
                select(ComplianceReportJob).where(ComplianceReportJob.id == job.id)
            )
        ).scalar_one()
        assert row.report_status == "completed"
        assert row.generation_attempts == 1


@pytest.mark.asyncio
async def test_concurrent_delivery_claim_sends_once(
    monkeypatch, seeded_orgs, tmp_path, bind_worker_db
):
    import asyncio

    monkeypatch.setattr(
        "app.services.compliance_report_service.settings.EXPORT_STORAGE_PATH",
        str(tmp_path),
    )
    started = asyncio.Event()
    release = asyncio.Event()
    calls = {"count": 0}

    async def blocking_email(*args, **kwargs):
        calls["count"] += 1
        started.set()
        await release.wait()

    monkeypatch.setattr(worker_module, "send_compliance_report_email", blocking_email)
    job = await enqueue_compliance_report_job(
        organization_id=seeded_orgs["org_a_id"],
        requested_by=seeded_orgs["user_a_id"],
        framework="all",
        report_format="json",
        recipients=["admin@example.com"],
    )
    org_id = seeded_orgs["org_a_id"]

    monkeypatch.setattr(worker_module.settings, "COMPLIANCE_REPORT_EMAIL_ENABLED", False)
    await worker_module.process_job(job.id, org_id)
    monkeypatch.setattr(worker_module.settings, "COMPLIANCE_REPORT_EMAIL_ENABLED", True)
    completed = await worker_module._load_job(job.id, org_id)
    assert completed is not None

    first = asyncio.create_task(worker_module._deliver_email(completed))
    await started.wait()
    second = asyncio.create_task(worker_module._deliver_email(completed))
    await asyncio.sleep(0)
    release.set()
    await asyncio.gather(first, second)
    assert calls["count"] == 1


@pytest.mark.asyncio
async def test_no_resend_after_email_sent_at(monkeypatch, seeded_orgs, admin_sync_url, tmp_path, bind_worker_db):
    monkeypatch.setattr(
        "app.services.compliance_report_service.settings.EXPORT_STORAGE_PATH",
        str(tmp_path),
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
    await worker_module.process_job(job.id, seeded_orgs["org_a_id"])
    await worker_module.process_job(job.id, seeded_orgs["org_a_id"])
    assert email_mock.await_count == 1


@pytest.mark.asyncio
async def test_email_is_skipped_until_signed_links_are_enabled(
    monkeypatch, seeded_orgs, tmp_path, bind_worker_db
):
    monkeypatch.setattr(
        "app.services.compliance_report_service.settings.EXPORT_STORAGE_PATH",
        str(tmp_path),
    )
    monkeypatch.setattr(
        worker_module.settings,
        "COMPLIANCE_REPORT_EMAIL_ENABLED",
        False,
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
    await worker_module.process_job(job.id, seeded_orgs["org_a_id"])

    from sqlalchemy import select, text
    from app.db.database import AsyncSessionLocal
    from app.db.models import ComplianceReportJob

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
        assert row.report_status == "completed"
        assert row.delivery_status == "skipped"
        assert row.email_attempts == 0
    email_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_stale_running_recovery(monkeypatch, seeded_orgs, admin_sync_url, bind_worker_db):
    import psycopg2

    job = await enqueue_compliance_report_job(
        organization_id=seeded_orgs["org_a_id"],
        requested_by=seeded_orgs["user_a_id"],
        framework="all",
        report_format="json",
        recipients=["admin@example.com"],
    )
    conn = psycopg2.connect(admin_sync_url)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE compliance_report_jobs
                SET report_status = 'running',
                    started_at = NOW() - INTERVAL '2 hours',
                    updated_at = NOW() - INTERVAL '2 hours'
                WHERE id = %s;
                """,
                (str(job.id),),
            )
    finally:
        conn.close()

    await worker_module.recover_stale_jobs()

    from sqlalchemy import select, text
    from app.db.database import AsyncSessionLocal
    from app.db.models import ComplianceReportJob

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
async def test_terminal_failure_persistence(monkeypatch, seeded_orgs, tmp_path, bind_worker_db):
    monkeypatch.setattr(
        "app.services.compliance_report_service.settings.EXPORT_STORAGE_PATH",
        str(tmp_path),
    )

    async def boom(*args, **kwargs):
        raise RuntimeError("generation exploded")

    monkeypatch.setattr(worker_module, "generate_and_store_report", boom)
    monkeypatch.setattr(worker_module, "send_compliance_report_email", AsyncMock())

    job = await enqueue_compliance_report_job(
        organization_id=seeded_orgs["org_a_id"],
        requested_by=seeded_orgs["user_a_id"],
        framework="all",
        report_format="json",
        recipients=["admin@example.com"],
    )

    monkeypatch.setattr(worker_module.asyncio, "sleep", AsyncMock())
    await worker_module.handle_message(
        {
            "schema_version": 1,
            "job_id": str(job.id),
            "organization_id": str(seeded_orgs["org_a_id"]),
        }
    )

    from sqlalchemy import select, text
    from app.db.database import AsyncSessionLocal
    from app.db.models import ComplianceReportJob

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
        assert row.report_status == "failed"
        assert row.generation_attempts == 3
        assert row.error_report


@pytest.mark.asyncio
async def test_checksum_mismatch_regenerates_without_resending_email(
    monkeypatch, seeded_orgs, tmp_path, bind_worker_db
):
    monkeypatch.setattr(
        "app.services.compliance_report_service.settings.EXPORT_STORAGE_PATH",
        str(tmp_path),
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
    org_id = seeded_orgs["org_a_id"]
    await worker_module.process_job(job.id, org_id)

    from sqlalchemy import select, text
    from app.db.database import AsyncSessionLocal
    from app.db.models import ComplianceReportJob

    async with AsyncSessionLocal() as session:
        await session.execute(
            text("SELECT set_config('app.current_org_id', :org, false)"),
            {"org": str(org_id)},
        )
        row = (
            await session.execute(
                select(ComplianceReportJob).where(ComplianceReportJob.id == job.id)
            )
        ).scalar_one()
        path = worker_module.absolute_report_path(
            row.file_path,
            organization_id=org_id,
            job_id=job.id,
        )
        path.write_text("corrupt")

    await worker_module.process_job(job.id, org_id)

    async with AsyncSessionLocal() as session:
        await session.execute(
            text("SELECT set_config('app.current_org_id', :org, false)"),
            {"org": str(org_id)},
        )
        row = (
            await session.execute(
                select(ComplianceReportJob).where(ComplianceReportJob.id == job.id)
            )
        ).scalar_one()
        assert row.generation_attempts == 2
        assert worker_module._stored_file_is_valid(row)
    assert email_mock.await_count == 1


def test_message_validation_rejects_poison_payloads():
    with pytest.raises(ValueError):
        worker_module._validate_message([])
    with pytest.raises(ValueError):
        worker_module._validate_message({"schema_version": 999})
    with pytest.raises(ValueError):
        worker_module._validate_message(
            {
                "schema_version": 1,
                "job_id": "not-a-uuid",
                "organization_id": str(uuid4()),
            }
        )

"""Integration tests for signed compliance report downloads."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.utils import signed_urls as signed_urls_module
from app.utils.signed_urls import (
    PURPOSE_COMPLIANCE_REPORT,
    create_signed_download_token,
)
from app.workers import compliance_reports as worker_module


@pytest.fixture
def signed_settings(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "SIGNED_URL_SECRET_KEY", "signed-secret")
    monkeypatch.setattr(settings, "JWT_SECRET_KEY", "jwt-secret")
    monkeypatch.setattr(settings, "JWT_ALGORITHM", "HS256")
    monkeypatch.setattr(settings, "SIGNED_URL_ALGORITHM", "HS256")
    monkeypatch.setattr(settings, "SIGNED_URL_ISSUER", "test-issuer")
    monkeypatch.setattr(settings, "SIGNED_URL_AUDIENCE", "test-audience")
    monkeypatch.setattr(settings, "SIGNED_URL_ACCEPT_LEGACY_EXPORT_TOKENS", True)
    monkeypatch.setattr(settings, "EXPORT_LINK_EXPIRE_MINUTES", 1440)
    monkeypatch.setattr(settings, "EXPORT_PUBLIC_BASE_URL", "http://example.test")
    signed_urls_module._fallback_warning_emitted = False


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


def _token_for(job_id: UUID, org_id: UUID) -> str:
    return create_signed_download_token(
        PURPOSE_COMPLIANCE_REPORT,
        job_id,
        org_id,
    )


async def _seed_completed_job(
    admin_sync_url,
    seeded_orgs,
    job_id: str,
    tmp_path,
    monkeypatch,
    *,
    file_bytes: bytes = b'{"framework":"all"}',
    sha256: str | None = None,
    size: int | None = None,
    report_status: str = "completed",
    file_path: str | None = None,
):
    import psycopg2

    from app.core.config import settings

    org_id = seeded_orgs["org_a_id"]
    monkeypatch.setattr(settings, "EXPORT_STORAGE_PATH", str(tmp_path))
    relative = file_path or f"compliance/{org_id}/{job_id}.json"
    absolute = tmp_path / relative
    absolute.parent.mkdir(parents=True, exist_ok=True)
    absolute.write_bytes(file_bytes)
    digest = sha256 or hashlib.sha256(file_bytes).hexdigest()
    file_size = size if size is not None else len(file_bytes)

    conn = psycopg2.connect(admin_sync_url)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO compliance_report_jobs
                (id, organization_id, requested_by, framework, format,
                 report_status, delivery_status, file_path, filename,
                 media_type, file_size, file_sha256, completed_at)
                VALUES
                (%s, %s, %s, 'all', 'json', %s, 'pending', %s, %s,
                 'application/json', %s, %s, NOW());
                """,
                (
                    job_id,
                    str(org_id),
                    str(seeded_orgs["user_a_id"]),
                    report_status,
                    relative,
                    f"{job_id}.json",
                    file_size,
                    digest,
                ),
            )
    finally:
        conn.close()
    return org_id


@pytest.mark.asyncio
async def test_valid_signed_link_works_without_bearer(
    app, seeded_orgs, admin_sync_url, tmp_path, monkeypatch, signed_settings
):
    job_id = str(uuid4())
    org_id = await _seed_completed_job(
        admin_sync_url, seeded_orgs, job_id, tmp_path, monkeypatch
    )
    token = _token_for(UUID(job_id), org_id)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            f"/api/v1/compliance/reports/{job_id}/signed-download",
            params={"token": token},
        )
    assert response.status_code == 200
    assert json.loads(response.content)["framework"] == "all"
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["pragma"] == "no-cache"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["x-content-type-options"] == "nosniff"


@pytest.mark.asyncio
async def test_bearer_token_alone_does_not_replace_signed_token(
    app, client_a, seeded_orgs, admin_sync_url
):
    import psycopg2

    created = await client_a.post(
        "/api/v1/compliance/reports",
        json={"framework": "all", "format": "json"},
    )
    job_id = created.json()["job_id"]
    response = await client_a.get(
        f"/api/v1/compliance/reports/{job_id}/signed-download",
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "Invalid or expired download link"

    conn = psycopg2.connect(admin_sync_url)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT details->>'reason'
                FROM audit_logs
                WHERE resource_type = 'compliance_report'
                  AND resource_id = %s
                ORDER BY timestamp DESC
                LIMIT 1;
                """,
                (job_id,),
            )
            assert cur.fetchone()[0] == "missing_token"
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_invalid_tokens_return_uniform_403(
    app, seeded_orgs, admin_sync_url, tmp_path, monkeypatch, signed_settings
):
    job_id = str(uuid4())
    org_id = await _seed_completed_job(
        admin_sync_url, seeded_orgs, job_id, tmp_path, monkeypatch
    )
    token = _token_for(UUID(job_id), org_id)
    expired = create_signed_download_token(
        PURPOSE_COMPLIANCE_REPORT,
        UUID(job_id),
        org_id,
        expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
    )
    from app.utils.signed_urls import PURPOSE_EXPORT

    wrong_purpose = create_signed_download_token(
        PURPOSE_EXPORT,
        UUID(job_id),
        org_id,
    )
    wrong_job = _token_for(uuid4(), org_id)
    tampered = token[:-1] + ("a" if token[-1] != "a" else "b")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        for bad in (
            tampered,
            "not-a-token",
            expired,
            wrong_purpose,
            wrong_job,
        ):
            response = await client.get(
                f"/api/v1/compliance/reports/{job_id}/signed-download",
                params={"token": bad},
            )
            assert response.status_code == 403
            assert response.json()["detail"] == "Invalid or expired download link"


@pytest.mark.asyncio
async def test_cross_tenant_token_returns_404(
    app, seeded_orgs, admin_sync_url, tmp_path, monkeypatch, signed_settings
):
    job_id = str(uuid4())
    await _seed_completed_job(admin_sync_url, seeded_orgs, job_id, tmp_path, monkeypatch)
    other_org = seeded_orgs["org_b_id"]
    token = _token_for(UUID(job_id), other_org)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            f"/api/v1/compliance/reports/{job_id}/signed-download",
            params={"token": token},
        )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_unfinished_report_returns_409(
    app, seeded_orgs, admin_sync_url, tmp_path, monkeypatch, signed_settings
):
    job_id = str(uuid4())
    org_id = await _seed_completed_job(
        admin_sync_url,
        seeded_orgs,
        job_id,
        tmp_path,
        monkeypatch,
        report_status="queued",
    )
    token = _token_for(UUID(job_id), org_id)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            f"/api/v1/compliance/reports/{job_id}/signed-download",
            params={"token": token},
        )
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_missing_file_returns_410(
    app, seeded_orgs, admin_sync_url, tmp_path, monkeypatch, signed_settings
):
    job_id = str(uuid4())
    org_id = seeded_orgs["org_a_id"]
    relative = f"compliance/{org_id}/{job_id}.json"
    import psycopg2

    conn = psycopg2.connect(admin_sync_url)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO compliance_report_jobs
                (id, organization_id, requested_by, framework, format,
                 report_status, file_path, filename, media_type, completed_at)
                VALUES (%s, %s, %s, 'all', 'json', 'completed', %s, %s,
                        'application/json', NOW());
                """,
                (
                    job_id,
                    str(org_id),
                    str(seeded_orgs["user_a_id"]),
                    relative,
                    f"{job_id}.json",
                ),
            )
    finally:
        conn.close()

    token = _token_for(UUID(job_id), org_id)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            f"/api/v1/compliance/reports/{job_id}/signed-download",
            params={"token": token},
        )
    assert response.status_code == 410


@pytest.mark.asyncio
async def test_integrity_mismatch_returns_410(
    app, seeded_orgs, admin_sync_url, tmp_path, monkeypatch, signed_settings
):
    job_id = str(uuid4())
    org_id = await _seed_completed_job(
        admin_sync_url,
        seeded_orgs,
        job_id,
        tmp_path,
        monkeypatch,
        sha256="0" * 64,
    )
    token = _token_for(UUID(job_id), org_id)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            f"/api/v1/compliance/reports/{job_id}/signed-download",
            params={"token": token},
        )
    assert response.status_code == 410


@pytest.mark.asyncio
async def test_size_mismatch_returns_410(
    app, seeded_orgs, admin_sync_url, tmp_path, monkeypatch, signed_settings
):
    job_id = str(uuid4())
    org_id = await _seed_completed_job(
        admin_sync_url,
        seeded_orgs,
        job_id,
        tmp_path,
        monkeypatch,
        size=999,
    )
    token = _token_for(UUID(job_id), org_id)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            f"/api/v1/compliance/reports/{job_id}/signed-download",
            params={"token": token},
        )
    assert response.status_code == 410


@pytest.mark.asyncio
async def test_unsafe_path_returns_410(
    app, seeded_orgs, admin_sync_url, tmp_path, monkeypatch, signed_settings
):
    outside = tmp_path.parent / f"{uuid4()}.json"
    job_id = str(uuid4())
    org_id = await _seed_completed_job(
        admin_sync_url,
        seeded_orgs,
        job_id,
        tmp_path,
        monkeypatch,
        file_path=str(outside),
    )
    token = _token_for(UUID(job_id), org_id)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            f"/api/v1/compliance/reports/{job_id}/signed-download",
            params={"token": token},
        )
    assert response.status_code == 410


@pytest.mark.asyncio
async def test_public_download_tenant_context_is_transaction_local(
    app, seeded_orgs, admin_sync_url, tmp_path, monkeypatch, signed_settings
):
    from sqlalchemy import text
    import app.api.compliance_reports as compliance_reports_api

    job_id = str(uuid4())
    org_id = await _seed_completed_job(
        admin_sync_url, seeded_orgs, job_id, tmp_path, monkeypatch
    )
    token = _token_for(UUID(job_id), org_id)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            f"/api/v1/compliance/reports/{job_id}/signed-download",
            params={"token": token},
        )
    assert response.status_code == 200
    async with compliance_reports_api.AsyncSessionLocal() as session:
        current_org = (
            await session.execute(
                text("SELECT current_setting('app.current_org_id', true)")
            )
        ).scalar_one()
    assert current_org in (None, "")


@pytest.mark.asyncio
async def test_success_and_rejection_are_audited(
    app, seeded_orgs, admin_sync_url, tmp_path, monkeypatch, signed_settings
):
    import psycopg2

    job_id = str(uuid4())
    org_id = await _seed_completed_job(
        admin_sync_url, seeded_orgs, job_id, tmp_path, monkeypatch
    )
    token = _token_for(UUID(job_id), org_id)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        ok = await client.get(
            f"/api/v1/compliance/reports/{job_id}/signed-download",
            params={"token": token},
        )
        bad = await client.get(
            f"/api/v1/compliance/reports/{job_id}/signed-download",
            params={"token": "invalid"},
        )
    assert ok.status_code == 200
    assert bad.status_code == 403

    conn = psycopg2.connect(admin_sync_url)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT action, details::text, hash_chain
                FROM audit_logs
                WHERE resource_type = 'compliance_report'
                  AND resource_id = %s
                ORDER BY timestamp;
                """,
                (job_id,),
            )
            rows = cur.fetchall()
    finally:
        conn.close()

    actions = {row[0] for row in rows}
    assert "compliance_report_download_succeeded" in actions
    assert "compliance_report_download_rejected" in actions
    combined = " ".join(details for _, details, _ in rows)
    assert token not in combined
    assert all(len(hash_chain) == 64 for _, _, hash_chain in rows)


@pytest.mark.asyncio
async def test_worker_email_url_uses_signed_download_and_matching_expiry(
    monkeypatch, signed_settings, tmp_path, bind_worker_db, seeded_orgs
):
    from app.core.config import settings

    monkeypatch.setattr(settings, "EXPORT_STORAGE_PATH", str(tmp_path))
    monkeypatch.setattr(settings, "COMPLIANCE_REPORT_EMAIL_ENABLED", True)
    captured: dict = {}

    async def capture_email(recipients, framework, generated_at, download_url, expires_at, **kwargs):
        captured["download_url"] = download_url
        captured["expires_at"] = expires_at

    monkeypatch.setattr(worker_module, "send_compliance_report_email", capture_email)

    from app.services.compliance_report_queue import enqueue_compliance_report_job

    job = await enqueue_compliance_report_job(
        organization_id=seeded_orgs["org_a_id"],
        requested_by=seeded_orgs["user_a_id"],
        framework="all",
        report_format="json",
        recipients=["admin@example.com"],
    )
    await worker_module.process_job(job.id, seeded_orgs["org_a_id"])

    assert "/signed-download" in captured["download_url"]
    query = parse_qs(urlparse(captured["download_url"]).query)
    token = query["token"][0]
    verified = signed_urls_module.verify_signed_download_token(
        token,
        PURPOSE_COMPLIANCE_REPORT,
        job.id,
    )
    assert verified.expires_at.replace(microsecond=0) == captured["expires_at"].replace(
        microsecond=0
    )


@pytest.mark.asyncio
async def test_worker_link_lifetime_starts_when_email_is_sent(
    monkeypatch, signed_settings, tmp_path, bind_worker_db, seeded_orgs
):
    from app.core.config import settings
    from app.services.compliance_report_queue import enqueue_compliance_report_job
    from sqlalchemy import select, text
    from app.db.models import ComplianceReportJob

    monkeypatch.setattr(settings, "EXPORT_STORAGE_PATH", str(tmp_path))
    monkeypatch.setattr(settings, "COMPLIANCE_REPORT_EMAIL_ENABLED", True)
    captured: dict = {}

    async def capture_email(recipients, framework, generated_at, download_url, expires_at, **kwargs):
        captured["generated_at"] = generated_at
        captured["expires_at"] = expires_at

    monkeypatch.setattr(worker_module, "send_compliance_report_email", capture_email)
    job = await enqueue_compliance_report_job(
        organization_id=seeded_orgs["org_a_id"],
        requested_by=seeded_orgs["user_a_id"],
        framework="all",
        report_format="json",
        recipients=["admin@example.com"],
    )
    await worker_module.process_job(job.id, seeded_orgs["org_a_id"])

    async with bind_worker_db() as session:
        await session.execute(
            text("SELECT set_config('app.current_org_id', :org, true)"),
            {"org": str(seeded_orgs["org_a_id"])},
        )
        row = (
            await session.execute(
                select(ComplianceReportJob).where(ComplianceReportJob.id == job.id)
            )
        ).scalar_one()
        row.completed_at = datetime.now(timezone.utc) - timedelta(days=2)
        row.delivery_status = "pending"
        row.email_sent_at = None
        await session.commit()

    stale_job = await worker_module._load_job(job.id, seeded_orgs["org_a_id"])
    await worker_module._deliver_email(stale_job)
    remaining = captured["expires_at"] - datetime.now(timezone.utc)
    assert remaining > timedelta(minutes=settings.EXPORT_LINK_EXPIRE_MINUTES - 1)


@pytest.fixture(scope="session")
def rate_limit_redis_url():
    from testcontainers.redis import RedisContainer

    with RedisContainer("redis:7-alpine") as container:
        yield (
            f"redis://{container.get_container_host_ip()}:"
            f"{container.get_exposed_port(6379)}/0"
        )


@pytest.mark.asyncio
async def test_public_download_rate_limit_is_enforced_and_audited(
    app,
    seeded_orgs,
    admin_sync_url,
    tmp_path,
    monkeypatch,
    signed_settings,
    rate_limit_redis_url,
):
    import psycopg2
    from limits.storage import storage_from_string
    from limits.strategies import FixedWindowRateLimiter

    from app.middleware.rate_limit import limiter

    job_id = str(uuid4())
    org_id = await _seed_completed_job(
        admin_sync_url, seeded_orgs, job_id, tmp_path, monkeypatch
    )
    token = _token_for(UUID(job_id), org_id)

    old_enabled = limiter.enabled
    old_storage = limiter._storage
    old_limiter = limiter._limiter
    storage = storage_from_string(rate_limit_redis_url)
    limiter._storage = storage
    limiter._limiter = FixedWindowRateLimiter(storage)
    limiter.enabled = True
    limiter.reset()
    try:
        transport = ASGITransport(app=app, client=("198.51.100.10", 1234))
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            responses = [
                await client.get(
                    f"/api/v1/compliance/reports/{job_id}/signed-download",
                    params={"token": token},
                )
                for _ in range(11)
            ]
    finally:
        limiter.enabled = old_enabled
        limiter._storage = old_storage
        limiter._limiter = old_limiter

    assert [response.status_code for response in responses[:10]] == [200] * 10
    assert responses[10].status_code == 429

    conn = psycopg2.connect(admin_sync_url)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT COUNT(*)
                FROM audit_logs
                WHERE resource_type = 'compliance_report'
                  AND resource_id = %s
                  AND action = 'compliance_report_download_rejected'
                  AND details->>'reason' = 'rate_limited';
                """,
                (job_id,),
            )
            assert cur.fetchone()[0] == 1
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_export_public_download_uses_shared_security_controls(
    app, seeded_orgs, admin_sync_url, tmp_path, monkeypatch, signed_settings
):
    import psycopg2

    from app.core.config import settings
    from app.utils.signed_urls import PURPOSE_EXPORT

    monkeypatch.setattr(settings, "EXPORT_STORAGE_PATH", str(tmp_path))
    template_id = uuid4()
    schedule_id = uuid4()
    job_id = uuid4()
    org_id = seeded_orgs["org_a_id"]
    path = tmp_path / f"{job_id}.csv"
    path.write_bytes(b"metric,value\nspeed,10\n")

    conn = psycopg2.connect(admin_sync_url)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO export_templates
                    (id, organization_id, name, export_type, export_format,
                     columns, filters, created_by)
                VALUES (%s, %s, %s, 'telemetry', 'csv', '[]', '{}', %s);
                """,
                (
                    str(template_id),
                    str(org_id),
                    f"template-{template_id}",
                    str(seeded_orgs["user_a_id"]),
                ),
            )
            cur.execute(
                """
                INSERT INTO scheduled_exports
                    (id, organization_id, template_id, name, frequency, timezone,
                     next_run_at, recipients, is_active, created_by)
                VALUES (%s, %s, %s, %s, 'daily', 'UTC', NOW(), '[]', FALSE, %s);
                """,
                (
                    str(schedule_id),
                    str(org_id),
                    str(template_id),
                    f"schedule-{schedule_id}",
                    str(seeded_orgs["user_a_id"]),
                ),
            )
            cur.execute(
                """
                INSERT INTO export_delivery_jobs
                    (id, organization_id, schedule_id, template_id, requested_by,
                     scheduled_for, status, attempts, file_path, filename, completed_at)
                VALUES (%s, %s, %s, %s, %s, NOW(), 'completed', 0, %s, %s, NOW());
                """,
                (
                    str(job_id),
                    str(org_id),
                    str(schedule_id),
                    str(template_id),
                    str(seeded_orgs["user_a_id"]),
                    str(path),
                    f"{job_id}.csv",
                ),
            )
    finally:
        conn.close()

    signature = create_signed_download_token(PURPOSE_EXPORT, job_id, org_id)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            f"/api/v1/exports/deliveries/{job_id}/download",
            params={"signature": signature},
        )
        missing = await client.get(
            f"/api/v1/exports/deliveries/{job_id}/download",
        )

    assert response.status_code == 200
    assert response.content == path.read_bytes()
    assert response.headers["cache-control"] == "private, no-store"
    assert missing.status_code == 403

    conn = psycopg2.connect(admin_sync_url)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT action, details->>'reason'
                FROM audit_logs
                WHERE resource_type = 'export_delivery'
                  AND resource_id = %s
                ORDER BY timestamp;
                """,
                (str(job_id),),
            )
            rows = cur.fetchall()
    finally:
        conn.close()
    assert ("export_delivery_download_succeeded", "ok") in rows
    assert ("export_delivery_download_rejected", "missing_signature") in rows

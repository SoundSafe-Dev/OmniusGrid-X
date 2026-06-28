"""Integration coverage for async export job status/download boundaries."""

from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient


pytestmark = pytest.mark.asyncio


def _job(org_id, **overrides):
    job = {
        "job_id": str(uuid4()),
        "type": "export_telemetry",
        "status": "pending",
        "total": 10,
        "processed": 0,
        "succeeded": 0,
        "failed": 0,
        "errors": [],
        "file_path": None,
        "filename": None,
        "created_at": "2030-01-01T00:00:00+00:00",
        "updated_at": "2030-01-01T00:00:00+00:00",
        "organization_id": str(org_id),
    }
    job.update(overrides)
    return job


async def test_export_job_status_requires_auth(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/api/v1/exports/jobs/{uuid4()}")

    assert response.status_code == 401


async def test_export_job_status_is_tenant_scoped_and_omits_file_path(
    client_a,
    client_b,
    seeded_orgs,
    monkeypatch,
):
    import app.api.exports as exports_api

    job = _job(
        seeded_orgs["org_a_id"],
        status="completed",
        file_path="/tmp/private-export.csv",
        filename="telemetry.csv",
    )

    async def fake_get_job(_job_id):
        return dict(job)

    monkeypatch.setattr(exports_api.export_processor, "get_job", fake_get_job)

    owner = await client_a.get(f"/api/v1/exports/jobs/{job['job_id']}")
    foreign = await client_b.get(f"/api/v1/exports/jobs/{job['job_id']}")

    assert owner.status_code == 200
    body = owner.json()
    assert body["status"] == "completed"
    assert body["download_url"] == f"/api/v1/exports/jobs/{job['job_id']}/download"
    assert "file_path" not in body
    assert foreign.status_code == 404


async def test_export_job_download_handles_not_ready_missing_and_available_file(
    client_a,
    seeded_orgs,
    monkeypatch,
    tmp_path,
):
    import app.api.exports as exports_api

    job = _job(seeded_orgs["org_a_id"])

    async def fake_get_job(_job_id):
        return dict(job)

    monkeypatch.setattr(exports_api.export_processor, "get_job", fake_get_job)

    pending = await client_a.get(f"/api/v1/exports/jobs/{job['job_id']}/download")
    assert pending.status_code == 409

    job["status"] = "completed"
    job["file_path"] = str(tmp_path / "missing.csv")
    missing = await client_a.get(f"/api/v1/exports/jobs/{job['job_id']}/download")
    assert missing.status_code == 410

    export_file = tmp_path / "ready.csv"
    export_file.write_text("time,value\n2030-01-01T00:00:00Z,42\n", encoding="utf-8")
    job["file_path"] = str(export_file)
    job["filename"] = "ready.csv"

    ready = await client_a.get(f"/api/v1/exports/jobs/{job['job_id']}/download")
    assert ready.status_code == 200
    assert ready.content == b"time,value\n2030-01-01T00:00:00Z,42\n"
    assert ready.headers["content-disposition"] == 'attachment; filename="ready.csv"'


async def test_export_job_store_outage_returns_503(client_a, monkeypatch):
    import app.api.exports as exports_api

    async def broken_get_job(_job_id):
        raise RuntimeError("redis unavailable")

    monkeypatch.setattr(exports_api.export_processor, "get_job", broken_get_job)

    status = await client_a.get(f"/api/v1/exports/jobs/{uuid4()}")
    download = await client_a.get(f"/api/v1/exports/jobs/{uuid4()}/download")

    assert status.status_code == 503
    assert download.status_code == 503

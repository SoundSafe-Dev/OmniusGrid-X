"""Unit tests for compliance report generation and secure storage."""

from __future__ import annotations

import json
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.services.compliance_report_service import (
    ComplianceReportServiceError,
    _write_json_atomic,
    absolute_report_path,
    build_report_payload,
    generate_and_store_report,
    resolve_report_paths,
    validate_framework_and_format,
)


@pytest.fixture
def storage_root(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "app.services.compliance_report_service.settings.EXPORT_STORAGE_PATH",
        str(tmp_path),
    )
    return tmp_path


@pytest.fixture
async def tenant_session(tenant_async_url):
    engine = create_async_engine(tenant_async_url, future=True)
    session_maker = async_sessionmaker(engine, expire_on_commit=False)
    async with session_maker() as session:
        yield session
    await engine.dispose()


def test_validate_framework_and_format_rejects_unknown():
    with pytest.raises(ComplianceReportServiceError):
        validate_framework_and_format("hipaa", "json")
    with pytest.raises(ComplianceReportServiceError):
        validate_framework_and_format("all", "docx")


@pytest.mark.asyncio
async def test_tenant_a_report_excludes_tenant_b_data(
    admin_sync_url, seeded_orgs, tenant_session, storage_root
):
    import psycopg2

    org_a = seeded_orgs["org_a_id"]
    org_b = seeded_orgs["org_b_id"]
    asset_a = uuid4()
    asset_b = uuid4()

    conn = psycopg2.connect(admin_sync_url)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO security_assets
                (id, organization_id, asset_type, asset_name)
                VALUES (%s, %s, 'software', 'tenant-a-only'),
                       (%s, %s, 'hardware', 'tenant-b-only');
                """,
                (str(asset_a), str(org_a), str(asset_b), str(org_b)),
            )
    finally:
        conn.close()

    await tenant_session.execute(
        text("SELECT set_config('app.current_org_id', :org, false)"),
        {"org": str(org_a)},
    )
    payload = await build_report_payload(tenant_session, org_a, "iso27001", None)
    names = {item["asset_name"] for item in payload["details"]["iso_27001"]}
    assert names == {"tenant-a-only"}


@pytest.mark.asyncio
async def test_tenant_a_report_excludes_tenant_b_vendor_and_gdpr_data(
    admin_sync_url, seeded_orgs, tenant_session, storage_root
):
    import psycopg2

    org_a = seeded_orgs["org_a_id"]
    org_b = seeded_orgs["org_b_id"]
    vendor_a = uuid4()
    vendor_b = uuid4()
    processing_a = uuid4()
    processing_b = uuid4()
    consent_a = uuid4()
    consent_b = uuid4()

    conn = psycopg2.connect(admin_sync_url)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO vendor_risk_assessments
                (id, organization_id, vendor_name)
                VALUES (%s, %s, 'tenant-a-vendor'),
                       (%s, %s, 'tenant-b-vendor');
                INSERT INTO data_processing_records
                (id, organization_id, processing_activity, data_categories, purposes)
                VALUES (%s, %s, 'tenant-a-processing', ARRAY['personal'], ARRAY['ops']),
                       (%s, %s, 'tenant-b-processing', ARRAY['personal'], ARRAY['ops']);
                INSERT INTO consent_records
                (id, user_id, consent_type, consent_given)
                VALUES (%s, %s, 'data_processing', TRUE),
                       (%s, %s, 'data_processing', TRUE);
                """,
                (
                    str(vendor_a),
                    str(org_a),
                    str(vendor_b),
                    str(org_b),
                    str(processing_a),
                    str(org_a),
                    str(processing_b),
                    str(org_b),
                    str(consent_a),
                    str(seeded_orgs["user_a_id"]),
                    str(consent_b),
                    str(seeded_orgs["user_b_id"]),
                ),
            )
    finally:
        conn.close()

    payload = await build_report_payload(tenant_session, org_a, "all", None)
    vendor_names = {
        item["vendor_name"] for item in payload["details"]["soc_2"]
    }
    processing_ids = {
        item["id"] for item in payload["details"]["gdpr"]["processing_records"]
    }
    consent_ids = {
        item["id"] for item in payload["details"]["gdpr"]["consents"]
    }
    assert vendor_names == {"tenant-a-vendor"}
    assert processing_ids == {str(processing_a)}
    assert consent_ids == {str(consent_a)}


@pytest.mark.asyncio
async def test_json_generation(seeded_orgs, tenant_session, storage_root):
    org_id = seeded_orgs["org_a_id"]
    job_id = uuid4()
    metadata = await generate_and_store_report(
        tenant_session,
        org_id,
        job_id,
        "all",
        "json",
        seeded_orgs["user_a_id"],
    )
    absolute = absolute_report_path(metadata["file_path"])
    data = json.loads(absolute.read_text())
    assert data["framework"] == "all"
    assert data["organization_id"] == str(org_id)
    assert metadata["media_type"] == "application/json"
    assert metadata["file_size"] == absolute.stat().st_size
    assert len(metadata["file_sha256"]) == 64


@pytest.mark.asyncio
async def test_pdf_begins_with_pdf_magic(seeded_orgs, tenant_session, storage_root):
    org_id = seeded_orgs["org_a_id"]
    job_id = uuid4()
    metadata = await generate_and_store_report(
        tenant_session,
        org_id,
        job_id,
        "soc2",
        "pdf",
        seeded_orgs["user_a_id"],
    )
    absolute = absolute_report_path(metadata["file_path"])
    assert absolute.read_bytes()[:4] == b"%PDF"
    assert metadata["media_type"] == "application/pdf"


@pytest.mark.asyncio
async def test_pdf_escapes_special_characters(
    admin_sync_url, seeded_orgs, tenant_session, storage_root, monkeypatch
):
    import psycopg2

    org_id = seeded_orgs["org_a_id"]
    asset_id = uuid4()
    conn = psycopg2.connect(admin_sync_url)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO security_assets
                (id, organization_id, asset_type, asset_name)
                VALUES (%s, %s, 'software', '<script>&"vendor"');
                """,
                (str(asset_id), str(org_id)),
            )
    finally:
        conn.close()

    from app.services import compliance_report_service as service

    captured = []
    original_paragraph = service.Paragraph

    def capture_paragraph(value, style):
        captured.append(value)
        return original_paragraph(value, style)

    monkeypatch.setattr(service, "Paragraph", capture_paragraph)
    await generate_and_store_report(
        tenant_session,
        org_id,
        uuid4(),
        "iso27001",
        "pdf",
        seeded_orgs["user_a_id"],
    )
    rendered = "\n".join(captured)
    assert "<script>" not in rendered
    assert "&lt;script&gt;" in rendered
    assert "&amp;" in rendered


def test_atomic_file_write_leaves_no_temp_files(storage_root, monkeypatch):
    org_id = uuid4()
    job_id = uuid4()
    absolute, _relative = resolve_report_paths(org_id, job_id, "json")
    _write_json_atomic({"ok": True}, absolute)
    assert json.loads(absolute.read_text()) == {"ok": True}
    temps = list(absolute.parent.glob(f".{job_id}.json.*.tmp"))
    assert temps == []


def test_path_containment_rejects_escape(storage_root):
    org_id = uuid4()
    job_id = uuid4()
    absolute, relative = resolve_report_paths(org_id, job_id, "json")
    assert str(absolute).startswith(str(storage_root.resolve()))

    with pytest.raises(ComplianceReportServiceError):
        absolute_report_path("../../etc/passwd")

    sibling = storage_root.parent / f"{storage_root.name}-outside" / "secret.json"
    sibling.parent.mkdir()
    sibling.write_text("outside")
    sibling_relative = f"../{sibling.relative_to(storage_root.parent)}"
    with pytest.raises(ComplianceReportServiceError):
        absolute_report_path(sibling_relative)

    with pytest.raises(ComplianceReportServiceError):
        absolute_report_path(
            relative,
            organization_id=uuid4(),
            job_id=job_id,
        )


@pytest.mark.asyncio
async def test_size_and_checksum_match_file(seeded_orgs, tenant_session, storage_root):
    org_id = seeded_orgs["org_a_id"]
    job_id = uuid4()
    metadata = await generate_and_store_report(
        tenant_session,
        org_id,
        job_id,
        "gdpr",
        "json",
        seeded_orgs["user_a_id"],
    )
    absolute = absolute_report_path(metadata["file_path"])
    assert metadata["file_size"] == absolute.stat().st_size
    import hashlib

    assert metadata["file_sha256"] == hashlib.sha256(absolute.read_bytes()).hexdigest()

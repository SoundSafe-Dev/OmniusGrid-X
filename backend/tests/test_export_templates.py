from uuid import uuid4
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.middleware.rbac import require_admin
from app.services.export_delivery import (
    create_download_signature,
    next_run_at,
    verify_download_signature,
)
from app.services.export_processor import (
    ExportError,
    _cell,
    validate_export_configuration,
)


def test_validate_telemetry_template_normalizes_configuration():
    asset_id = uuid4()

    columns, filters = validate_export_configuration(
        "telemetry",
        "csv",
        ["time", "value"],
        {"asset_id": str(asset_id), "metric_name": "temperature"},
    )

    assert columns == ["time", "value"]
    assert filters == {
        "asset_id": str(asset_id),
        "metric_name": "temperature",
    }


def test_validate_template_rejects_wrong_format():
    with pytest.raises(ExportError, match="requires format 'xlsx'"):
        validate_export_configuration("kanban_tasks", "csv", [], {})


def test_validate_template_rejects_unknown_columns_and_filters():
    with pytest.raises(ExportError, match="Unknown column"):
        validate_export_configuration(
            "registries", "xlsx", ["registry_name", "password"], {}
        )

    with pytest.raises(ExportError, match="Unknown filter"):
        validate_export_configuration(
            "registries", "xlsx", [], {"organization_id": str(uuid4())}
        )


def test_validate_template_requires_resource_identifier():
    with pytest.raises(ExportError, match="Missing required filter"):
        validate_export_configuration("oee_asset", "pdf", [], {})


def test_schedule_recurrence_preserves_month_end():
    current = datetime(2028, 1, 31, 8, tzinfo=timezone.utc)
    assert next_run_at(current, "monthly", "UTC") == datetime(
        2028, 2, 29, 8, tzinfo=timezone.utc
    )


def test_download_signature_is_bound_to_job_and_organization():
    job_id = uuid4()
    org_id = uuid4()
    signature = create_download_signature(job_id, org_id)

    assert verify_download_signature(signature, job_id, org_id)
    assert not verify_download_signature(signature, uuid4(), org_id)
    assert not verify_download_signature(signature, job_id, uuid4())


def test_legacy_export_signature_remains_valid(monkeypatch):
    from datetime import timedelta

    import jwt

    from app.core.config import settings

    monkeypatch.setattr(settings, "SIGNED_URL_SECRET_KEY", "signed-secret")
    monkeypatch.setattr(settings, "JWT_SECRET_KEY", "jwt-secret")
    job_id = uuid4()
    org_id = uuid4()
    legacy = jwt.encode(
        {
            "organization_id": str(org_id),
            "job_id": str(job_id),
            "purpose": "export_download",
            "exp": datetime.now(timezone.utc) + timedelta(hours=1),
        },
        settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )
    assert verify_download_signature(legacy, job_id, org_id)


async def test_exports_reject_non_admin_users():
    with pytest.raises(HTTPException) as exc:
        await require_admin(
            current_user=SimpleNamespace(id=uuid4(), role="operator")
        )
    assert exc.value.status_code == 403


@pytest.mark.parametrize("value", ["=1+1", "+SUM(A1:A2)", "-2+3", "@cmd"])
def test_spreadsheet_cells_escape_formula_prefixes(value):
    assert _cell(value) == f"'{value}"


async def _create_template(client, name: str = "Daily telemetry") -> dict:
    response = await client.post(
        "/api/v1/exports/templates",
        json={
            "name": name,
            "export_type": "telemetry",
            "export_format": "csv",
            "columns": ["time", "metric_name", "value"],
            "filters": {"asset_id": "00000000-0000-0000-0000-000000000001"},
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


class TestExportTemplateAPI:
    async def test_templates_are_tenant_scoped(self, client_a, client_b):
        template = await _create_template(client_a)

        owner = await client_a.get(f"/api/v1/exports/templates/{template['id']}")
        foreign = await client_b.get(f"/api/v1/exports/templates/{template['id']}")
        foreign_listing = await client_b.get("/api/v1/exports/templates")

        assert owner.status_code == 200
        assert foreign.status_code == 404
        assert foreign_listing.status_code == 200
        assert foreign_listing.json()["items"] == []

    async def test_duplicate_template_name_returns_conflict(self, client_a):
        await _create_template(client_a)
        duplicate = await client_a.post(
            "/api/v1/exports/templates",
            json={
                "name": "Daily telemetry",
                "export_type": "telemetry",
                "export_format": "csv",
                "columns": ["time"],
                "filters": {
                    "asset_id": "00000000-0000-0000-0000-000000000001"
                },
            },
        )

        assert duplicate.status_code == 409

    async def test_schedule_requires_company_smtp_before_activation(self, client_a):
        template = await _create_template(client_a)
        response = await client_a.post(
            "/api/v1/exports/schedules",
            json={
                "template_id": template["id"],
                "name": "Every morning",
                "frequency": "daily",
                "timezone": "UTC",
                "next_run_at": "2030-01-01T08:00:00Z",
                "recipients": ["reports@example.com"],
                "is_active": True,
            },
        )

        assert response.status_code == 503
        assert "SMTP is not configured" in response.json()["detail"]

    async def test_deleting_template_removes_its_inactive_schedule(
        self, client_a, seeded_orgs
    ):
        template = await _create_template(client_a)
        admin_email = f"a-{seeded_orgs['user_a_id'].hex[:8]}@test.local"
        schedule_response = await client_a.post(
            "/api/v1/exports/schedules",
            json={
                "template_id": template["id"],
                "name": "Every morning",
                "frequency": "daily",
                "timezone": "UTC",
                "next_run_at": "2030-01-01T08:00:00Z",
                "recipients": [admin_email],
            },
        )
        assert schedule_response.status_code == 201, schedule_response.text
        schedule_id = schedule_response.json()["id"]

        deleted = await client_a.delete(f"/api/v1/exports/templates/{template['id']}")
        missing_schedule = await client_a.get(
            f"/api/v1/exports/schedules/{schedule_id}"
        )

        assert deleted.status_code == 200
        assert missing_schedule.status_code == 404

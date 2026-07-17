"""ORM contracts for integration-branch schema migrations."""

from sqlalchemy import CheckConstraint, UniqueConstraint
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import JSONB

from app.db.models import (
    ErrorEvent,
    ExportDeliveryJob,
    ExportTemplate,
    ScheduledExport,
    SecurityAsset,
    VendorRiskAssessment,
)


def _check_names(table):
    return {
        constraint.name
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint)
    }


def _unique_names(table):
    return {
        constraint.name
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    }


def _ondelete_by_column(table):
    return {fk.parent.name: fk.ondelete for fk in table.foreign_keys}


def _assert_postgres_jsonb(column):
    assert isinstance(column.type.dialect_impl(postgresql.dialect()), JSONB)


def test_export_template_orm_matches_migration_012_contract():
    table = ExportTemplate.__table__

    assert "uq_export_templates_org_name" in _unique_names(table)
    _assert_postgres_jsonb(table.c.columns)
    _assert_postgres_jsonb(table.c.filters)
    assert _ondelete_by_column(table) == {
        "organization_id": "CASCADE",
        "created_by": "SET NULL",
    }


def test_scheduled_export_orm_matches_migration_012_contract():
    table = ScheduledExport.__table__

    assert "ck_scheduled_exports_frequency" in _check_names(table)
    _assert_postgres_jsonb(table.c.recipients)
    assert _ondelete_by_column(table) == {
        "organization_id": "CASCADE",
        "template_id": "CASCADE",
        "created_by": "SET NULL",
    }


def test_export_delivery_job_orm_matches_migration_012_contract():
    table = ExportDeliveryJob.__table__

    assert "uq_export_delivery_jobs_schedule_run" in _unique_names(table)
    assert _ondelete_by_column(table) == {
        "organization_id": "CASCADE",
        "schedule_id": "CASCADE",
        "template_id": "CASCADE",
        "requested_by": "SET NULL",
    }


def test_error_event_orm_matches_migration_018_contract():
    table = ErrorEvent.__table__

    assert "ck_error_events_status" in _check_names(table)
    assert _ondelete_by_column(table) == {
        "status_changed_by": "SET NULL",
    }


def test_compliance_tenant_ownership_matches_final_migration_contract():
    assert SecurityAsset.__table__.c.organization_id.nullable is False
    assert VendorRiskAssessment.__table__.c.organization_id.nullable is False

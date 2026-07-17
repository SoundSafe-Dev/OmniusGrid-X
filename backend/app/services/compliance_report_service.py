"""Tenant-scoped compliance report generation and secure file persistence."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID
from xml.sax.saxutils import escape as xml_escape

import structlog
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import (
    ConsentRecord,
    DataProcessingRecord,
    SecurityAsset,
    User,
    VendorRiskAssessment,
)

logger = structlog.get_logger()

SUPPORTED_FRAMEWORKS = frozenset({"all", "gdpr", "soc2", "iso27001"})
SUPPORTED_FORMATS = frozenset({"json", "pdf"})
MAX_ERROR_LENGTH = 2000


class ComplianceReportServiceError(ValueError):
    """Invalid report request or unsafe storage path."""


async def set_tenant_guc(session: AsyncSession, org_id: UUID) -> None:
    await session.execute(
        text("SELECT set_config('app.current_org_id', :org_id, true)"),
        {"org_id": str(org_id)},
    )


def validate_framework_and_format(framework: str, report_format: str) -> None:
    if framework not in SUPPORTED_FRAMEWORKS:
        raise ComplianceReportServiceError(f"Unsupported framework '{framework}'")
    if report_format not in SUPPORTED_FORMATS:
        raise ComplianceReportServiceError(f"Unsupported format '{report_format}'")


def _storage_root() -> Path:
    return Path(settings.EXPORT_STORAGE_PATH).resolve()


def resolve_report_paths(
    organization_id: UUID,
    job_id: UUID,
    extension: str,
) -> tuple[Path, str]:
    root = _storage_root()
    relative = Path("compliance") / str(organization_id) / f"{job_id}.{extension}"
    absolute = (root / relative).resolve()
    if not absolute.is_relative_to(root):
        raise ComplianceReportServiceError("Resolved report path escapes storage root")
    return absolute, str(relative)


async def build_report_payload(
    session: AsyncSession,
    organization_id: UUID,
    framework: str,
    requested_by: UUID | None,
) -> dict[str, Any]:
    """Collect tenant-scoped compliance data into one neutral report dictionary."""
    validate_framework_and_format(framework, "json")
    await set_tenant_guc(session, organization_id)

    report: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "generated_by": str(requested_by) if requested_by else None,
        "framework": framework,
        "organization_id": str(organization_id),
        "summary": {},
        "details": {},
    }

    if framework in {"all", "iso27001"}:
        assets = (
            await session.execute(
                select(SecurityAsset).where(SecurityAsset.organization_id == organization_id)
            )
        ).scalars().all()
        report["summary"]["iso_27001"] = {
            "total_assets": len(assets),
            "by_type": {},
            "by_classification": {},
        }
        for asset in assets:
            report["summary"]["iso_27001"]["by_type"][asset.asset_type] = (
                report["summary"]["iso_27001"]["by_type"].get(asset.asset_type, 0) + 1
            )
            if asset.classification:
                report["summary"]["iso_27001"]["by_classification"][asset.classification] = (
                    report["summary"]["iso_27001"]["by_classification"]
                    .get(asset.classification, 0)
                    + 1
                )
        report["details"]["iso_27001"] = [
            {
                "id": str(asset.id),
                "asset_type": asset.asset_type,
                "asset_name": asset.asset_name,
                "classification": asset.classification,
                "status": asset.status,
            }
            for asset in assets
        ]

    if framework in {"all", "soc2"}:
        vendors = (
            await session.execute(
                select(VendorRiskAssessment).where(
                    VendorRiskAssessment.organization_id == organization_id
                )
            )
        ).scalars().all()
        report["summary"]["soc_2"] = {
            "total_assessments": len(vendors),
            "by_risk_level": {},
            "by_status": {},
        }
        for vendor in vendors:
            if vendor.risk_level:
                report["summary"]["soc_2"]["by_risk_level"][vendor.risk_level] = (
                    report["summary"]["soc_2"]["by_risk_level"].get(vendor.risk_level, 0) + 1
                )
            if vendor.status:
                report["summary"]["soc_2"]["by_status"][vendor.status] = (
                    report["summary"]["soc_2"]["by_status"].get(vendor.status, 0) + 1
                )
        report["details"]["soc_2"] = [
            {
                "id": str(vendor.id),
                "vendor_name": vendor.vendor_name,
                "risk_level": vendor.risk_level,
                "status": vendor.status,
                "assessment_date": (
                    vendor.assessment_date.isoformat() if vendor.assessment_date else None
                ),
            }
            for vendor in vendors
        ]

    if framework in {"all", "gdpr"}:
        consents = (
            await session.execute(
                select(ConsentRecord)
                .join(User, ConsentRecord.user_id == User.id)
                .where(
                    ConsentRecord.user_id.isnot(None),
                    User.organization_id == organization_id,
                )
            )
        ).scalars().all()
        processing = (
            await session.execute(
                select(DataProcessingRecord).where(
                    DataProcessingRecord.organization_id == organization_id
                )
            )
        ).scalars().all()
        report["summary"]["gdpr"] = {
            "total_consent_records": len(consents),
            "active_consents": sum(
                1 for consent in consents if consent.consent_given and not consent.withdrawn_at
            ),
            "data_processing_records": len(processing),
        }
        report["details"]["gdpr"] = {
            "consents": [
                {
                    "id": str(consent.id),
                    "consent_type": consent.consent_type,
                    "consent_given": consent.consent_given,
                    "withdrawn_at": (
                        consent.withdrawn_at.isoformat() if consent.withdrawn_at else None
                    ),
                }
                for consent in consents
            ],
            "processing_records": [
                {
                    "id": str(record.id),
                    "processing_activity": record.processing_activity,
                    "legal_basis": record.legal_basis,
                }
                for record in processing
            ],
        }

    return report


def _render_pdf(report: dict[str, Any], output_path: Path) -> None:
    styles = getSampleStyleSheet()
    story = [
        Paragraph(
            xml_escape(f"OmniusGrid Compliance Report ({report['framework']})"),
            styles["Title"],
        ),
        Spacer(1, 12),
        Paragraph(xml_escape(f"Generated at: {report['generated_at']}"), styles["Normal"]),
        Paragraph(
            xml_escape(f"Organization: {report['organization_id']}"),
            styles["Normal"],
        ),
    ]
    for section_name, section_data in report.get("summary", {}).items():
        story.append(Spacer(1, 8))
        story.append(Paragraph(xml_escape(section_name), styles["Heading2"]))
        story.append(
            Paragraph(xml_escape(json.dumps(section_data, sort_keys=True)), styles["Code"])
        )
    for section_name, section_data in report.get("details", {}).items():
        story.append(Spacer(1, 8))
        story.append(
            Paragraph(xml_escape(f"{section_name} details"), styles["Heading2"])
        )
        story.append(
            Paragraph(xml_escape(json.dumps(section_data, sort_keys=True)), styles["Code"])
        )
    doc = SimpleDocTemplate(str(output_path), pagesize=letter)
    doc.build(story)


def _write_json_atomic(payload: dict[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(
        dir=output_path.parent,
        prefix=f".{output_path.name}.",
        suffix=".tmp",
    )
    os.close(fd)
    temp_path = Path(temp_name)
    try:
        temp_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        os.replace(temp_path, output_path)
    finally:
        if temp_path.exists():
            temp_path.unlink(missing_ok=True)


def _write_pdf_atomic(payload: dict[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(
        dir=output_path.parent,
        prefix=f".{output_path.name}.",
        suffix=".tmp",
    )
    os.close(fd)
    temp_path = Path(temp_name)
    try:
        _render_pdf(payload, temp_path)
        os.replace(temp_path, output_path)
    finally:
        if temp_path.exists():
            temp_path.unlink(missing_ok=True)


def _file_metadata(output_path: Path, report_format: str) -> tuple[str, str, int, str]:
    media_type = "application/pdf" if report_format == "pdf" else "application/json"
    filename = output_path.name
    return (
        filename,
        media_type,
        output_path.stat().st_size,
        _sha256_file(output_path),
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def report_file_matches_metadata(
    path: Path,
    *,
    expected_sha256: str | None,
    expected_size: int | None,
) -> bool:
    if not expected_sha256 or not path.is_file():
        return False
    try:
        if expected_size is not None and path.stat().st_size != expected_size:
            return False
        return _sha256_file(path) == expected_sha256
    except OSError:
        return False


async def generate_and_store_report(
    session: AsyncSession,
    organization_id: UUID,
    job_id: UUID,
    framework: str,
    report_format: str,
    requested_by: UUID | None,
) -> dict[str, str | int]:
    """Build, persist, and return file metadata for a compliance report job."""
    validate_framework_and_format(framework, report_format)
    payload = await build_report_payload(session, organization_id, framework, requested_by)
    extension = "pdf" if report_format == "pdf" else "json"
    output_path, relative_path = resolve_report_paths(organization_id, job_id, extension)

    if report_format == "pdf":
        _write_pdf_atomic(payload, output_path)
    else:
        _write_json_atomic(payload, output_path)

    filename, media_type, file_size, file_sha256 = _file_metadata(output_path, report_format)
    logger.info(
        "compliance_report_stored",
        job_id=str(job_id),
        organization_id=str(organization_id),
        format=report_format,
        file_size=file_size,
    )
    return {
        "file_path": relative_path,
        "filename": filename,
        "media_type": media_type,
        "file_size": file_size,
        "file_sha256": file_sha256,
    }


def absolute_report_path(
    relative_path: str,
    *,
    organization_id: UUID | None = None,
    job_id: UUID | None = None,
) -> Path:
    root = _storage_root()
    absolute = (root / relative_path).resolve()
    if not absolute.is_relative_to(root):
        raise ComplianceReportServiceError("Report file path escapes storage root")
    if organization_id is not None:
        organization_root = (root / "compliance" / str(organization_id)).resolve()
        if absolute.parent != organization_root:
            raise ComplianceReportServiceError(
                "Report file path does not belong to the expected organization"
            )
    if job_id is not None and absolute.name not in {f"{job_id}.json", f"{job_id}.pdf"}:
        raise ComplianceReportServiceError(
            "Report file path does not belong to the expected job"
        )
    return absolute


def truncate_error(message: str | None) -> str | None:
    if message is None:
        return None
    return message[:MAX_ERROR_LENGTH]

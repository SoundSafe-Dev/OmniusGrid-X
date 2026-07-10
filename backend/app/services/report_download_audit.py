"""Audit helpers for public signed report download endpoints."""

from __future__ import annotations

import json
import uuid
from typing import Any
from uuid import UUID

import structlog
from fastapi import Request
from sqlalchemy import text

from app.db.database import AsyncSessionLocal

logger = structlog.get_logger()


def _client_ip(request: Request) -> str | None:
    if request.client is None:
        return None
    return request.client.host


async def audit_compliance_report_download(
    *,
    request: Request,
    succeeded: bool,
    job_id: UUID,
    organization_id: UUID | None,
    reason: str,
    token_version: int | None = None,
    purpose: str | None = None,
    token_id: str | None = None,
) -> None:
    action = (
        "compliance_report_download_succeeded"
        if succeeded
        else "compliance_report_download_rejected"
    )
    details: dict[str, Any] = {"reason": reason}
    if token_version is not None:
        details["token_version"] = token_version
    if purpose is not None:
        details["purpose"] = purpose
    if token_id is not None:
        details["jti"] = token_id
    await _insert_audit(
        request=request,
        action=action,
        resource_type="compliance_report",
        resource_id=str(job_id),
        organization_id=organization_id,
        details=details,
    )


async def audit_export_delivery_download(
    *,
    request: Request,
    succeeded: bool,
    job_id: UUID,
    organization_id: UUID | None,
    reason: str,
    token_version: int | None = None,
    purpose: str | None = None,
    token_id: str | None = None,
) -> None:
    action = (
        "export_delivery_download_succeeded"
        if succeeded
        else "export_delivery_download_rejected"
    )
    details: dict[str, Any] = {"reason": reason}
    if token_version is not None:
        details["token_version"] = token_version
    if purpose is not None:
        details["purpose"] = purpose
    if token_id is not None:
        details["jti"] = token_id
    await _insert_audit(
        request=request,
        action=action,
        resource_type="export_delivery",
        resource_id=str(job_id),
        organization_id=organization_id,
        details=details,
    )


async def _insert_audit(
    *,
    request: Request,
    action: str,
    resource_type: str,
    resource_id: str,
    organization_id: UUID | None,
    details: dict[str, Any],
) -> None:
    try:
        async with AsyncSessionLocal() as session:
            if organization_id is not None:
                await session.execute(
                    text("SELECT set_config('app.current_org_id', :org, true)"),
                    {"org": str(organization_id)},
                )
            await session.execute(
                text(
                    """
                    INSERT INTO audit_logs
                        (id, timestamp, user_id, organization_id, action,
                         resource_type, resource_id, details, ip_address, user_agent)
                    VALUES
                        (:id, now(), NULL, :organization_id, :action,
                         :resource_type, :resource_id, CAST(:details AS JSONB),
                         :ip_address, :user_agent)
                    """
                ),
                {
                    "id": str(uuid.uuid4()),
                    "organization_id": str(organization_id) if organization_id else None,
                    "action": action,
                    "resource_type": resource_type,
                    "resource_id": resource_id,
                    "details": json.dumps(details),
                    "ip_address": _client_ip(request),
                    "user_agent": request.headers.get("user-agent"),
                },
            )
            await session.commit()
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "report_download_audit_failed",
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            reason=details.get("reason"),
            error=str(exc),
        )

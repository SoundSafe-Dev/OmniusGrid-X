"""Narrow helpers for explicit user-administration audit events."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AuditLog


def add_user_audit(
    db: AsyncSession,
    request: Request,
    *,
    organization_id: UUID,
    action: str,
    resource_type: str,
    resource_id: UUID,
    details: dict[str, Any],
    actor_id: UUID | None,
) -> None:
    """Append one safe audit row inside the caller's transaction."""

    db.add(
        AuditLog(
            user_id=actor_id,
            organization_id=organization_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            details=details,
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
            hash_chain="pending",
        )
    )

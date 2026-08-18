"""Audit Log API Routes

Admin-only endpoints for viewing and managing security audit logs.
"""

from typing import Any, Dict, List, Optional
from datetime import datetime
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, and_, or_, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.pagination import MAX_OFFSET
from app.db.database import get_db  # noqa: F401
from app.middleware.tenant_isolation import get_tenant_db
from app.db.models import AuditLog, User
from app.middleware.rbac import require_admin

from pydantic import BaseModel  # noqa: E402

def _ip_str(value) -> str | None:
    """The stored address as a string, or None (FS-503).

    `AuditLog.ip_address` is `String(45).with_variant(INET, "postgresql")`
    (`app/db/models.py:1569`), so on Postgres the column is INET and the driver hands back an
    `ipaddress.IPv4Address`/`IPv6Address`. The response models here declare `Optional[str]`,
    and pydantic will not coerce an address object into a `str` field — it raises, and
    FastAPI turns that into a 500. Every row carrying an IP broke the page it appeared on.

    Converting at the boundary rather than widening the declared type, because the API's
    contract really is a string: `str(IPv4Address("127.0.0.1")) == "127.0.0.1"`, which is
    what every client already expects to receive.

    On SQLite the variant is VARCHAR and the value is already a string, so this is a no-op
    there — which is exactly why no non-realdb test could see the defect.
    """
    return None if value is None else str(value)


router = APIRouter()


# ---- Response schemas (pool #43 / FS-254). Documented, not reshaped.


class AuditLogOut(BaseModel):
    id: str
    timestamp: Optional[Any] = None
    user_id: Optional[str] = None
    organization_id: Optional[str] = None
    action: str
    resource_type: Optional[str] = None
    resource_id: Optional[str] = None
    details: Optional[Any] = None
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    #: The tamper-evidence chain. Nullable because rows written before migration
    #: 009's trigger existed have none — and, for a stretch this codebase has
    #: documented, because the trigger raised on every insert and no row was
    #: written at all.
    hash_chain: Optional[str] = None
    created_at: Optional[Any] = None


class AuditLogList(BaseModel):
    items: List[AuditLogOut]
    total: int
    skip: int
    limit: int


class HashChainVerification(BaseModel):
    verified: bool
    total_logs: int
    #: Absent on the clean path, present when links fail — so it is optional
    #: rather than an empty list, matching what the handler sends.
    errors: Optional[List[Any]] = None
    message: str


class AuditActionList(BaseModel):
    actions: List[str]
    total: int


class AuditSummary(BaseModel):
    total_logs: int
    by_action: Dict[str, Any]
    by_resource_type: Dict[str, Any]
    by_user: Dict[str, Any]
    time_range: Dict[str, Any]



@router.get("/logs", response_model=AuditLogList, summary="List audit logs", description="Retrieve audit logs with optional filtering. Admin access required.")
async def list_audit_logs(
    current_user: User = Depends(require_admin),
    user_id: Optional[UUID] = None,
    action: Optional[str] = None,
    resource_type: Optional[str] = None,
    start_time: Optional[datetime] = None,
    end_time: Optional[datetime] = None,
    skip: int = Query(0, ge=0, le=MAX_OFFSET),
    limit: int = Query(100, ge=1, le=1000),
    db: AsyncSession = Depends(get_tenant_db)
):
    """List audit logs with filtering"""
    query = select(AuditLog)

    # SCOPED BY RLS, via get_tenant_db. `audit_logs` has had a tenant policy since
    # migration 011, and this handler ran on `get_db` — which sets no GUC — so the
    # policy matched nothing and **every audit endpoint returned zero rows**, including
    # for the caller's own organization. The compliance surface was silently blank,
    # which is the failure this table's policy exists to make impossible.
    #
    # The branch that used to sit here read:
    #
    #     if current_user.role != "admin" and current_user.organization_id:
    #         query = query.where(AuditLog.organization_id == current_user.organization_id)
    #
    # It was unreachable: the endpoint is gated on `require_admin`, so `role` is always
    # "admin". It was written for a cross-organization admin view, and the safe reading
    # of a multi-tenant product is that a tenant admin sees their own tenant — one
    # tenant's admin reading another's audit trail is exactly what an audit trail is
    # supposed to preclude. Cross-org access needs the super-admin role that does not
    # exist yet (the same one `data_retention` is blocked on).
    #
    # THE `organization_id` QUERY PARAMETER IS GONE for the same reason. It read as a
    # cross-tenant selector and could never be one: this session is RLS-scoped, so any
    # value but the caller's own org matches zero rows — verified against a real database
    # (org A supplying org B's id got a 200 and an empty list, not org B's trail). A
    # parameter that can only narrow-to-nothing is a footgun on the one table where a
    # cross-tenant read IS the incident, and it would become a live selector the moment
    # anything ran this query with RLS bypassed. No caller sent it; AuditLogs.tsx builds
    # its query string by hand and never included it.
    
    # Apply filters
    if user_id:
        query = query.where(AuditLog.user_id == str(user_id))
    if action:
        query = query.where(AuditLog.action == action)
    if resource_type:
        query = query.where(AuditLog.resource_type == resource_type)
    if start_time:
        query = query.where(AuditLog.timestamp >= start_time)
    if end_time:
        query = query.where(AuditLog.timestamp <= end_time)
    
    # Order by timestamp descending
    query = query.order_by(AuditLog.timestamp.desc())
    
    # Pagination
    query = query.offset(skip).limit(limit)
    
    result = await db.execute(query)
    logs = result.scalars().all()
    
    return {
        "items": [
            {
                "id": str(log.id),
                "timestamp": log.timestamp.isoformat(),
                "user_id": log.user_id,
                "organization_id": log.organization_id,
                "action": log.action,
                "resource_type": log.resource_type,
                "resource_id": log.resource_id,
                "details": log.details,
                "ip_address": _ip_str(log.ip_address),
                "user_agent": log.user_agent,
                "hash_chain": log.hash_chain,
            }
            for log in logs
        ],
        "total": len(logs),
        "skip": skip,
        "limit": limit
    }


@router.get("/logs/{log_id}", response_model=AuditLogOut, summary="Get audit log details", description="Retrieve detailed information about a specific audit log entry. Admin access required.")
async def get_audit_log(
    log_id: UUID,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_tenant_db)
):
    """Get a single audit log by ID"""
    result = await db.execute(
        select(AuditLog).where(AuditLog.id == str(log_id))
    )
    log = result.scalar_one_or_none()
    
    if not log:
        raise HTTPException(status_code=404, detail="Audit log not found")
    
    # Check organization access for non-admin users
    if current_user.role != "admin" and log.organization_id != current_user.organization_id:
        raise HTTPException(status_code=403, detail="Access denied")
    
    return {
        "id": str(log.id),
        "timestamp": log.timestamp.isoformat(),
        "user_id": log.user_id,
        "organization_id": log.organization_id,
        "action": log.action,
        "resource_type": log.resource_type,
        "resource_id": log.resource_id,
        "details": log.details,
        "ip_address": _ip_str(log.ip_address),
        "user_agent": log.user_agent,
        "hash_chain": log.hash_chain,
        "created_at": log.created_at.isoformat() if log.created_at else None
    }


@router.get("/verify", response_model=HashChainVerification, summary="Verify hash chain integrity", description="Verify the integrity of the audit log hash chain to detect tampering. Admin access required.")
async def verify_hash_chain(
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_tenant_db)
):
    """Verify audit log hash chain integrity.

    THIS RECOMPUTED THE DIGEST IN PYTHON AND COULD NEVER AGREE WITH THE WRITER (FS-743).
    The trigger hashed `to_jsonb(NEW)` -- the whole row, including `hash_chain` itself, a
    value the stored row no longer carries -- while this function hashed a sorted 10-field
    subset. Two implementations of one hash, guaranteed to differ, so the endpoint reported
    every row as tampered on any non-empty table. No test asserted it passed, which is how
    an integrity control shipped inverted.

    Verification is now one SQL function (`verify_audit_hash_chain`, migration 069) calling
    the SAME `calculate_audit_hash` the trigger calls. There is no second implementation to
    drift, which is the only durable fix for this class.

    Rows written before that migration carry `hash_version = 1` and were hashed by the old,
    unverifiable algorithm. They are counted and reported as such rather than folded into
    the violation count: nothing altered them, so calling them tampered would be a false
    accusation, and calling them verified would be a false assurance.

    Scope is the caller's own organisation, by RLS -- and the chain is built per
    organisation, so a tenant verifies their own chain end to end without needing to see
    anybody else's rows.
    """
    verified_total = (
        await db.execute(
            text("SELECT count(*) FROM audit_logs WHERE hash_version = 2")
        )
    ).scalar_one()
    legacy_total = (
        await db.execute(
            text("SELECT count(*) FROM audit_logs WHERE hash_version <> 2")
        )
    ).scalar_one()

    if verified_total == 0 and legacy_total == 0:
        return {
            "verified": True,
            "total_logs": 0,
            "message": "No audit logs to verify",
        }

    rows = (
        await db.execute(text("SELECT * FROM verify_audit_hash_chain()"))
    ).mappings().all()
    errors = [
        {
            "log_id": str(row["log_id"]),
            "timestamp": row["log_timestamp"].isoformat(),
            "expected_hash": row["expected_hash"],
            "actual_hash": row["actual_hash"],
        }
        for row in rows
    ]

    legacy_note = (
        f" {legacy_total} legacy record(s) predate the verifiable chain "
        f"(hash_version 1) and were not checked."
        if legacy_total
        else ""
    )
    message = (
        f"Hash chain verified across {verified_total} record(s).{legacy_note}"
        if not errors
        else f"Found {len(errors)} hash chain violation(s).{legacy_note}"
    )

    return {
        "verified": not errors,
        "total_logs": verified_total,
        "errors": errors or None,
        "message": message,
    }


@router.get("/actions", response_model=AuditActionList, summary="List available audit actions", description="Retrieve a list of all unique audit actions recorded in the system. Admin access required.")
async def list_audit_actions(
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_tenant_db)
):
    """List all unique audit actions"""
    result = await db.execute(
        select(AuditLog.action).distinct().order_by(AuditLog.action)
    )
    actions = result.scalars().all()
    
    return {
        "actions": list(actions),
        "total": len(actions)
    }


@router.get("/summary", response_model=AuditSummary, summary="Audit log summary", description="Get a summary of audit log statistics by action and time period. Admin access required.")
async def audit_log_summary(
    current_user: User = Depends(require_admin),
    start_time: Optional[datetime] = None,
    end_time: Optional[datetime] = None,
    db: AsyncSession = Depends(get_tenant_db)
):
    """Get audit log summary statistics"""
    query = select(AuditLog)
    
    # Apply time filters
    if start_time:
        query = query.where(AuditLog.timestamp >= start_time)
    if end_time:
        query = query.where(AuditLog.timestamp <= end_time)
    
    # Apply organization filter for non-admin users
    if current_user.role != "admin" and current_user.organization_id:
        query = query.where(AuditLog.organization_id == current_user.organization_id)
    
    result = await db.execute(query)
    logs = result.scalars().all()
    
    # Calculate statistics
    action_counts = {}
    resource_type_counts = {}
    user_counts = {}
    
    for log in logs:
        # Count by action
        action_counts[log.action] = action_counts.get(log.action, 0) + 1
        
        # Count by resource type
        if log.resource_type:
            resource_type_counts[log.resource_type] = resource_type_counts.get(log.resource_type, 0) + 1
        
        # Count by user
        if log.user_id:
            user_counts[log.user_id] = user_counts.get(log.user_id, 0) + 1
    
    return {
        "total_logs": len(logs),
        "by_action": action_counts,
        "by_resource_type": resource_type_counts,
        "by_user": user_counts,
        "time_range": {
            "start": start_time.isoformat() if start_time else None,
            "end": end_time.isoformat() if end_time else None
        }
    }

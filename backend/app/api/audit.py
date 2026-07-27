"""Audit Log API Routes

Admin-only endpoints for viewing and managing security audit logs.
"""

from typing import List, Optional
from datetime import datetime
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db  # noqa: F401
from app.middleware.tenant_isolation import get_tenant_db
from app.db.models import AuditLog, User
from app.middleware.rbac import require_admin

router = APIRouter()


@router.get("/logs", summary="List audit logs", description="Retrieve audit logs with optional filtering. Admin access required.")
async def list_audit_logs(
    current_user: User = Depends(require_admin),
    user_id: Optional[UUID] = None,
    organization_id: Optional[UUID] = None,
    action: Optional[str] = None,
    resource_type: Optional[str] = None,
    start_time: Optional[datetime] = None,
    end_time: Optional[datetime] = None,
    skip: int = Query(0, ge=0),
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
    
    # Apply filters
    if user_id:
        query = query.where(AuditLog.user_id == str(user_id))
    if organization_id:
        query = query.where(AuditLog.organization_id == str(organization_id))
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
                "ip_address": log.ip_address,
                "user_agent": log.user_agent,
                "hash_chain": log.hash_chain,
            }
            for log in logs
        ],
        "total": len(logs),
        "skip": skip,
        "limit": limit
    }


@router.get("/logs/{log_id}", summary="Get audit log details", description="Retrieve detailed information about a specific audit log entry. Admin access required.")
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
        "ip_address": log.ip_address,
        "user_agent": log.user_agent,
        "hash_chain": log.hash_chain,
        "created_at": log.created_at.isoformat() if log.created_at else None
    }


@router.get("/verify", summary="Verify hash chain integrity", description="Verify the integrity of the audit log hash chain to detect tampering. Admin access required.")
async def verify_hash_chain(
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_tenant_db)
):
    """Verify audit log hash chain integrity"""
    result = await db.execute(
        select(AuditLog).order_by(AuditLog.timestamp.asc(), AuditLog.id.asc())
    )
    logs = result.scalars().all()
    
    if not logs:
        return {
            "verified": True,
            "message": "No audit logs to verify",
            "total_logs": 0
        }
    
    # Verify hash chain
    previous_hash = None
    verification_errors = []
    
    for log in logs:
        # Calculate expected hash
        import hashlib
        import json
        
        log_data = {
            "id": str(log.id),
            "timestamp": log.timestamp.isoformat(),
            "user_id": log.user_id,
            "organization_id": log.organization_id,
            "action": log.action,
            "resource_type": log.resource_type,
            "resource_id": log.resource_id,
            "details": log.details,
            "ip_address": log.ip_address,
            "user_agent": log.user_agent,
        }
        
        combined = (previous_hash or "") + json.dumps(log_data, sort_keys=True)
        expected_hash = hashlib.sha256(combined.encode()).hexdigest()
        
        if expected_hash != log.hash_chain:
            verification_errors.append({
                "log_id": str(log.id),
                "timestamp": log.timestamp.isoformat(),
                "expected_hash": expected_hash,
                "actual_hash": log.hash_chain
            })
        
        previous_hash = log.hash_chain
    
    return {
        "verified": len(verification_errors) == 0,
        "total_logs": len(logs),
        "errors": verification_errors,
        "message": "Hash chain verified successfully" if len(verification_errors) == 0 else f"Found {len(verification_errors)} hash chain violations"
    }


@router.get("/actions", summary="List available audit actions", description="Retrieve a list of all unique audit actions recorded in the system. Admin access required.")
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


@router.get("/summary", summary="Audit log summary", description="Get a summary of audit log statistics by action and time period. Admin access required.")
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

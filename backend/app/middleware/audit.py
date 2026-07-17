"""Security Audit Logging Middleware

Automatically logs sensitive operations to the audit_logs table with SHA-256 hash chaining
for tamper-evident audit trails.
"""

import json
import hashlib
from typing import Optional, Dict, Any
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, insert
import structlog

from app.db.database import AsyncSessionLocal

logger = structlog.get_logger()

# Sensitive operations that require audit logging.
# Keys use "{id}" for every path parameter because _normalize_path collapses all
# UUIDs to "{id}" before lookup — the templates must match that normalized form.
SENSITIVE_OPERATIONS = {
    # User operations
    "POST:/api/v1/auth/register": "user_created",
    "DELETE:/api/v1/auth/users/{id}": "user_deleted",
    "PUT:/api/v1/auth/users/{id}": "user_updated",

    # Asset operations
    "POST:/api/v1/assets/": "asset_created",
    "PUT:/api/v1/assets/{id}": "asset_updated",
    "DELETE:/api/v1/assets/{id}": "asset_deleted",

    # Command operations
    "POST:/api/v1/commands/submit": "command_executed",
    "POST:/api/v1/commands/{id}/cancel": "command_cancelled",

    # Registry operations
    "POST:/api/v1/registries/": "registry_item_created",
    "PUT:/api/v1/registries/{id}": "registry_item_updated",
    "DELETE:/api/v1/registries/{id}": "registry_item_deleted",

    # Kanban operations
    "POST:/api/v1/kanban/tasks/{id}/approve": "task_approved",
    "POST:/api/v1/kanban/tasks/{id}/reject": "task_rejected",
    "POST:/api/v1/kanban/tasks/{id}/assign": "task_assigned",

    # FS-111: newly-mounted subsystem control-plane mutations. Only the
    # destructive / admin control actions are audited — the high-frequency
    # compute endpoints (drift/detect, performance/prediction) are deliberately
    # NOT here, or they'd flood the trail. Historian and RUL expose no mutations.
    "POST:/api/v1/twin/optimize": "twin_optimization_run",
    "POST:/api/v1/model-monitoring/reset/{id}": "model_monitoring_reset",
    "POST:/api/v1/admin/query-performance/record-snapshot": "query_performance_snapshot_recorded",
    "POST:/api/v1/admin/query-performance/refresh-frequent-queries": "query_performance_refreshed",
    "POST:/api/v1/admin/query-performance/reset-stats": "query_performance_stats_reset",
}


class AuditLoggingMiddleware(BaseHTTPMiddleware):
    """Middleware for automatic audit logging of sensitive operations"""
    
    async def dispatch(self, request: Request, call_next):
        # Process the request
        response = await call_next(request)
        
        # Only log successful requests (2xx, 3xx)
        if response.status_code >= 400:
            return response
        
        # Check if this is a sensitive operation
        method = request.method
        path = request.url.path
        
        # Normalize path for matching (replace path parameters with {id})
        normalized_path = self._normalize_path(path)
        operation_key = f"{method}:{normalized_path}"
        
        if operation_key not in SENSITIVE_OPERATIONS:
            return response
        
        # Get user context from request state (set by auth dependency)
        user_id = getattr(request.state, "user_id", None)
        organization_id = getattr(request.state, "organization_id", None)
        
        if not user_id:
            # No user context, skip logging
            return response
        
        # Extract resource information
        resource_type, resource_id = self._extract_resource(normalized_path, request)
        
        # Get request body if available
        request_body = await self._get_request_body(request)
        
        # Get response body if available
        response_body = await self._get_response_body(response)
        
        # Create audit log entry
        audit_data = {
            "action": SENSITIVE_OPERATIONS[operation_key],
            "resource_type": resource_type,
            "resource_id": str(resource_id) if resource_id else None,
            "details": {
                "method": method,
                "path": path,
                "request_body": request_body,
                "response_status": response.status_code,
                "response_body": response_body,
            },
            "ip_address": request.client.host if request.client else None,
            "user_agent": request.headers.get("user-agent"),
        }
        
        # Log asynchronously (non-blocking)
        await self._log_audit_entry(
            user_id=user_id,
            organization_id=organization_id,
            audit_data=audit_data
        )
        
        return response
    
    def _normalize_path(self, path: str) -> str:
        """Normalize path by replacing resource identifiers with {id}"""
        import re
        # Replace UUID patterns with {id}
        path = re.sub(
            r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}',
            '{id}',
            path
        )
        # FS-111: some resource ids are free-form strings, not UUIDs (e.g. the
        # model_id on /model-monitoring/reset/{model_id}), so the UUID rule alone
        # wouldn't collapse them. Collapse the single segment following a known
        # single-resource action verb so those keys match their template.
        path = re.sub(r'(/reset)/[^/]+$', r'\1/{id}', path)
        return path
    
    def _extract_resource(self, path: str, request: Request) -> tuple:
        """Extract resource type and ID from path and request"""
        # Extract from path
        parts = path.strip("/").split("/")
        
        resource_type = None
        resource_id = None
        
        if "assets" in parts:
            resource_type = "asset"
            idx = parts.index("assets")
            if idx + 1 < len(parts):
                resource_id = parts[idx + 1]
        elif "commands" in parts:
            resource_type = "command"
            idx = parts.index("commands")
            if idx + 1 < len(parts):
                resource_id = parts[idx + 1]
        elif "registries" in parts:
            resource_type = "registry_item"
            idx = parts.index("registries")
            if idx + 1 < len(parts):
                resource_id = parts[idx + 1]
        elif "kanban" in parts and "tasks" in parts:
            resource_type = "kanban_task"
            idx = parts.index("tasks")
            if idx + 1 < len(parts):
                resource_id = parts[idx + 1]
        elif "auth" in parts and "users" in parts:
            resource_type = "user"
            idx = parts.index("users")
            if idx + 1 < len(parts):
                resource_id = parts[idx + 1]
        
        # Try to extract from request body if not in path
        if not resource_id and request.method in ["POST", "PUT"]:
            # This would need to be handled before body is consumed
            pass
        
        return resource_type, resource_id
    
    async def _get_request_body(self, request: Request) -> Optional[Dict]:
        """Get request body if available"""
        try:
            # Note: This requires the body to not have been consumed yet
            # In practice, you'd need to use a custom request wrapper
            return None
        except Exception:
            return None
    
    async def _get_response_body(self, response: Response) -> Optional[Dict]:
        """Get response body if available"""
        try:
            # Note: This requires the response body to not have been consumed yet
            # In practice, you'd need to use a custom response wrapper
            return None
        except Exception:
            return None
    
    async def _log_audit_entry(
        self,
        user_id: str,
        organization_id: Optional[str],
        audit_data: Dict[str, Any]
    ):
        """Log audit entry to database"""
        try:
            # Import here to avoid circular import
            from app.db.models import AuditLog
            
            async with AsyncSessionLocal() as session:
                # Insert audit log (hash chain is calculated by database trigger)
                await session.execute(
                    insert(AuditLog).values(
                        user_id=user_id,
                        organization_id=organization_id,
                        action=audit_data["action"],
                        resource_type=audit_data["resource_type"],
                        resource_id=audit_data["resource_id"],
                        details=audit_data["details"],
                        ip_address=audit_data["ip_address"],
                        user_agent=audit_data["user_agent"],
                    )
                )
                await session.commit()
                
                logger.info(
                    "audit_log_created",
                    action=audit_data["action"],
                    resource_type=audit_data["resource_type"],
                    resource_id=audit_data["resource_id"],
                    user_id=user_id,
                )
        except Exception as e:
            # Log error but don't fail the request
            logger.error(
                "audit_log_failed",
                error=str(e),
                action=audit_data["action"],
                user_id=user_id,
            )

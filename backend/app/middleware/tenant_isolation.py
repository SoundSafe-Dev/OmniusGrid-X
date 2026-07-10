"""Tenant-isolation dependency facade.

Tenant isolation is implemented as FastAPI dependencies rather than
global ASGI middleware. The canonical implementation remains in
``app.core.tenant``.
"""

from app.core.tenant import get_tenant_db, get_tenant_org_id

__all__ = ["get_tenant_org_id", "get_tenant_db"]

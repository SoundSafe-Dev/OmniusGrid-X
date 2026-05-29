"""Tenant Isolation Dependency.

Provides FastAPI dependencies that derive the request's tenant
(organization) scope from the authenticated user. This is the single
source of truth for which organization's data a request is allowed
to access — never trust client-supplied parameters.

Security rationale
------------------
Endpoints must NEVER trust a client-supplied ``organization_id`` (query
string, path, or request body). Doing so creates an Insecure Direct
Object Reference (IDOR) vulnerability where any authenticated user can
read or mutate any tenant's data simply by changing a UUID in the URL.

``get_tenant_org_id`` derives ``organization_id`` from the JWT's ``sub``
claim (via :func:`app.api.auth.get_current_active_user`), which is
signed by the backend and cannot be forged client-side.

Usage
-----
::

    from app.core.tenant import get_tenant_org_id

    @router.get("/assets")
    async def list_assets(
        org_id: UUID = Depends(get_tenant_org_id),
        db: AsyncSession = Depends(get_db),
    ):
        query = select(Asset).where(Asset.organization_id == org_id)
        ...

Notes
-----
This is the application-layer enforcement. A defense-in-depth follow-up
(Task 4) adds Postgres Row-Level Security policies so that even a query
that forgets ``where(organization_id == ...)`` cannot leak data across
tenants. Integration tests (Task 5) verify both layers.
"""

from uuid import UUID

import structlog
from fastapi import Depends, HTTPException, status
from sqlalchemy import text

from app.api.auth import get_current_active_user
from app.db.database import AsyncSessionLocal
from app.db.models import User

logger = structlog.get_logger()


async def get_tenant_org_id(
    current_user: User = Depends(get_current_active_user),
) -> UUID:
    """Return the authenticated user's ``organization_id``.

    Declare this as a ``Depends(get_tenant_org_id)`` parameter on any
    endpoint that returns or mutates tenant-scoped data, then use the
    returned UUID to scope every database query for that request.

    Returns:
        UUID: The authenticated user's organization identifier.

    Raises:
        HTTPException 403: The authenticated user has no
            ``organization_id`` assigned. This should be impossible in
            production (every user is created with an organization),
            but we fail closed rather than fail open. Emits a
            ``tenant_isolation_rejected`` log event for observability.
    """
    if current_user.organization_id is None:
        logger.warning(
            "tenant_isolation_rejected",
            reason="user_has_no_organization",
            user_id=str(current_user.id),
            user_email=current_user.email,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User is not associated with an organization",
        )
    return current_user.organization_id


async def get_tenant_db(
    org_id: UUID = Depends(get_tenant_org_id),
):
    """Yield a DB session pre-bound to the caller's tenant via Postgres RLS.

    Sets the per-transaction GUC ``app.current_org_id`` to the
    authenticated user's organization before any query runs. The RLS
    policies in migration ``011_tenant_isolation_rls.sql`` reference
    this GUC to filter rows. ``set_config(..., true)`` scopes the value
    to the current transaction so it cannot leak across requests
    sharing the underlying connection.

    Use this in place of ``get_db`` on any endpoint that returns or
    mutates tenant-scoped data. ``get_db`` remains available for
    system-level tasks (startup, background services) that need to
    operate across tenants.

    Lives here rather than in ``app.db.database`` to avoid an import
    cycle (``database`` -> ``tenant`` -> ``api.auth`` -> ``database``).

    The GUC is set at session (connection) scope rather than
    transaction-local: some endpoints commit mid-request and then issue
    further queries (e.g. ``create``/``update`` followed by ``refresh``),
    and a ``SET LOCAL`` value would be cleared by that commit, leaving the
    follow-up query without tenant context. To prevent context leaking to
    a later request that reuses the pooled connection, the value is reset
    in the ``finally`` block; the RLS policies treat the empty value as
    NULL (fail-closed) via ``NULLIF``.
    """
    async with AsyncSessionLocal() as session:
        try:
            await session.execute(
                text("SELECT set_config('app.current_org_id', :org_id, false)"),
                {"org_id": str(org_id)},
            )
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.execute(
                text("SELECT set_config('app.current_org_id', '', false)")
            )
            await session.commit()
            await session.close()

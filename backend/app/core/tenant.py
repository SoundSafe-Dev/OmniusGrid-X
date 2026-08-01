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

    from app.middleware.tenant_isolation import get_tenant_db, get_tenant_org_id

    @router.get("/assets")
    async def list_assets(
        org_id: UUID = Depends(get_tenant_org_id),
        db: AsyncSession = Depends(get_tenant_db),
    ):
        query = select(Asset).where(Asset.organization_id == org_id)
        ...

Notes
-----
This is the application-layer enforcement. Postgres Row-Level Security
provides defense in depth so that even a query that forgets
``where(organization_id == ...)`` cannot leak data across tenants.
Integration tests verify both layers.
"""

from contextlib import asynccontextmanager
from typing import AsyncIterator
from uuid import UUID

import structlog
from fastapi import Depends, HTTPException, status
from sqlalchemy import event, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

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

    Installs the transaction-local GUC ``app.current_org_id`` for the
    authenticated user's organization before every transaction. The RLS
    policies in migration ``011_tenant_isolation_rls.sql`` reference this GUC
    to filter rows. Reinstalling it at each transaction boundary supports
    handlers that commit and continue querying without leaking tenant context
    through a pooled connection.

    Use this in place of ``get_db`` on any endpoint that returns or mutates
    tenant-scoped data. ``get_db`` remains available for system-level tasks
    (startup, background services) that need to operate across tenants.

    Lives here rather than in ``app.db.database`` to avoid an import cycle
    (``database`` -> ``tenant`` -> ``api.auth`` -> ``database``).
    """
    async with tenant_session(org_id) as session:
        yield session


@asynccontextmanager
async def tenant_session(organization_id: UUID | str) -> AsyncIterator[AsyncSession]:
    """Open a session whose every transaction is scoped to one trusted tenant.

    This is the non-HTTP counterpart to :func:`get_tenant_db`. Background jobs
    and machine-authenticated routes must call it only after deriving the
    organization from a trusted credential or an already-authenticated user.

    The tenant GUC is transaction-local and installed by ``after_begin``. That
    distinction matters: endpoint and service code commits mid-session, and an
    ``AsyncSession`` may acquire a different pooled connection for the next
    transaction. Installing the GUC on every transaction keeps RLS active after
    those commits, while PostgreSQL clears the value automatically on
    commit/rollback so it cannot leak to the next pool borrower.
    """
    tenant_id = str(organization_id).strip()
    if not tenant_id:
        raise ValueError("organization_id is required for a tenant session")

    async with AsyncSessionLocal() as session:
        def _set_tenant_guc(
            _session: Session,
            _transaction: object,
            connection: Connection,
        ) -> None:
            # SQLite is used by focused unit tests and has no PostgreSQL GUCs.
            # Those code paths still need explicit organization predicates.
            if connection.dialect.name == "postgresql":
                connection.execute(
                    text(
                        "SELECT set_config("
                        "'app.current_org_id', :org_id, true)"
                    ),
                    {"org_id": tenant_id},
                )

        event.listen(session.sync_session, "after_begin", _set_tenant_guc)
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            event.remove(session.sync_session, "after_begin", _set_tenant_guc)
            await session.close()

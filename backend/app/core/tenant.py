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
from uuid import UUID

import structlog
from fastapi import Depends, HTTPException, status
from sqlalchemy import event, text

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


@asynccontextmanager
async def tenant_session(org_id: UUID, session_maker=None):
    """The tenant-bound session itself, separate from the FastAPI dependency.

    EXTRACTED SO THE TESTS CAN STOP REIMPLEMENTING IT. ``conftest`` has to point
    endpoints at the testcontainers engine, and did so with an override that
    hand-copied this function's body, under a comment reading *"Mirrors the
    production get_tenant_db."* It mirrored the bug as well as the behaviour —
    and being a copy, it could not do otherwise: the suite was exercising the
    duplicate, so the RLS-after-commit defect was invisible to every RLS test we
    had, and fixing production would not have reached them.

    Only the session maker differs between the two, so that is the only thing
    injected. Everything below runs identically in tests and in production.
    """
    # RESOLVED AT CALL TIME, from the one module that owns it. This read the module-global
    # `AsyncSessionLocal` captured by `from app.db.database import ...` at import — and the test
    # harness rebinds that name PER MODULE (conftest sweeps sys.modules for anything carrying
    # the attribute). When `app.core.tenant`'s copy is not among the rebound ones, this opened a
    # session against the placeholder DATABASE_URL and failed with `role "placeholder" does not
    # exist` — which is what happened the moment a SERVICE started calling this directly rather
    # than going through the `get_tenant_db` dependency the suite overrides wholesale.
    #
    # Looking the name up on the module removes the whole class: there is one binding that
    # matters and this reads it, rather than holding a copy that may or may not have been
    # patched.
    if session_maker is None:
        from app.db import database as _database

        session_maker = _database.AsyncSessionLocal
    async with session_maker() as session:
        # set_config/RLS are Postgres features; on other dialects (SQLite dev,
        # smoke tests) tenant scoping falls back to the endpoints' explicit
        # organization_id filters, so skip the GUC round-trips entirely.
        is_postgres = session.bind.dialect.name == "postgresql"

        def _bind_tenant(_session, _transaction, connection):
            """Re-assert the tenant on whatever connection this transaction got."""
            connection.execute(
                text("SELECT set_config('app.current_org_id', :org_id, true)"),
                {"org_id": str(org_id)},
            )

        if is_postgres:
            event.listen(session.sync_session, "after_begin", _bind_tenant)
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            if is_postgres:
                # Explicitly detached: the listener closes over org_id, so leaving
                # it attached to a session that outlived the request would bind the
                # wrong tenant.
                event.remove(session.sync_session, "after_begin", _bind_tenant)
            await session.close()


async def get_tenant_db(
    org_id: UUID = Depends(get_tenant_org_id),
):
    """Yield a DB session pre-bound to the caller's tenant via Postgres RLS.

    Sets the session-scoped GUC ``app.current_org_id`` to the authenticated
    user's organization before any query runs. The RLS policies in migration
    ``011_tenant_isolation_rls.sql`` reference this GUC to filter rows.

    The GUC is set from an ``after_begin`` hook, so it is re-established at the
    start of EVERY transaction on this session rather than once at the top of
    the request. That is what makes a mid-request ``commit()`` safe: commit ends
    the transaction and returns the connection to the pool, and the next query
    may land on a different connection entirely. Setting it once could not
    survive that, and did not — see the note below.

    Because the hook re-runs per transaction, the value is written
    transaction-locally (``set_config(..., true)``). It therefore cannot outlive
    the transaction and cannot leak onto a pooled connection, which removes the
    need to scrub it afterwards. RLS policies treat an unset value as NULL
    (fail-closed) via ``NULLIF``.

    Use this in place of ``get_db`` on any endpoint that returns or mutates
    tenant-scoped data. ``get_db`` remains available for system-level tasks
    (startup, background services) that need to operate across tenants.

    Lives here rather than in ``app.db.database`` to avoid an import cycle
    (``database`` -> ``tenant`` -> ``api.auth`` -> ``database``).
    """
    # WHY A PER-TRANSACTION HOOK AND NOT A SINGLE set_config AT THE TOP.
    #
    # It used to be one `set_config(..., false)` before the yield, on the
    # reasoning that a session-scoped value would survive an endpoint that
    # commits mid-request. It does not. commit() ends the transaction AND
    # returns the connection to the pool; the next statement checks out a
    # connection that was never configured, so `app.current_org_id` reads as
    # empty and every RLS policy fails closed.
    #
    # The endpoint then sees zero rows for data it just wrote. `create_rollout`
    # in `api/agent_rollouts.py` did exactly this: it committed, re-read the
    # rollout it had created, and returned 404 for a row that was there.
    #
    # An earlier fix took this to be a `db.refresh()`-specific problem and
    # removed twenty refresh-after-commit calls. That was worth doing —
    # expire_on_commit=False makes them redundant anyway — but it treated one
    # symptom: ANY query after a mid-request commit was affected, not just a
    # refresh. Binding to `after_begin` fixes the cause, so the ban below is no
    # longer load-bearing, only still-good practice.
    #
    # The body lives in `tenant_session` so the test harness can point it at the
    # testcontainers engine without copying it. See that function.
    async with tenant_session(org_id) as session:
        yield session

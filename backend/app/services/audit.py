"""Shared writer for the security audit trail (FS-225).

WHY A SHARED HELPER. Two services already carried their own private ``_audit``
method — ``bulk_processor.BulkProcessor._audit`` and
``FeatureFlagService._audit`` — each with its own copy of the same raw INSERT.
A third copy for user management would have made the duplication a pattern, and
the duplication is not harmless: the ``ip_address`` column type mismatch
documented on ``AuditLog`` (declared VARCHAR, created as INET) silently swallowed
every write on real deployments, and finding that required checking each copy.

NON-FATAL BY DESIGN, LOUD IN THE LOG. An audit write must not fail the operation
it describes: refusing to deactivate a compromised account because the audit table
is unavailable is the wrong trade. When the write shares the caller's transaction
that requires a SAVEPOINT — in Postgres a failed statement aborts the whole
transaction, so a bare execute would roll back the very change being audited.

But a swallowed failure is exactly how the trail was silently empty before, so
failures log at ERROR with the action name, not DEBUG.

``hash_chain`` is populated by ``audit_log_hash_chain_trigger`` (migration 009),
which is why it is absent from the column list below.
"""

from __future__ import annotations

from typing import Any, Optional

import json

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger()


async def record_audit(
    *,
    action: str,
    resource_type: str,
    resource_id: Optional[Any] = None,
    actor_id: Optional[Any] = None,
    organization_id: Optional[Any] = None,
    details: Optional[dict] = None,
    session: Optional[AsyncSession] = None,
) -> bool:
    """Write one audit row. Returns whether it landed.

    Pass ``session`` to enlist in the caller's transaction, so the audit row and
    the change it describes commit together — for a role change that atomicity is
    the point, since an audit trail that can disagree with the data is worse than
    none. Omit it and the row is written in its own short-lived session, which is
    what background paths want.
    """
    payload = {
        "user_id": str(actor_id) if actor_id else None,
        "organization_id": str(organization_id) if organization_id else None,
        "action": action,
        "resource_type": resource_type,
        "resource_id": str(resource_id) if resource_id else None,
        # Bound as a JSON string: the column is JSON/JSONB and asyncpg will not
        # adapt a bare dict through a text() construct.
        "details": json.dumps(details or {}),
    }
    statement = text(
        """
        INSERT INTO audit_logs
            (user_id, organization_id, action, resource_type, resource_id, details)
        VALUES
            (:user_id, :organization_id, :action, :resource_type, :resource_id,
             CAST(:details AS json))
        """
    )

    try:
        if session is not None:
            # SAVEPOINT, not a bare execute. In Postgres a failed statement aborts
            # the ENTIRE transaction, so a rejected audit INSERT would roll back the
            # very change it was describing — "non-fatal" would have been a lie for
            # the in-session path. begin_nested() confines the failure to the audit
            # row. (Found by wiring this up: audit_logs is RLS-protected, the insert
            # was rejected, and it took nine unrelated assertions down with it.)
            async with session.begin_nested():
                await session.execute(statement, payload)
        else:
            from app.db.database import AsyncSessionLocal

            async with AsyncSessionLocal() as own_session:
                # The in-session branch above inherits the caller's GUC from
                # get_tenant_db. This branch has no caller session and therefore no
                # tenant context, and `audit_logs` is ENABLE + FORCE ROW LEVEL SECURITY
                # — FORCE meaning the policy binds the table owner too — so the INSERT
                # is rejected and the `except` below turns that into `return False`.
                # Every standalone audit write was silently lost.
                #
                # is_local=true, transaction-scoped: nothing here resets a session-scoped
                # value before the connection goes back to the pool.
                if organization_id and own_session.bind.dialect.name == "postgresql":
                    await own_session.execute(
                        text("SELECT set_config('app.current_org_id', :org, true)"),
                        {"org": str(organization_id)},
                    )
                await own_session.execute(statement, payload)
                await own_session.commit()
        return True
    except Exception as exc:  # noqa: BLE001 — never fail the audited operation
        # ERROR, not DEBUG: a silently empty audit trail is the failure mode this
        # helper exists to make visible.
        logger.error(
            "audit_log_write_failed",
            action=action,
            resource_type=resource_type,
            resource_id=str(resource_id) if resource_id else None,
            error=str(exc),
        )
        return False

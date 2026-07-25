"""Alarm rule CRUD (FS-218).

Operators define thresholds here; app/services/alarm_rules.py evaluates them
against incoming telemetry in the ingestion path (FS-219).

TENANCY. `alarm_rules` carries `organization_id` with FORCE ROW LEVEL SECURITY
from its first migration (047), so RLS scopes every query even if a predicate is
forgotten. The explicit `organization_id ==` filters below are belt-and-braces —
they also keep the endpoints correct on SQLite, where RLS is a no-op and the
offline demo path would otherwise be unscoped.

Writes require operator-or-admin. Reads only require an authenticated user,
matching the alarms router: seeing which thresholds are configured is part of
understanding an alarm you have been paged about.
"""

from typing import Optional
from uuid import UUID
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from types import SimpleNamespace
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_active_user
from app.core.pagination import PaginatedResponse, paginate
from app.core.tenant import get_tenant_db, get_tenant_org_id
from app.db.models import AlarmRule, Asset, AssetType, User, Workcell
from app.middleware.rbac import require_operator_or_admin
from app.models.schemas import (
    AlarmRuleCreate,
    AlarmRuleResponse,
    AlarmRuleUpdate,
)

router = APIRouter(dependencies=[Depends(get_current_active_user)])


async def _validate_targets(
    db: AsyncSession, org_id: UUID, rule: AlarmRuleCreate | AlarmRuleUpdate
) -> None:
    """Reject targets that belong to another organization.

    Without this a rule could reference another tenant's asset id. RLS would stop
    the *rule row* from being read cross-tenant, but the FK would still resolve
    and the stored reference would be wrong — the same shape as the kanban
    `alarm_id` hole found in FS-216, where an unvalidated foreign id became a
    cross-tenant write. 404 rather than 403 so target existence is not leaked.
    """
    checks = (
        (rule.asset_id, Asset, "asset"),
        (rule.workcell_id, Workcell, "workcell"),
    )
    for target_id, model, label in checks:
        if target_id is None:
            continue
        found = (
            await db.execute(
                select(model.id).where(
                    model.id == target_id, model.organization_id == org_id
                )
            )
        ).first()
        if not found:
            raise HTTPException(status_code=404, detail=f"Unknown {label}")

    # asset_types is a GLOBAL table (no organization_id — see the seeding helper
    # in tests/test_tenant_isolation_api.py), so it is checked for existence only.
    if rule.asset_type_id is not None:
        found = (
            await db.execute(
                select(AssetType.id).where(AssetType.id == rule.asset_type_id)
            )
        ).first()
        if not found:
            raise HTTPException(status_code=404, detail="Unknown asset_type")


@router.get(
    "/",
    response_model=PaginatedResponse[AlarmRuleResponse],
    summary="List alarm rules",
    description="Paginated list of the organization's alarm rules, newest first. Filter by metric, severity or enabled state.",
)
async def list_alarm_rules(
    metric_name: Optional[str] = None,
    severity: Optional[str] = None,
    is_enabled: Optional[bool] = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    org_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    query = select(AlarmRule).where(AlarmRule.organization_id == org_id)

    if metric_name:
        query = query.where(AlarmRule.metric_name == metric_name)
    if severity:
        query = query.where(AlarmRule.severity == severity)
    if is_enabled is not None:
        query = query.where(AlarmRule.is_enabled == is_enabled)

    total = (
        await db.execute(select(func.count()).select_from(query.subquery()))
    ).scalar_one()
    query = query.order_by(AlarmRule.created_at.desc()).offset(skip).limit(limit)
    result = await db.execute(query)
    return paginate(
        result.scalars().all(), total, SimpleNamespace(skip=skip, limit=limit)
    )


@router.get(
    "/{rule_id}",
    response_model=AlarmRuleResponse,
    summary="Get an alarm rule",
    description="Retrieve a single alarm rule by id.",
)
async def get_alarm_rule(
    rule_id: UUID,
    org_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    rule = (
        await db.execute(
            select(AlarmRule).where(
                AlarmRule.id == rule_id, AlarmRule.organization_id == org_id
            )
        )
    ).scalars().first()
    if not rule:
        raise HTTPException(status_code=404, detail="Alarm rule not found")
    return rule


@router.post(
    "/",
    response_model=AlarmRuleResponse,
    status_code=201,
    summary="Create an alarm rule",
    description="Define a threshold rule evaluated against incoming telemetry. duration_seconds requires the breach to persist before an alarm is raised.",
    dependencies=[Depends(require_operator_or_admin)],
)
async def create_alarm_rule(
    payload: AlarmRuleCreate,
    org_id: UUID = Depends(get_tenant_org_id),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_tenant_db),
):
    await _validate_targets(db, org_id, payload)

    rule = AlarmRule(
        # Server-side, never from the payload — the schema has no organization_id
        # field at all so a client cannot even attempt to set it.
        organization_id=org_id,
        created_by=current_user.id,
        **payload.model_dump(),
    )
    db.add(rule)
    await db.commit()
    # No db.refresh() after commit — see the warning in app/core/tenant.py. With
    # FORCE RLS on this table the refresh can land on a pooled connection that
    # never had app.current_org_id set and the row would appear to vanish.
    return rule


@router.patch(
    "/{rule_id}",
    response_model=AlarmRuleResponse,
    summary="Update an alarm rule",
    description="Partial update. Omitted fields are left unchanged.",
    dependencies=[Depends(require_operator_or_admin)],
)
async def update_alarm_rule(
    rule_id: UUID,
    payload: AlarmRuleUpdate,
    org_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    rule = (
        await db.execute(
            select(AlarmRule).where(
                AlarmRule.id == rule_id, AlarmRule.organization_id == org_id
            )
        )
    ).scalars().first()
    if not rule:
        raise HTTPException(status_code=404, detail="Alarm rule not found")

    await _validate_targets(db, org_id, payload)

    # exclude_unset so an omitted field is left alone rather than reset to its
    # default — the reason AlarmRuleUpdate is a separate schema.
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(rule, field, value)
    rule.updated_at = datetime.now(timezone.utc)

    await db.commit()
    return rule


@router.delete(
    "/{rule_id}",
    status_code=204,
    summary="Delete an alarm rule",
    description="Permanently remove a rule. Alarms it already raised are unaffected.",
    dependencies=[Depends(require_operator_or_admin)],
)
async def delete_alarm_rule(
    rule_id: UUID,
    org_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    rule = (
        await db.execute(
            select(AlarmRule).where(
                AlarmRule.id == rule_id, AlarmRule.organization_id == org_id
            )
        )
    ).scalars().first()
    if not rule:
        raise HTTPException(status_code=404, detail="Alarm rule not found")

    # Hard delete is correct here: a rule is configuration, not a record of
    # something that happened. Alarms it already raised are separate rows and
    # survive — they carry alarm_code, not a rule FK, precisely so that history
    # does not disappear when an operator retires a threshold.
    await db.delete(rule)
    await db.commit()
    return None

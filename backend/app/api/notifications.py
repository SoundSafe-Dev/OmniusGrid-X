"""API routes for the Notifications & delivery center."""

from uuid import UUID
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select, delete

from app.db.database import AsyncSessionLocal
from app.db.notification_models import NotificationSubscription, NotificationDelivery
from app.api.auth import get_current_active_user
from app.core.tenant import get_tenant_org_id, tenant_session
from app.services.notifications import notification_service

router = APIRouter()


class SubscriptionCreate(BaseModel):
    name: str
    channel: str = Field(..., pattern="^(webhook|slack|email)$")
    target: str
    min_severity: str = Field(default="warning", pattern="^(info|warning|error|critical)$")
    domain: Optional[str] = None
    asset_id: Optional[str] = None
    enabled: bool = True


class TestEvent(BaseModel):
    severity: str = "warning"
    title: str = "Test notification"
    message: str = "This is a test."
    domain: Optional[str] = None
    asset_id: Optional[str] = None


# `_org` IS GONE. It was `getattr(current_user, "organization_id", None)`, and every caller
# then wrote `if org is not None: stmt = stmt.where(...)` — so a user whose organisation was
# NULL had the tenant filter SKIPPED and saw every organisation's rows. Absence read as
# unrestricted access, which is the opposite of what this codebase's own tenant dependency
# does: `get_tenant_org_id` raises 403 for exactly that case and documents why — "we fail
# closed rather than fail open".
#
# At the time the tables had no row-level security either, so the conditional filter was the
# only thing standing between tenants. Migration 056 policied both, in the order migration 051
# insists on: this file's handlers were moved onto `tenant_session` FIRST, because a FORCEd
# policy over unbound sessions would have emptied every read rather than protecting it.


@router.post("/subscriptions")
async def create_subscription(
    body: SubscriptionCreate,
    organization_id=Depends(get_tenant_org_id),
):
    sub = NotificationSubscription(organization_id=str(organization_id), **body.model_dump())
    async with tenant_session(organization_id) as session:
        # `tenant_session`, NOT `AsyncSessionLocal`. These handlers opened their own
        # unbound session and relied entirely on the explicit organisation filter — and
        # `notification_subscriptions` / `notification_deliveries` had no policy either,
        # so that filter was the only thing separating tenants. Binding the GUC is what
        # lets migration 056 add the second layer; the shared helper re-asserts it on
        # every transaction, which is the part a hand-rolled `set_config` gets wrong.
        session.add(sub)
        await session.commit()
        await session.refresh(sub)
    return {"id": str(sub.id), "name": sub.name, "channel": sub.channel}


@router.get("/subscriptions")
async def list_subscriptions(
    organization_id=Depends(get_tenant_org_id),
) -> List[Dict[str, Any]]:
    async with tenant_session(organization_id) as session:
        # UNCONDITIONAL. The `if org is not None` that used to wrap this returned every
        # tenant's subscriptions for a user with no organisation.
        stmt = select(NotificationSubscription).where(
            NotificationSubscription.organization_id == str(organization_id)
        )
        rows = (await session.execute(stmt)).scalars().all()
    return [{"id": str(r.id), "name": r.name, "channel": r.channel, "target": r.target,
             "min_severity": r.min_severity, "domain": r.domain, "asset_id": r.asset_id,
             "enabled": r.enabled} for r in rows]


@router.delete("/subscriptions/{subscription_id}")
async def delete_subscription(
    subscription_id: UUID,
    organization_id=Depends(get_tenant_org_id),
):
    async with tenant_session(organization_id) as session:
        # SCOPED BY ORGANISATION AS WELL AS ID. This deleted on `id` alone, so any
        # authenticated user could delete any other tenant's notification subscription by
        # guessing or leaking its id — a cross-tenant destructive write, on a table with no
        # row-level security to fall back on. The rowcount check already existed and was
        # measuring the wrong thing: it proved a row was deleted, not that it was yours.
        result = await session.execute(
            delete(NotificationSubscription).where(
                NotificationSubscription.id == subscription_id,
                NotificationSubscription.organization_id == str(organization_id),
            )
        )
        await session.commit()
    if result.rowcount == 0:
        # 404, not 403: whether the row exists is itself tenant information, and answering
        # "it exists but is not yours" tells a caller that a given id is live in another
        # organisation.
        raise HTTPException(status_code=404, detail="subscription not found")
    return {"deleted": subscription_id}


@router.post("/test")
async def send_test(body: TestEvent, organization_id=Depends(get_tenant_org_id)):
    """Dispatch a test event through matching subscriptions."""
    event = body.model_dump()
    results = await notification_service.dispatch(event, organization_id=str(organization_id))
    return {"matched": len(results), "results": results}


@router.get("/log")
async def delivery_log(limit: int = Query(default=100, ge=1, le=1000),
                       organization_id=Depends(get_tenant_org_id)) -> List[Dict[str, Any]]:
    async with tenant_session(organization_id) as session:
        # UNCONDITIONAL, like the subscription list. The delivery log carries alarm titles and
        # detail strings from whatever fired the notification, so an unfiltered read hands one
        # tenant another tenant's alarm text — which is the most specific operational
        # information in this system.
        stmt = (
            select(NotificationDelivery)
            .where(NotificationDelivery.organization_id == str(organization_id))
            .order_by(NotificationDelivery.created_at.desc())
        )
        rows = (await session.execute(stmt.limit(limit))).scalars().all()
    return [{"id": str(r.id), "channel": r.channel, "severity": r.severity, "title": r.title,
             "delivered": r.delivered, "detail": r.detail,
             "created_at": r.created_at.isoformat() if r.created_at else None} for r in rows]

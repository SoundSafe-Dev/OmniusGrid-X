"""API routes for the Notifications & delivery center."""

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select, delete

from app.db.database import AsyncSessionLocal
from app.db.notification_models import NotificationSubscription, NotificationDelivery
from app.api.auth import get_current_active_user
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


def _org(current_user) -> Optional[str]:
    return getattr(current_user, "organization_id", None)


@router.post("/subscriptions")
async def create_subscription(body: SubscriptionCreate, current_user=Depends(get_current_active_user)):
    sub = NotificationSubscription(organization_id=_org(current_user), **body.model_dump())
    async with AsyncSessionLocal() as session:
        session.add(sub)
        await session.commit()
        await session.refresh(sub)
    return {"id": str(sub.id), "name": sub.name, "channel": sub.channel}


@router.get("/subscriptions")
async def list_subscriptions(current_user=Depends(get_current_active_user)) -> List[Dict[str, Any]]:
    org = _org(current_user)
    async with AsyncSessionLocal() as session:
        stmt = select(NotificationSubscription)
        if org is not None:
            stmt = stmt.where(NotificationSubscription.organization_id == org)
        rows = (await session.execute(stmt)).scalars().all()
    return [{"id": str(r.id), "name": r.name, "channel": r.channel, "target": r.target,
             "min_severity": r.min_severity, "domain": r.domain, "asset_id": r.asset_id,
             "enabled": r.enabled} for r in rows]


@router.delete("/subscriptions/{subscription_id}")
async def delete_subscription(subscription_id: str, current_user=Depends(get_current_active_user)):
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            delete(NotificationSubscription).where(NotificationSubscription.id == subscription_id)
        )
        await session.commit()
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="subscription not found")
    return {"deleted": subscription_id}


@router.post("/test")
async def send_test(body: TestEvent, current_user=Depends(get_current_active_user)):
    """Dispatch a test event through matching subscriptions."""
    event = body.model_dump()
    results = await notification_service.dispatch(event, organization_id=_org(current_user))
    return {"matched": len(results), "results": results}


@router.get("/log")
async def delivery_log(limit: int = Query(default=100, ge=1, le=1000),
                       current_user=Depends(get_current_active_user)) -> List[Dict[str, Any]]:
    org = _org(current_user)
    async with AsyncSessionLocal() as session:
        stmt = select(NotificationDelivery).order_by(NotificationDelivery.created_at.desc())
        if org is not None:
            stmt = stmt.where(NotificationDelivery.organization_id == org)
        rows = (await session.execute(stmt.limit(limit))).scalars().all()
    return [{"id": str(r.id), "channel": r.channel, "severity": r.severity, "title": r.title,
             "delivered": r.delivered, "detail": r.detail,
             "created_at": r.created_at.isoformat() if r.created_at else None} for r in rows]

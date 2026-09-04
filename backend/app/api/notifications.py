"""API routes for the Notifications & delivery center."""

from uuid import UUID
from typing import Any, Dict, List, Optional

from app.core.pagination import MAX_OFFSET, mark_truncated
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import select, delete

from app.db.database import AsyncSessionLocal
from app.db.models import Asset
from app.db.notification_models import NotificationSubscription, NotificationDelivery
from app.api.auth import get_current_active_user
from app.core.tenant import get_tenant_org_id, tenant_session
from app.services.notifications import notification_service

router = APIRouter()


class SubscriptionResponse(BaseModel):
    """One row of `GET /subscriptions`.

    snake_case on the wire — the frontend client registers `/api/v1/notifications`
    with the casing seam, so `min_severity` reaches TypeScript as `minSeverity`.
    Renaming here would break that transform, not fix it.
    """

    id: str
    name: str
    channel: str
    target: str
    min_severity: str
    domain: Optional[str] = None
    asset_id: Optional[str] = None
    enabled: bool


class SubscriptionCreated(BaseModel):
    """`POST /subscriptions` deliberately echoes three fields, not the whole row —
    the client's `SubscriptionCreated` reads exactly these and refetches the list."""

    id: str
    name: str
    channel: str


class SubscriptionDeleted(BaseModel):
    #: UUID, not str. The handler returns the raw path parameter — which FastAPI
    #: parsed into a `UUID` — and pydantic v2 does NOT coerce UUID to str: typing
    #: this `str` turns every successful delete into a 500 at response-validation
    #: time, on a route that worked before the model was attached. UUID serialises
    #: to the same JSON string, so the wire format is unchanged.
    deleted: UUID


class TestDispatchResult(BaseModel):
    """`results` is whatever `notification_service.dispatch` returned per matched
    subscription; its shape is the service's, so it is passed through untyped
    rather than guessed at here."""

    matched: int
    results: List[Dict[str, Any]]


class DeliveryLogEntry(BaseModel):
    id: str
    channel: str
    severity: str
    title: str
    delivered: bool
    detail: Optional[str] = None
    created_at: Optional[str] = None


class SubscriptionCreate(BaseModel):
    name: str
    channel: str = Field(..., pattern="^(webhook|slack|email)$")
    target: str
    min_severity: str = Field(default="warning", pattern="^(info|warning|error|critical)$")
    domain: Optional[str] = None
    #: `UUID`, not `str` (FS-726). As a string, `{"asset_id": "nope"}` reached Postgres and
    #: came back a 500; and nothing checked whose asset it was, so a subscription could be
    #: scoped to ANOTHER organisation's machine — accepted with a 200, and then silently
    #: dead, because the alarms it would match are ones this tenant can never see.
    asset_id: Optional[UUID] = None
    enabled: bool = True


class SubscriptionUpdate(BaseModel):
    """Every field optional — a PATCH that required the whole row would make a toggle
    into a form (P11, page-enhancement review).

    Same closed sets as `SubscriptionCreate`: a channel or severity this server does not
    dispatch must be refused on the way in, not discovered when an alert goes nowhere.
    """

    name: Optional[str] = None
    channel: Optional[str] = Field(default=None, pattern="^(webhook|slack|email)$")
    target: Optional[str] = None
    min_severity: Optional[str] = Field(
        default=None, pattern="^(info|warning|error|critical)$"
    )
    domain: Optional[str] = None
    asset_id: Optional[UUID] = None
    enabled: Optional[bool] = None


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


async def _own_asset_id(session, asset_id: Optional[UUID]) -> Optional[str]:
    """The asset id as a string, having proved the caller can see the asset.

    A subscription scoped to another organisation's asset is accepted by the database — the
    foreign key is checked below RLS — and is then permanently silent, because the alarms it
    filters for belong to a tenant this subscriber cannot see. A rule that can never fire is
    worse than no rule: the operator believes they are covered.

    Same shape as `shop_floor._own_asset_id` and `operations._own_operation`. Three files,
    one question — what proves this id belongs to the caller.
    """
    if asset_id is None:
        return None
    found = (
        await session.execute(select(Asset.id).where(Asset.id == asset_id))
    ).scalar_one_or_none()
    if found is None:
        raise HTTPException(status_code=404, detail=f"asset {asset_id} not found")
    return str(asset_id)


@router.post("/subscriptions", response_model=SubscriptionCreated)
async def create_subscription(
    body: SubscriptionCreate,
    organization_id=Depends(get_tenant_org_id),
):
    async with tenant_session(organization_id) as session:
        fields = body.model_dump()
        fields["asset_id"] = await _own_asset_id(session, body.asset_id)
        sub = NotificationSubscription(organization_id=str(organization_id), **fields)
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


@router.get("/subscriptions", response_model=List[SubscriptionResponse])
async def list_subscriptions(
    response: Response,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0, le=MAX_OFFSET),
    organization_id=Depends(get_tenant_org_id),
) -> List[Dict[str, Any]]:
    async with tenant_session(organization_id) as session:
        # UNCONDITIONAL. The `if org is not None` that used to wrap this returned every
        # tenant's subscriptions for a user with no organisation.
        stmt = (
            select(NotificationSubscription)
            .where(NotificationSubscription.organization_id == str(organization_id))
            .order_by(NotificationSubscription.id)
            .offset(offset)
            .limit(limit + 1)
        )
        rows = (await session.execute(stmt)).scalars().all()
    rows = mark_truncated(response, rows, limit)
    return [{"id": str(r.id), "name": r.name, "channel": r.channel, "target": r.target,
             "min_severity": r.min_severity, "domain": r.domain, "asset_id": r.asset_id,
             "enabled": r.enabled} for r in rows]


@router.patch("/subscriptions/{subscription_id}", response_model=SubscriptionResponse)
async def update_subscription(
    subscription_id: UUID,
    payload: SubscriptionUpdate,
    organization_id=Depends(get_tenant_org_id),
):
    """Edit a subscription, or just flip it off (P11, page-enhancement review).

    There was no update route at all: a wrong URL or severity meant delete-and-recreate,
    and the `enabled` column — which the list has always returned and the UI has always
    shown as a badge — could be written once at creation and never again. So the one
    action an operator most wants during an incident, *stop paging this channel*, meant
    destroying the subscription and rebuilding it afterwards from memory.

    SCOPED BY ORGANISATION AS WELL AS ID, for the reason the delete below documents: an
    update on `id` alone would let any authenticated user retarget another tenant's
    subscription — the same cross-tenant write, pointed at a webhook URL of their
    choosing, which is worse than deletion.
    """
    fields = payload.model_dump(exclude_unset=True)
    async with tenant_session(organization_id) as session:
        # The SAME ownership check the create does. A PATCH can move a subscription onto a
        # different asset, so it can move it onto another organisation's asset — the create
        # being fixed alone would leave the second door open, and this route is newer than
        # the defect it would have reintroduced.
        if "asset_id" in fields:
            fields["asset_id"] = await _own_asset_id(session, payload.asset_id)
        subscription = (
            await session.execute(
                select(NotificationSubscription).where(
                    NotificationSubscription.id == subscription_id,
                    NotificationSubscription.organization_id == str(organization_id),
                )
            )
        ).scalar_one_or_none()
        # 404 rather than 403, matching delete: whether the row exists is itself tenant
        # information.
        if subscription is None:
            raise HTTPException(status_code=404, detail="subscription not found")
        for key, value in fields.items():
            setattr(subscription, key, value)
        await session.commit()
        await session.refresh(subscription)
        return {
            "id": str(subscription.id),
            "name": subscription.name,
            "channel": subscription.channel,
            "target": subscription.target,
            "min_severity": subscription.min_severity,
            "domain": subscription.domain,
            "asset_id": subscription.asset_id,
            "enabled": subscription.enabled,
        }


@router.delete("/subscriptions/{subscription_id}", response_model=SubscriptionDeleted)
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


@router.post("/test", response_model=TestDispatchResult)
async def send_test(body: TestEvent, organization_id=Depends(get_tenant_org_id)):
    """Dispatch a test event through matching subscriptions."""
    event = body.model_dump()
    results = await notification_service.dispatch(event, organization_id=str(organization_id))
    return {"matched": len(results), "results": results}


@router.get("/log", response_model=List[DeliveryLogEntry])
async def delivery_log(response: Response,
                       limit: int = Query(default=100, ge=1, le=1000),
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
        rows = (await session.execute(stmt.limit(limit + 1))).scalars().all()
        # SAYS WHEN IT CAPPED (FS-455): a bare array of exactly `limit` rows is
        # indistinguishable from the complete set.
        rows = mark_truncated(response, rows, limit)
    return [{"id": str(r.id), "channel": r.channel, "severity": r.severity, "title": r.title,
             "delivered": r.delivered, "detail": r.detail,
             "created_at": r.created_at.isoformat() if r.created_at else None} for r in rows]

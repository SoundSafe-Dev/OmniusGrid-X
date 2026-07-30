"""
GeoTab Integration API Endpoints
Fleet telematics, HOS compliance, vehicle diagnostics
"""

import hmac
from datetime import datetime, timedelta, timezone
from typing import List, Optional
from uuid import UUID
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_active_user
from app.core.config import settings
from app.db.database import get_db
from app.middleware.tenant_isolation import get_tenant_db, get_tenant_org_id
from app.services.geotab_service import geotab_service

# Read/query endpoints require an authenticated user.
router = APIRouter(prefix="/geotab", tags=["geotab"],
                   dependencies=[Depends(get_current_active_user)])


async def verify_geotab_webhook(x_webhook_secret: Optional[str] = Header(None)):
    """Guard the external webhook with a shared secret (no user JWT available)."""
    expected = settings.GEOTAB_WEBHOOK_SECRET
    if expected and not hmac.compare_digest(x_webhook_secret or "", expected):
        raise HTTPException(status_code=401, detail="Invalid webhook secret")


# Webhook is an external callback: secret-guarded, not user-authenticated.
webhook_router = APIRouter(prefix="/geotab", tags=["geotab"],
                           dependencies=[Depends(verify_geotab_webhook)])


@router.get("/devices")
async def get_geotab_devices(
    organization_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db)
):
    """List GeoTab devices (drivers' ELD assignments + device registry)"""
    # ORG FROM THE TOKEN, SESSION FROM get_tenant_db. This took `organization_id` as a
    # client-supplied query parameter and ran on `get_db`, which binds no tenant GUC —
    # so on the RLS-protected tables the service queries, the policy filtered every row
    # and the endpoint returned nothing to anyone, including for its own organisation.
    # The same pair of mistakes was fixed on `get_fleet_summary` in this file and on five
    # transportation handlers; these six were missed because their queries live in the
    # SERVICE, so the get_db guard — which inspects handler bodies for RLS models —
    # cannot see them.
    return await geotab_service.get_devices(
        organization_id=organization_id,
        db=db
    )


@router.get("/devices/{device_id}/location")
async def get_device_location(
    device_id: str,
    organization_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db)
):
    """Latest known position for a GeoTab device"""
    # ORG FROM THE TOKEN, SESSION FROM get_tenant_db. This took `organization_id` as a
    # client-supplied query parameter and ran on `get_db`, which binds no tenant GUC —
    # so on the RLS-protected tables the service queries, the policy filtered every row
    # and the endpoint returned nothing to anyone, including for its own organisation.
    # The same pair of mistakes was fixed on `get_fleet_summary` in this file and on five
    # transportation handlers; these six were missed because their queries live in the
    # SERVICE, so the get_db guard — which inspects handler bodies for RLS models —
    # cannot see them.
    try:
        return await geotab_service.get_device_location(
            device_id=device_id,
            organization_id=organization_id,
            db=db
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/devices/{device_id}/trips")
async def get_device_trips(
    device_id: str,
    from_time: Optional[datetime] = Query(None, alias="from"),
    to_time: Optional[datetime] = Query(None, alias="to"),
    organization_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db)
):
    """Trips for a GeoTab device within a time window (default: last 24h)"""
    # ORG FROM THE TOKEN, SESSION FROM get_tenant_db. This took `organization_id` as a
    # client-supplied query parameter and ran on `get_db`, which binds no tenant GUC —
    # so on the RLS-protected tables the service queries, the policy filtered every row
    # and the endpoint returned nothing to anyone, including for its own organisation.
    # The same pair of mistakes was fixed on `get_fleet_summary` in this file and on five
    # transportation handlers; these six were missed because their queries live in the
    # SERVICE, so the get_db guard — which inspects handler bodies for RLS models —
    # cannot see them.
    now = datetime.now(timezone.utc)
    return await geotab_service.get_device_trips(
        device_id=device_id,
        from_time=from_time or (now - timedelta(hours=24)),
        to_time=to_time or now,
        organization_id=organization_id,
        db=db
    )


@router.get(
    "/exceptions",
    dependencies=[Depends(get_current_active_user)],
)
async def get_geotab_exceptions(
    organization_id: UUID = Depends(get_tenant_org_id),
    driver_id: Optional[UUID] = None,
    device_id: Optional[str] = None,
    exception_type: Optional[str] = None,
    hours_back: int = Query(24, ge=1, le=168),
    db: AsyncSession = Depends(get_tenant_db)
):
    """Get GeoTab exceptions (harsh braking, speeding, HOS violations)"""
    # ORG FROM THE TOKEN, SESSION FROM get_tenant_db. This took `organization_id` as a
    # client-supplied query parameter and ran on `get_db`, which binds no tenant GUC —
    # so on the RLS-protected tables the service queries, the policy filtered every row
    # and the endpoint returned nothing to anyone, including for its own organisation.
    # The same pair of mistakes was fixed on `get_fleet_summary` in this file and on five
    # transportation handlers; these six were missed because their queries live in the
    # SERVICE, so the get_db guard — which inspects handler bodies for RLS models —
    # cannot see them.
    try:
        exceptions = await geotab_service.get_exceptions(
            organization_id=organization_id,
            driver_id=driver_id,
            exception_type=exception_type,
            hours_back=hours_back,
            db=db
        )
        if device_id:
            exceptions = [e for e in exceptions if e.get("device_id") == device_id]
        return {
            "organization_id": str(organization_id) if organization_id else None,
            "hours_back": hours_back,
            "exception_count": len(exceptions),
            "exceptions": exceptions
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get(
    "/devices/{device_id}/diagnostics",
    dependencies=[Depends(get_current_active_user)],
)
async def get_device_diagnostics(
    device_id: str,
    organization_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db)
):
    """Get GeoTab device diagnostics (DTC codes, reefer status, etc.)"""
    # ORG FROM THE TOKEN, SESSION FROM get_tenant_db. This took `organization_id` as a
    # client-supplied query parameter and ran on `get_db`, which binds no tenant GUC —
    # so on the RLS-protected tables the service queries, the policy filtered every row
    # and the endpoint returned nothing to anyone, including for its own organisation.
    # The same pair of mistakes was fixed on `get_fleet_summary` in this file and on five
    # transportation handlers; these six were missed because their queries live in the
    # SERVICE, so the get_db guard — which inspects handler bodies for RLS models —
    # cannot see them.
    try:
        diagnostics = await geotab_service.get_device_diagnostics(
            device_id=device_id,
            organization_id=organization_id,
            db=db
        )
        return diagnostics
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@webhook_router.post("/webhook")
async def geotab_webhook(
    webhook_data: dict,
    db: AsyncSession = Depends(get_db)
):
    """Webhook receiver for real-time GeoTab events"""
    try:
        result = await geotab_service.handle_webhook(
            webhook_data=webhook_data,
            db=db
        )
        return {
            "status": "processed",
            "event_type": webhook_data.get("type"),
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get(
    "/drivers/{driver_id}/hos",
    dependencies=[Depends(get_current_active_user)],
)
async def get_driver_hos_geotab(
    driver_id: UUID,
    organization_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db)
):
    """Get driver HOS status from GeoTab"""
    # ORG FROM THE TOKEN, SESSION FROM get_tenant_db. This took `organization_id` as a
    # client-supplied query parameter and ran on `get_db`, which binds no tenant GUC —
    # so on the RLS-protected tables the service queries, the policy filtered every row
    # and the endpoint returned nothing to anyone, including for its own organisation.
    # The same pair of mistakes was fixed on `get_fleet_summary` in this file and on five
    # transportation handlers; these six were missed because their queries live in the
    # SERVICE, so the get_db guard — which inspects handler bodies for RLS models —
    # cannot see them.
    try:
        hos_status = await geotab_service.get_driver_hos(
            driver_id=driver_id,
            organization_id=organization_id,
            db=db
        )
        return hos_status
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get(
    "/fleet/summary",
    dependencies=[Depends(get_current_active_user)],
)
async def get_fleet_summary(
    # From the TOKEN. As a client-supplied query parameter this was the IDOR shape,
    # and it did not work either: the geotab tables have row-level security and this
    # handler set no tenant GUC, so every underlying query returned nothing and the
    # summary reported zeros for every caller.
    organization_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db)
):
    """Get fleet-wide GeoTab summary"""
    try:
        summary = await geotab_service.get_fleet_summary(
            organization_id=organization_id,
            db=db
        )
        return summary
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

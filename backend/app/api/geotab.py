"""
GeoTab Integration API Endpoints
Fleet telematics, HOS compliance, vehicle diagnostics
"""

import hmac
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from pydantic import BaseModel
from uuid import UUID
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_active_user
from app.core.config import settings
from app.db.database import get_db
from app.middleware.tenant_isolation import get_tenant_db, get_tenant_org_id
from app.services.geotab_service import geotab_service, simulated_provenance

# Read/query endpoints require an authenticated user.
router = APIRouter(prefix="/geotab", tags=["geotab"],
                   dependencies=[Depends(get_current_active_user)])


# ---- Response schemas (pool #43 / FS-256).
#
# Most of these hand back whatever `geotab_service` returns, so the envelope is
# declared and the records are not — the service owns that structure, and a fixed
# model here would silently drop whatever it adds.
#
# ⚠ RESOLVED 2026-08-01 (FS-267), and the warning is kept because it records why.
# `geotab_service` fabricates with ~30 `random.*` call sites, including the
# hours-of-service figures below, which are DOT-regulated. Declaring a schema for a
# generated number does not make it a measurement — and for a while the schema work
# made these surfaces read as MORE trustworthy while nothing about the data changed.
#
# There were two defences and they covered different sets. `_require_simulated` (FS-25)
# stops fabricated telematics reaching a live deployment; `simulated_provenance` (FS-233)
# tells a consumer of the demo data what it is holding. Four functions were gated and
# only two were stamped, so `get_exceptions` (which can emit `hos_violation`) and
# `get_device_diagnostics` (DTC codes, cold-chain reefer temperatures) shipped unlabelled.
# Every gated function is now stamped, and
# `tests/test_simulated_data_says_so.py` fails the build if a new one is not.


class GeotabExceptionsResponse(BaseModel):
    organization_id: str
    hours_back: int
    exception_count: int
    exceptions: List[Dict[str, Any]]
    #: Stamped on the ENVELOPE as well as on each item, because the generator draws
    #: `random.randint(0, 10)` records and an empty list would otherwise carry no
    #: provenance at all — leaving a simulated "no exceptions today" indistinguishable
    #: from a measured one. That is the reading an operator is most likely to trust.
    simulated: bool = True
    data_source: str = "geotab_simulator"
    warning: Optional[str] = None


class GeotabWebhookAck(BaseModel):
    status: str
    event_type: Optional[str] = None
    timestamp: str



async def verify_geotab_webhook(x_webhook_secret: Optional[str] = Header(None)):
    """Guard the external webhook with a shared secret (no user JWT available)."""
    expected = settings.GEOTAB_WEBHOOK_SECRET
    if expected and not hmac.compare_digest(x_webhook_secret or "", expected):
        raise HTTPException(status_code=401, detail="Invalid webhook secret")


# Webhook is an external callback: secret-guarded, not user-authenticated.
webhook_router = APIRouter(prefix="/geotab", tags=["geotab"],
                           dependencies=[Depends(verify_geotab_webhook)])


@router.get("/devices", response_model=List[Dict[str, Any]])
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


@router.get("/devices/{device_id}/location", response_model=Dict[str, Any])
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


@router.get("/devices/{device_id}/trips", response_model=List[Dict[str, Any]])
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
    response_model=GeotabExceptionsResponse,
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
            "exceptions": exceptions,
            # The whole handler is unreachable unless GEOTAB_SIMULATED is set —
            # `get_exceptions` calls `_require_simulated` and raises otherwise — so the
            # envelope is simulated by construction, empty list or not.
            **simulated_provenance(),
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get(
    "/devices/{device_id}/diagnostics",
    #: An OBJECT, not a list. geotab_service.get_device_diagnostics is annotated
    #: -> Dict[str, Any] and returns {device_id, …, diagnostics: {...}}. Declaring
    #: List here was a guess from the plural route name, and
    #: test_frontend_response_shapes_match caught it against the frontend's own
    #: type: an envelope typed as an array throws `.map is not a function`.
    response_model=Dict[str, Any],
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


@webhook_router.post("/webhook", response_model=GeotabWebhookAck)
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
    response_model=Dict[str, Any],
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
    response_model=Dict[str, Any],
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

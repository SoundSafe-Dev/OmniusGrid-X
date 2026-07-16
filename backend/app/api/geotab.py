"""
GeoTab Integration API Endpoints
Fleet telematics, HOS compliance, vehicle diagnostics
"""

from datetime import datetime, timedelta
from typing import List, Optional
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_active_user
from app.db.database import get_db
from app.services.geotab_service import geotab_service

router = APIRouter(prefix="/geotab", tags=["geotab"])


@router.get(
    "/exceptions",
    dependencies=[Depends(get_current_active_user)],
)
async def get_geotab_exceptions(
    organization_id: UUID,
    driver_id: Optional[UUID] = None,
    exception_type: Optional[str] = None,
    hours_back: int = Query(24, ge=1, le=168),
    db: AsyncSession = Depends(get_db)
):
    """Get GeoTab exceptions (harsh braking, speeding, HOS violations)"""
    try:
        exceptions = await geotab_service.get_exceptions(
            organization_id=organization_id,
            driver_id=driver_id,
            exception_type=exception_type,
            hours_back=hours_back,
            db=db
        )
        return {
            "organization_id": str(organization_id),
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
    organization_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """Get GeoTab device diagnostics (DTC codes, reefer status, etc.)"""
    try:
        diagnostics = await geotab_service.get_device_diagnostics(
            device_id=device_id,
            organization_id=organization_id,
            db=db
        )
        return diagnostics
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/webhook")
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
            "timestamp": datetime.utcnow().isoformat()
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get(
    "/drivers/{driver_id}/hos",
    dependencies=[Depends(get_current_active_user)],
)
async def get_driver_hos_geotab(
    driver_id: UUID,
    organization_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """Get driver HOS status from GeoTab"""
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
    organization_id: UUID,
    db: AsyncSession = Depends(get_db)
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

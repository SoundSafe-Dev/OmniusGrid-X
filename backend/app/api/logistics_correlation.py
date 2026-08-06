"""
Logistics Correlation API Endpoints
Cross-domain data correlation between YMS/TMS and manufacturing

TENANT SESSION, NOT get_db. `dock_appointments` is RLS-protected and every handler here
ran on a session that sets no `app.current_org_id`, so the policy matched nothing and each
endpoint returned an empty result — despite the handlers filtering on `organization_id`
correctly themselves. A correct application-layer filter is no help when RLS has already
removed the row.

`organization_id` also came from the query string as a REQUIRED parameter: the IDOR shape
`app/core/tenant.py` forbids, and a 422 for any client that did not send it. It now comes
from the token.

SEPARATE, UNFIXED, AND DELIBERATE: the double `/logistics` prefix (see the comment above
`router` below). Removing it collides with `fleet_logistics.logistics_router`, which
serves the two paths the frontend actually calls. That is a product decision about which
implementation is canonical, not a routing edit.
"""

from datetime import datetime, timedelta, timezone
from typing import List, Optional
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_active_user
from app.db.database import get_db  # noqa: F401
from app.middleware.tenant_isolation import get_tenant_db, get_tenant_org_id
from app.models.schemas import (
    LogisticsCorrelationResponse,
    DockScheduleCorrelationResponse,
    DetentionRiskPrediction,
    LoadQualityLogCreate,
    LoadQualityLogResponse,
    TruckAssetCorrelationResponse
)
from app.services.logistics_correlation_engine import (
    logistics_correlation_engine,
    DockProductionSynchronizer,
    DetentionRiskPredictor,
    LoadQualityCorrelator
)
from app.middleware.rbac import require_operator_or_admin

# NOTE ON THE DOUBLED PREFIX. main.py mounts this router at /api/v1/logistics
# and the prefix below adds another, so every path here is served at
# /api/v1/logistics/logistics/... That looks like an obvious bug to delete —
# don't, without reading this first.
#
# RESOLVED (FS-468). This router declared `prefix="/logistics"` while `main.py` mounted it
# at `/api/v1/logistics`, so all twelve of its paths served at
# `/api/v1/logistics/logistics/…`. The prefix could not simply be dropped, because
# `fleet_logistics.logistics_router` is mounted at the same place and defines its own
# `/delivery-efficiency` and `/compliance/summary`; this router registers first, so it
# would have silently won and changed the payload the frontend receives.
#
# THE DECISION, which was the actual blocker rather than the edit:
# `fleet_logistics` is canonical for those two paths. It declares response models, its
# `/compliance/summary` carries the HOS fix that stopped an unreported driver counting as
# compliant, and its single-prefix paths are what `transportation.ts` calls today.
#
# So the two here are renamed under `/correlation/` — they are correlation-flavoured
# variants with different semantics (this one takes a `days` window) and deserve names
# that say so — and the inner prefix is gone. Twelve paths moved from
# `/api/v1/logistics/logistics/X` to `/api/v1/logistics/X`; nothing outside this
# repository's own tests referenced the doubled form.
router = APIRouter(
    tags=["logistics_correlation"],
    dependencies=[Depends(get_current_active_user)],
)


# ==================== Dashboard Endpoints ====================

@router.get("/correlation-dashboard", response_model=LogisticsCorrelationResponse)
async def get_correlation_dashboard(
    date: Optional[datetime] = Query(None),
    # organization_id from the TOKEN. As a required client-supplied query
    # parameter it was the IDOR shape app/core/tenant.py forbids, and it made
    # every call a 422 for any client that did not send it.
    organization_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db)
):
    """Get comprehensive logistics correlation dashboard"""
    dashboard = await logistics_correlation_engine.get_correlation_dashboard(
        organization_id=organization_id,
        date=date,
        db=db
    )
    return dashboard


# ==================== Dock-Production Sync Endpoints ====================

@router.get("/dock-production-sync", response_model=dict)
async def get_dock_production_sync(
    date: Optional[datetime] = Query(None),
    # organization_id from the TOKEN. As a required client-supplied query
    # parameter it was the IDOR shape app/core/tenant.py forbids, and it made
    # every call a 422 for any client that did not send it.
    organization_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db)
):
    """Get dock schedule aligned with production forecasts"""
    synchronizer = DockProductionSynchronizer()
    sync_data = await synchronizer.get_sync_dashboard(
        organization_id=organization_id,
        date=date,
        db=db
    )
    return sync_data


@router.post("/dock-appointments/{appointment_id}/sync", dependencies=[Depends(require_operator_or_admin)])
async def sync_dock_appointment(
    appointment_id: UUID,
    db: AsyncSession = Depends(get_tenant_db)
):
    """Run dock-production sync analysis for specific appointment"""
    synchronizer = DockProductionSynchronizer()
    try:
        result = await synchronizer.sync_dock_with_production(
            appointment_id=appointment_id,
            db=db
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ==================== Truck-Asset Readiness Endpoints ====================

@router.get("/truck-asset-readiness")
async def get_truck_asset_readiness(
    shipment_id: Optional[UUID] = None,
    # organization_id from the TOKEN. As a required client-supplied query
    # parameter it was the IDOR shape app/core/tenant.py forbids, and it made
    # every call a 422 for any client that did not send it.
    organization_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db)
):
    """Get truck arrival vs asset readiness correlation"""
    if shipment_id:
        # Get specific shipment optimization
        result = await logistics_correlation_engine.optimize_truck_asset_assignment(
            organization_id=organization_id,
            shipment_id=shipment_id,
            db=db
        )
        return result
    else:
        # Get overall readiness metrics for the day
        dashboard = await logistics_correlation_engine.get_correlation_dashboard(
            organization_id=organization_id,
            db=db
        )
        return {
            "production_dock_sync_percent": dashboard['production_dock_sync_percent'],
            "at_risk_appointments": dashboard['at_risk_appointments'],
            "truck_arrivals_today": dashboard['truck_arrivals_today'],
            "avg_dwell_time_hours": dashboard['avg_dwell_time_hours'],
            "note": "Provide shipment_id for specific optimization recommendations"
        }


# ==================== Load Quality Correlation Endpoints ====================

@router.post("/load-quality", response_model=LoadQualityLogResponse, dependencies=[Depends(require_operator_or_admin)])
async def log_load_quality_issue(
    data: LoadQualityLogCreate,
    organization_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db)
):
    """Log shipping defect and correlate to manufacturing root cause"""
    correlator = LoadQualityCorrelator()
    log = await correlator.log_quality_issue(
    # FROM THE TOKEN, NEVER THE REQUEST. This read `data.organization_id`, a field the
    # client supplies, so a caller could file the row under any organisation they named.
    # Removed by hand six times already in this codebase — the yard list, dock doors, dock
    # schedule, maintenance schedule, geofence zones and dashboard overview each carry a
    # comment saying so — which is why it is now a guard
    # (test_no_handler_takes_its_tenant_from_the_body.py) rather than a seventh comment.
    #
    # The `*Create` schema still declares the field, so an existing client may keep sending
    # one; it is ignored. Making it optional there is a separate change with its own readers
    # to check.
        organization_id=organization_id,
        shipment_id=data.shipment_id,
        defect_type=data.defect_type or 'damaged',
        severity=data.severity or 'major',
        quantity_affected=data.quantity_affected or 0,
        asset_id=data.asset_id,
        operation_id=data.operation_id,
        carrier_liable=data.carrier_liable,
        db=db
    )
    return log


@router.get("/load-quality-correlation")
async def get_load_quality_correlation(
    start_date: datetime = Query(default_factory=lambda: datetime.now(timezone.utc) - timedelta(days=30)),
    end_date: Optional[datetime] = Query(None),
    # organization_id from the TOKEN. As a required client-supplied query
    # parameter it was the IDOR shape app/core/tenant.py forbids, and it made
    # every call a 422 for any client that did not send it.
    organization_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db)
):
    """Get load quality correlation analytics"""
    if not end_date:
        end_date = datetime.now(timezone.utc)
    
    correlator = LoadQualityCorrelator()
    analytics = await correlator.get_quality_analytics(
        organization_id=organization_id,
        start_date=start_date,
        end_date=end_date,
        db=db
    )
    return analytics


# ==================== Delivery Efficiency Endpoints ====================

@router.get("/correlation/delivery-efficiency")
async def get_delivery_efficiency(
    days: int = Query(30, ge=1, le=365),
    # organization_id from the TOKEN. As a required client-supplied query
    # parameter it was the IDOR shape app/core/tenant.py forbids, and it made
    # every call a 422 for any client that did not send it.
    organization_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db)
):
    """Get on-time delivery vs production efficiency metrics"""
    from sqlalchemy import case, func, select
    from app.db.models import Shipment
    
    start_date = datetime.now(timezone.utc) - timedelta(days=days)
    
    # Get shipment delivery stats
    result = await db.execute(
        select(
            func.count(Shipment.id).label('total_shipments'),
            func.sum(case((Shipment.actual_delivery <= Shipment.scheduled_delivery, 1), else_=0)).label('on_time'),
            func.avg(
                func.extract('epoch', Shipment.actual_delivery - Shipment.scheduled_delivery) / 60
            ).label('avg_delay_minutes')
        ).where(
            Shipment.organization_id == organization_id,
            Shipment.status == 'delivered',
            Shipment.actual_delivery.isnot(None),
            Shipment.scheduled_delivery.isnot(None),
            Shipment.actual_delivery >= start_date
        )
    )
    row = result.fetchone()
    
    total = row.total_shipments or 0
    on_time = row.on_time or 0
    on_time_percent = (on_time / total * 100) if total > 0 else 0
    avg_delay = row.avg_delay_minutes or 0
    
    return {
        "period_days": days,
        "total_delivered_shipments": total,
        "on_time_deliveries": on_time,
        "on_time_percent": round(on_time_percent, 1),
        "late_deliveries": total - on_time,
        "avg_delay_minutes": round(float(avg_delay), 1) if avg_delay else 0,
        # THE SAME EMPTINESS DEFECT, FAILING THE OTHER WAY. With no shipments in the
        # period `on_time_percent` is 0, which is below every threshold, so the grade
        # came out "D" — a failing mark awarded for a week with nothing to deliver.
        # Pessimism from absence is no more true than optimism from it; both are a
        # verdict on data that does not exist. `None` says so, and `graded` lets a
        # caller distinguish it from a missing field.
        "graded": total > 0,
        "efficiency_grade": (
            None
            if total == 0
            else "A" if on_time_percent >= 95
            else "B" if on_time_percent >= 85
            else "C" if on_time_percent >= 75
            else "D"
        ),
    }


# ==================== Detention Risk Prediction Endpoints ====================

@router.post("/predict-detention", response_model=DetentionRiskPrediction, dependencies=[Depends(require_operator_or_admin)])
async def predict_detention(
    appointment_id: UUID,
    db: AsyncSession = Depends(get_tenant_db)
):
    """Predict detention risk for a dock appointment"""
    predictor = DetentionRiskPredictor()
    try:
        prediction = await predictor.predict_risk(
            appointment_id=appointment_id,
            db=db
        )
        return DetentionRiskPrediction(**prediction)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/detention-risk/upcoming")
async def get_upcoming_detention_risks(
    hours_ahead: int = Query(24, ge=1, le=168),
    # organization_id from the TOKEN. As a required client-supplied query
    # parameter it was the IDOR shape app/core/tenant.py forbids, and it made
    # every call a 422 for any client that did not send it.
    organization_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db)
):
    """Get detention risk predictions for upcoming appointments"""
    from sqlalchemy import select
    from app.db.models import DockAppointment
    
    cutoff = datetime.now(timezone.utc) + timedelta(hours=hours_ahead)
    
    result = await db.execute(
        select(DockAppointment).where(
            DockAppointment.organization_id == organization_id,
            DockAppointment.scheduled_start >= datetime.now(timezone.utc),
            DockAppointment.scheduled_start <= cutoff,
            DockAppointment.status.in_(['scheduled', 'in_progress'])
        )
    )
    appointments = result.scalars().all()
    
    predictor = DetentionRiskPredictor()
    predictions = []
    
    for appt in appointments:
        try:
            pred = await predictor.predict_risk(appt.id, db)
            predictions.append(pred)
        except Exception:
            continue
    
    # Sort by risk score (highest first)
    predictions.sort(key=lambda x: x['risk_score'], reverse=True)
    
    high_risk_count = sum(1 for p in predictions if p['risk_score'] >= 50)
    
    return {
        "appointments_analyzed": len(appointments),
        "high_risk_count": high_risk_count,
        "predictions": predictions[:10],  # Top 10 risks
        "summary": {
            "critical": sum(1 for p in predictions if p['risk_level'] == 'critical'),
            "high": sum(1 for p in predictions if p['risk_level'] == 'high'),
            "medium": sum(1 for p in predictions if p['risk_level'] == 'medium'),
            "low": sum(1 for p in predictions if p['risk_level'] == 'low')
        }
    }


# ==================== Compliance & Safety Endpoints ====================

@router.get("/correlation/compliance-summary")
async def get_compliance_summary(
    # organization_id from the TOKEN. As a required client-supplied query
    # parameter it was the IDOR shape app/core/tenant.py forbids, and it made
    # every call a 422 for any client that did not send it.
    organization_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db)
):
    """Get logistics compliance summary (DOT, CTPAT, HOS)"""
    from sqlalchemy import case, func, select
    from app.db.models import Carrier, Driver, DockAppointment
    
    # Carrier compliance
    carrier_result = await db.execute(
        select(
            func.count(Carrier.id).label('total'),
            func.sum(case((Carrier.ctpat_certified == True, 1), else_=0)).label('ctpat_count'),
            # Both conditions must hold. Written as two separate WHENs, it
            # counted any carrier with insurance on file as valid — CASE returns
            # on the first match, so an expired policy still scored 1.
            func.sum(
                case(
                    (
                        and_(
                            Carrier.insurance_on_file == True,  # noqa: E712
                            Carrier.insurance_expires_at > datetime.now(timezone.utc),
                        ),
                        1,
                    ),
                    else_=0,
                )
            ).label('valid_insurance')
        ).where(
            Carrier.organization_id == organization_id,
            Carrier.is_active == True
        )
    )
    carrier_row = carrier_result.fetchone()
    
    # Driver HOS compliance
    hos_violations = await db.execute(
        select(func.count(Driver.id)).where(
            Driver.organization_id == organization_id,
            or_(
                Driver.hos_drive_hours_today > 11,
                Driver.hos_on_duty_hours_today > 14,
                Driver.medical_cert_expires < datetime.now(timezone.utc)
            )
        )
    )
    hos_count = hos_violations.scalar() or 0

    # HOW MANY DRIVERS COULD NOT BE JUDGED AT ALL.
    #
    # The violation query above filters on `>` comparisons, and **SQL NULL never
    # satisfies a comparison** — it evaluates to UNKNOWN, which WHERE discards. So a
    # driver who has never reported hours, or has no medical certificate on file, is not
    # counted as a violation and not counted as anything else either. `hos_count == 0`
    # then reads as a clean fleet, and the endpoint below returned "COMPLIANT".
    #
    # Same defect as `HOSComplianceMonitor.check_compliance` (Python coercing NULL to 0)
    # and as the carrier roll-up (a zero count over zero drivers), reached a third way.
    # Absence keeps arriving as a clean result.
    driver_totals = (
        await db.execute(
            select(
                func.count(Driver.id).label("total"),
                func.count(Driver.id)
                .filter(
                    or_(
                        Driver.hos_drive_hours_today.is_(None),
                        Driver.hos_on_duty_hours_today.is_(None),
                        Driver.medical_cert_expires.is_(None),
                    )
                )
                .label("unassessable"),
            ).where(Driver.organization_id == organization_id)
        )
    ).fetchone()
    total_drivers = driver_totals.total or 0
    unassessable_drivers = driver_totals.unassessable or 0
    
    # Driver medical cert expirations (next 30 days)
    medical_expiring = await db.execute(
        select(func.count(Driver.id)).where(
            Driver.organization_id == organization_id,
            Driver.medical_cert_expires.between(
                datetime.now(timezone.utc),
                datetime.now(timezone.utc) + timedelta(days=30)
            )
        )
    )
    medical_expiring_count = medical_expiring.scalar() or 0
    
    return {
        "carrier_compliance": {
            "total_carriers": carrier_row.total or 0,
            "ctpat_certified": carrier_row.ctpat_count or 0,
            "valid_insurance": carrier_row.valid_insurance or 0,
            # `or 1` invents a denominator so the expression cannot raise, and the 0%
            # it yields is indistinguishable from an organisation whose carriers are all
            # uncertified. With no carriers there is no rate to report.
            "compliance_rate": (
                round((carrier_row.ctpat_count or 0) / carrier_row.total * 100, 1)
                if carrier_row.total
                else None
            ),
        },
        "driver_compliance": {
            "hos_violations_today": hos_count,
            "medical_certs_expiring_30_days": medical_expiring_count,
            "total_drivers": total_drivers,
            "unassessable_drivers": unassessable_drivers,
        },
        # UNKNOWN is its own answer. "COMPLIANT" now requires that there were drivers and
        # that every one of them had the data needed to judge them; anything else is
        # reported as INCOMPLETE_DATA rather than folded into ATTENTION_REQUIRED, because
        # "your fleet has a problem" and "we could not check your fleet" send an operator
        # to different places.
        "overall_status": (
            "COMPLIANT"
            if (
                total_drivers > 0
                and unassessable_drivers == 0
                and hos_count == 0
                and (carrier_row.ctpat_count or 0) > 0
            )
            else "INCOMPLETE_DATA"
            if total_drivers == 0 or unassessable_drivers > 0
            else "ATTENTION_REQUIRED"
        ),
    }


# ==================== Optimize Assignment Endpoints ====================

@router.post("/optimize-assignment", dependencies=[Depends(require_operator_or_admin)])
async def optimize_assignment(
    shipment_id: UUID,
    # organization_id from the TOKEN. As a required client-supplied query
    # parameter it was the IDOR shape app/core/tenant.py forbids, and it made
    # every call a 422 for any client that did not send it.
    organization_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db)
):
    """Get optimal truck-asset assignment recommendations"""
    result = await logistics_correlation_engine.optimize_truck_asset_assignment(
        organization_id=organization_id,
        shipment_id=shipment_id,
        db=db
    )
    return result


# ==================== Liability & Cost Endpoints ====================

@router.get("/liability/costs")
async def get_liability_costs(
    days: int = Query(30, ge=1, le=365),
    # organization_id from the TOKEN. As a required client-supplied query
    # parameter it was the IDOR shape app/core/tenant.py forbids, and it made
    # every call a 422 for any client that did not send it.
    organization_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db)
):
    """Get detention, demurrage, and quality liability costs"""
    from sqlalchemy import case, func, select
    from app.db.models import DriverWaitTime, LoadQualityLog
    
    start_date = datetime.now(timezone.utc) - timedelta(days=days)
    
    # Detention/Demurrage costs
    detention_result = await db.execute(
        select(
            func.sum(DriverWaitTime.detention_charge).label('total_detention'),
            func.sum(DriverWaitTime.demurrage_charge).label('total_demurrage'),
            func.count(func.distinct(DriverWaitTime.id)).label('incident_count')
        ).where(
            DriverWaitTime.organization_id == organization_id,
            DriverWaitTime.check_in_at >= start_date
        )
    )
    detention_row = detention_result.fetchone()
    
    # Quality liability
    quality_result = await db.execute(
        select(
            func.sum(LoadQualityLog.claim_amount).label('total_claims'),
            func.sum(case((LoadQualityLog.carrier_liable == False, LoadQualityLog.claim_amount), else_=0)).label('manufacturing_liability'),
            func.sum(case((LoadQualityLog.carrier_liable == True, LoadQualityLog.claim_amount), else_=0)).label('carrier_liability')
        ).where(
            LoadQualityLog.organization_id == organization_id,
            LoadQualityLog.created_at >= start_date
        )
    )
    quality_row = quality_result.fetchone()
    
    detention_total = float(detention_row.total_detention or 0) + float(detention_row.total_demurrage or 0)
    quality_total = float(quality_row.total_claims or 0)
    
    return {
        "period_days": days,
        "detention_demurrage": {
            "total_charges": round(detention_total, 2),
            "detention": round(float(detention_row.total_detention or 0), 2),
            "demurrage": round(float(detention_row.total_demurrage or 0), 2),
            "incident_count": detention_row.incident_count or 0
        },
        "quality_claims": {
            "total_claims": round(quality_total, 2),
            "manufacturing_liability": round(float(quality_row.manufacturing_liability or 0), 2),
            "carrier_liability": round(float(quality_row.carrier_liability or 0), 2)
        },
        "total_liability": round(detention_total + quality_total, 2)
    }

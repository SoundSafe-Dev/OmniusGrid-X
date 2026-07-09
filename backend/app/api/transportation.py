"""
Transportation Management API Endpoints (TMS)
Carrier management, shipment tracking, routing, HOS compliance
"""

from datetime import datetime, timedelta
from typing import List, Optional
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db.database import get_db
from app.db.models import Carrier, Driver, Shipment, Route, LoadPlan, FreightCharge
from app.models.schemas import (
    CarrierCreate, CarrierUpdate, CarrierResponse,
    DriverCreate, DriverUpdate, DriverResponse,
    ShipmentCreate, ShipmentUpdate, ShipmentResponse,
    RouteCreate, RouteUpdate, RouteResponse,
    LoadPlanCreate, LoadPlanResponse,
    FreightChargeCreate, FreightChargeResponse
)
from app.services.transportation_management import transportation_management_service

# No router-level prefix: main.py already includes this router at its /api/v1/...
# path. (The old prefix double-prefixed every route — e.g. /api/v1/yard/yard/* —
# never noticed because the frontend ran on mocks.)
router = APIRouter(tags=["transportation_management"])


# ==================== Carrier Endpoints ====================

@router.post("/carriers", response_model=CarrierResponse)
async def create_carrier(
    data: CarrierCreate,
    db: AsyncSession = Depends(get_db)
):
    """Create new carrier profile"""
    carrier = await transportation_management_service.create_carrier(
        organization_id=data.organization_id,
        carrier_name=data.carrier_name,
        dot_number=data.dot_number,
        mc_number=data.mc_number,
        ctpat_certified=data.ctpat_certified,
        insurance_on_file=data.insurance_on_file,
        safety_rating=data.safety_rating,
        csa_score=data.csa_score,
        contract_rate=data.contract_rate,
        contact_info=data.contact_info,
        db=db
    )
    return carrier


@router.get("/carriers", response_model=List[CarrierResponse])
async def get_carriers(
    organization_id: UUID,
    is_active: Optional[bool] = Query(True),
    db: AsyncSession = Depends(get_db)
):
    """Get carriers for organization"""
    query = select(Carrier).where(
        Carrier.organization_id == organization_id
    )
    if is_active is not None:
        query = query.where(Carrier.is_active == is_active)
    
    result = await db.execute(query)
    return result.scalars().all()


@router.get("/carriers/{carrier_id}", response_model=CarrierResponse)
async def get_carrier(
    carrier_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """Get carrier details"""
    result = await db.execute(
        select(Carrier).where(Carrier.id == carrier_id)
    )
    carrier = result.scalar_one_or_none()
    if not carrier:
        raise HTTPException(status_code=404, detail="Carrier not found")
    return carrier


@router.put("/carriers/{carrier_id}", response_model=CarrierResponse)
async def update_carrier(
    carrier_id: UUID,
    data: CarrierUpdate,
    db: AsyncSession = Depends(get_db)
):
    """Update carrier profile"""
    result = await db.execute(
        select(Carrier).where(Carrier.id == carrier_id)
    )
    carrier = result.scalar_one_or_none()
    if not carrier:
        raise HTTPException(status_code=404, detail="Carrier not found")
    
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(carrier, field, value)
    
    carrier.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(carrier)
    return carrier


@router.get("/carriers/{carrier_id}/compliance")
async def get_carrier_compliance(
    carrier_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """Get carrier compliance summary"""
    try:
        compliance = await transportation_management_service.get_carrier_compliance_summary(
            carrier_id=carrier_id,
            db=db
        )
        return compliance
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ==================== Driver Endpoints ====================

@router.post("/drivers", response_model=DriverResponse)
async def create_driver(
    data: DriverCreate,
    db: AsyncSession = Depends(get_db)
):
    """Create new driver profile"""
    driver = await transportation_management_service.create_driver(
        organization_id=data.organization_id,
        first_name=data.first_name,
        last_name=data.last_name,
        carrier_id=data.carrier_id,
        license_number=data.license_number,
        license_state=data.license_state,
        cdl_class=data.cdl_class,
        hazmat_endorsed=data.hazmat_endorsed,
        medical_cert_expires=data.medical_cert_expires,
        eld_device_id=data.eld_device_id,
        phone=data.phone,
        email=data.email,
        db=db
    )
    return driver


@router.get("/drivers", response_model=List[DriverResponse])
async def get_drivers(
    organization_id: UUID,
    carrier_id: Optional[UUID] = None,
    is_active: Optional[bool] = Query(True),
    db: AsyncSession = Depends(get_db)
):
    """Get drivers for organization"""
    query = select(Driver).where(
        Driver.organization_id == organization_id
    )
    if carrier_id:
        query = query.where(Driver.carrier_id == carrier_id)
    if is_active is not None:
        query = query.where(Driver.is_active == is_active)
    
    result = await db.execute(query)
    return result.scalars().all()


@router.get("/drivers/{driver_id}", response_model=DriverResponse)
async def get_driver(
    driver_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """Get driver details"""
    result = await db.execute(
        select(Driver).where(Driver.id == driver_id)
    )
    driver = result.scalar_one_or_none()
    if not driver:
        raise HTTPException(status_code=404, detail="Driver not found")
    return driver


@router.put("/drivers/{driver_id}", response_model=DriverResponse)
async def update_driver(
    driver_id: UUID,
    data: DriverUpdate,
    db: AsyncSession = Depends(get_db)
):
    """Update driver profile"""
    result = await db.execute(
        select(Driver).where(Driver.id == driver_id)
    )
    driver = result.scalar_one_or_none()
    if not driver:
        raise HTTPException(status_code=404, detail="Driver not found")
    
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(driver, field, value)
    
    driver.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(driver)
    return driver


@router.get("/drivers/{driver_id}/hos")
async def get_driver_hos(
    driver_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """Get driver HOS compliance status"""
    try:
        hos_status = await transportation_management_service.get_driver_hos_status(
            driver_id=driver_id,
            db=db
        )
        return hos_status
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ==================== Shipment Endpoints ====================

@router.post("/shipments", response_model=ShipmentResponse)
async def create_shipment(
    data: ShipmentCreate,
    db: AsyncSession = Depends(get_db)
):
    """Create new shipment"""
    shipment = await transportation_management_service.create_shipment(
        organization_id=data.organization_id,
        shipment_number=data.shipment_number,
        shipment_type=data.shipment_type,
        origin=data.origin,
        destination=data.destination,
        scheduled_pickup=data.scheduled_pickup,
        scheduled_delivery=data.scheduled_delivery,
        carrier_id=data.carrier_id,
        driver_id=data.driver_id,
        trailer_id=data.trailer_id,
        total_weight_lbs=data.total_weight_lbs,
        total_pieces=data.total_pieces,
        hazmat=data.hazmat,
        temperature_required=data.temperature_required,
        pro_number=data.pro_number,
        bol_number=data.bol_number,
        db=db
    )
    return shipment


@router.get("/shipments", response_model=List[ShipmentResponse])
async def get_shipments(
    organization_id: UUID,
    status: Optional[str] = Query(None),
    carrier_id: Optional[UUID] = None,
    db: AsyncSession = Depends(get_db)
):
    """Get shipments for organization"""
    query = select(Shipment).where(
        Shipment.organization_id == organization_id
    )
    if status:
        query = query.where(Shipment.status == status)
    if carrier_id:
        query = query.where(Shipment.carrier_id == carrier_id)
    
    result = await db.execute(query.order_by(Shipment.created_at.desc()))
    return result.scalars().all()


@router.get("/shipments/{shipment_id}", response_model=ShipmentResponse)
async def get_shipment(
    shipment_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """Get shipment details"""
    result = await db.execute(
        select(Shipment).where(Shipment.id == shipment_id)
    )
    shipment = result.scalar_one_or_none()
    if not shipment:
        raise HTTPException(status_code=404, detail="Shipment not found")
    return shipment


@router.put("/shipments/{shipment_id}", response_model=ShipmentResponse)
async def update_shipment(
    shipment_id: UUID,
    data: ShipmentUpdate,
    db: AsyncSession = Depends(get_db)
):
    """Update shipment"""
    result = await db.execute(
        select(Shipment).where(Shipment.id == shipment_id)
    )
    shipment = result.scalar_one_or_none()
    if not shipment:
        raise HTTPException(status_code=404, detail="Shipment not found")
    
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(shipment, field, value)
    
    shipment.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(shipment)
    return shipment


@router.post("/shipments/{shipment_id}/dispatch")
async def dispatch_shipment(
    shipment_id: UUID,
    driver_id: UUID,
    trailer_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """Dispatch shipment to driver"""
    try:
        shipment = await transportation_management_service.dispatch_shipment(
            shipment_id=shipment_id,
            driver_id=driver_id,
            trailer_id=trailer_id,
            db=db
        )
        return {
            "message": "Shipment dispatched",
            "shipment_id": str(shipment_id),
            "driver_id": str(driver_id),
            "status": shipment.status
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/shipments/{shipment_id}/status")
async def update_shipment_status(
    shipment_id: UUID,
    status: str,
    actual_pickup: Optional[datetime] = None,
    actual_delivery: Optional[datetime] = None,
    db: AsyncSession = Depends(get_db)
):
    """Update shipment status"""
    try:
        shipment = await transportation_management_service.update_shipment_status(
            shipment_id=shipment_id,
            status=status,
            actual_pickup=actual_pickup,
            actual_delivery=actual_delivery,
            db=db
        )
        return {
            "message": "Shipment status updated",
            "shipment_id": str(shipment_id),
            "status": shipment.status
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/shipments/{shipment_id}/costs")
async def get_shipment_costs(
    shipment_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """Calculate shipment costs"""
    try:
        costs = await transportation_management_service.calculate_shipment_costs(
            shipment_id=shipment_id,
            db=db
        )
        return costs
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ==================== Route Endpoints ====================

@router.post("/routes", response_model=RouteResponse)
async def create_route(
    data: RouteCreate,
    db: AsyncSession = Depends(get_db)
):
    """Create optimized route"""
    route = await transportation_management_service.create_route(
        organization_id=data.organization_id,
        origin=data.origin,
        destination=data.destination,
        waypoints=data.waypoints,
        route_name=data.route_name,
        optimization_criteria=data.optimization_criteria,
        db=db
    )
    return route


@router.get("/routes", response_model=List[RouteResponse])
async def get_routes(
    organization_id: UUID,
    is_active: Optional[bool] = Query(True),
    db: AsyncSession = Depends(get_db)
):
    """Get routes for organization"""
    query = select(Route).where(
        Route.organization_id == organization_id
    )
    if is_active is not None:
        query = query.where(Route.is_active == is_active)
    
    result = await db.execute(query)
    return result.scalars().all()


# ==================== Load Plan Endpoints ====================

@router.post("/load-plans", response_model=LoadPlanResponse)
async def create_load_plan(
    data: LoadPlanCreate,
    db: AsyncSession = Depends(get_db)
):
    """Create load plan for shipment"""
    load_plan = await transportation_management_service.create_load_plan(
        organization_id=data.organization_id,
        shipment_id=data.shipment_id,
        trailer_id=data.trailer_id,
        load_sequence=data.load_sequence,
        weight_distribution=data.weight_distribution,
        space_utilization_percent=data.space_utilization_percent,
        special_instructions=data.special_instructions,
        planned_by=data.planned_by,
        db=db
    )
    return load_plan


@router.get("/shipments/{shipment_id}/load-plan", response_model=LoadPlanResponse)
async def get_load_plan(
    shipment_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """Get load plan for shipment"""
    result = await db.execute(
        select(LoadPlan).where(LoadPlan.shipment_id == shipment_id)
    )
    load_plan = result.scalar_one_or_none()
    if not load_plan:
        raise HTTPException(status_code=404, detail="Load plan not found")
    return load_plan


# ==================== Freight Charge Endpoints ====================

@router.post("/freight-charges", response_model=FreightChargeResponse)
async def create_freight_charge(
    data: FreightChargeCreate,
    db: AsyncSession = Depends(get_db)
):
    """Create freight charge"""
    from app.services.transportation_management import FreightBillingEngine
    billing_engine = FreightBillingEngine()
    
    charge = await billing_engine.create_freight_charge(
        organization_id=data.organization_id,
        shipment_id=data.shipment_id,
        charge_type=data.charge_type,
        amount=data.amount,
        carrier_id=data.carrier_id,
        charge_description=data.charge_description,
        rate_basis=data.rate_basis,
        quantity=data.quantity,
        rate=data.rate,
        db=db
    )
    return charge


@router.get("/shipments/{shipment_id}/freight-charges", response_model=List[FreightChargeResponse])
async def get_shipment_charges(
    shipment_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """Get freight charges for shipment"""
    result = await db.execute(
        select(FreightCharge).where(FreightCharge.shipment_id == shipment_id)
    )
    return result.scalars().all()


# ==================== Vehicles (task D20; backed by migration 025) ====================

@router.get("/vehicles")
async def get_vehicles(
    carrier_id: Optional[UUID] = None,
    db: AsyncSession = Depends(get_db)
):
    """List fleet vehicles (previously frontend-mock-only)."""
    from sqlalchemy import select
    from app.db.logistics_models import Vehicle

    query = select(Vehicle).where(Vehicle.is_active == True)  # noqa: E712
    if carrier_id:
        query = query.where(Vehicle.carrier_id == str(carrier_id))
    vehicles = (await db.execute(query)).scalars().all()
    return [
        {
            "id": str(v.id),
            "vehicleNumber": v.vehicle_number,
            "vin": v.vin,
            "make": v.make,
            "model": v.model,
            "year": v.year,
            "status": v.status,
            "fuelLevel": v.fuel_level_percent,
            "odometer": v.odometer_miles,
            "geotabDeviceId": v.geotab_device_id,
            "currentDriverId": v.current_driver_id,
            "lastLocation": v.last_location or {},
        }
        for v in vehicles
    ]


@router.post("/vehicles")
async def create_vehicle(
    payload: dict,
    db: AsyncSession = Depends(get_db)
):
    """Register a fleet vehicle."""
    from app.db.logistics_models import Vehicle

    vehicle = Vehicle(
        organization_id=payload.get("organization_id"),
        carrier_id=payload.get("carrier_id"),
        vehicle_number=payload.get("vehicle_number") or payload.get("vehicleNumber"),
        vin=payload.get("vin"),
        make=payload.get("make"),
        model=payload.get("model"),
        year=payload.get("year"),
        status=payload.get("status", "idle"),
        geotab_device_id=payload.get("geotab_device_id"),
    )
    if not vehicle.vehicle_number:
        raise HTTPException(status_code=400, detail="vehicle_number is required")
    db.add(vehicle)
    await db.commit()
    await db.refresh(vehicle)
    return {"id": str(vehicle.id), "vehicleNumber": vehicle.vehicle_number}


def compute_delivery_efficiency(shipments: list) -> dict:
    """Pure aggregate for the delivery-efficiency panel (task D20).

    on-time = delivered with actual_delivery <= scheduled_delivery.
    """
    delivered = [s for s in shipments if getattr(s, "status", None) == "delivered"]
    on_time = [
        s for s in delivered
        if s.actual_delivery and s.scheduled_delivery and s.actual_delivery <= s.scheduled_delivery
    ]
    transit_hours = [
        (s.actual_delivery - s.actual_pickup).total_seconds() / 3600
        for s in delivered
        if s.actual_delivery and s.actual_pickup
    ]
    today = datetime.utcnow().date()
    return {
        "onTimeRate": round(len(on_time) / len(delivered), 4) if delivered else 1.0,
        "avgTransitHours": round(sum(transit_hours) / len(transit_hours), 1) if transit_hours else 0.0,
        "deliveredToday": sum(
            1 for s in delivered if s.actual_delivery and s.actual_delivery.date() == today
        ),
        "totalDelivered": len(delivered),
    }

"""
Transportation Management API Endpoints (TMS)
Carrier management, shipment tracking, routing, HOS compliance
"""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any, Dict, List, Optional
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.api.auth import get_current_active_user
from app.core.pagination import MAX_OFFSET, PaginatedResponse, mark_truncated, paginate
from app.db.database import get_db
from app.middleware.tenant_isolation import get_tenant_db, get_tenant_org_id
from app.core.tenant_refs import verify_refs
from app.db.models import Carrier, Driver, Shipment, Route, LoadPlan, FreightCharge
from app.models.schemas import (
    CarrierCreate, CarrierUpdate, CarrierResponse,
    DriverCreate, DriverUpdate, DriverResponse, DriverListItem,
    ShipmentCreate, ShipmentUpdate, ShipmentResponse,
    RouteCreate, RouteUpdate, RouteResponse,
    LoadPlanCreate, LoadPlanUpdate, LoadPlanResponse,
    FreightChargeCreate, FreightChargeUpdate, FreightChargeResponse
)
from app.services.transportation_management import transportation_management_service

# No router-level prefix: main.py already includes this router at its /api/v1/...
# path. (The old prefix double-prefixed every route — e.g. /api/v1/yard/yard/* —
# never noticed because the frontend ran on mocks.)
from app.middleware.rbac import require_operator_or_admin

router = APIRouter(tags=["transportation_management"], dependencies=[Depends(get_current_active_user)])


def _iso(dt):
    """ISO-8601 string for a datetime, or None."""
    return dt.isoformat() if dt else None


async def _resolve_carrier_names(carrier_ids, db: AsyncSession) -> Dict[str, Any]:
    """Map {carrier_id -> carrier_name} in one query (the UI shows names)."""
    ids = {c for c in carrier_ids if c}
    if not ids:
        return {}
    rows = (await db.execute(
        select(Carrier.id, Carrier.carrier_name).where(Carrier.id.in_(ids))
    )).all()
    return {str(cid): name for cid, name in rows}


#: A shipment in one of these has been handed over; the driver is no longer on it.
_TERMINAL_SHIPMENT_STATUSES = ("delivered", "cancelled", "completed")


async def _resolve_driver_assignments(driver_ids, db: AsyncSession) -> Dict[str, Dict[str, Any]]:
    """Map {driver_id -> {vehicle_id, shipment_id}} in two queries.

    `drivers` holds neither association: a vehicle names its driver
    (`vehicles.current_driver_id`) and a shipment names its driver
    (`shipments.driver_id`). So the driver's side of both is a reverse lookup, and a
    column-by-column comparison of the table against the client's type reports
    `currentVehicleId`/`currentShipmentId` as having no source — which is how the panel ended
    up with two rows that never rendered.

    Two queries for the whole page rather than two per driver; the N+1 is easy to write here
    and this endpoint is the fleet list.
    """
    from app.db.logistics_models import Vehicle

    ids = {str(d) for d in driver_ids if d}
    if not ids:
        return {}

    out: Dict[str, Dict[str, Any]] = {}
    vehicles = (await db.execute(
        select(Vehicle.id, Vehicle.current_driver_id).where(
            Vehicle.current_driver_id.in_(ids)
        )
    )).all()
    for vehicle_id, driver_id in vehicles:
        out.setdefault(str(driver_id), {})["vehicle_id"] = str(vehicle_id)

    shipments = (await db.execute(
        select(Shipment.id, Shipment.driver_id).where(
            Shipment.driver_id.in_(ids),
            # A delivered shipment is not what the driver is on NOW. Without this the panel
            # would name whichever historical load the query happened to return first.
            Shipment.status.notin_(_TERMINAL_SHIPMENT_STATUSES),
        ).order_by(Shipment.scheduled_pickup.desc())
    )).all()
    for shipment_id, driver_id in shipments:
        out.setdefault(str(driver_id), {}).setdefault("shipment_id", str(shipment_id))

    return out


# ---- Small response schemas for stable dict-shaped endpoints (FS-100). ----
# Shapes are unchanged; these only document/type what the handlers already return.

class ShipmentDispatchRequest(BaseModel):
    """Who and what a shipment is dispatched with (FS-420).

    A BODY, not two bare parameters. Declared as bare `driver_id: UUID, trailer_id: UUID`,
    FastAPI reads them as QUERY parameters — and the client sent them in the body, so every
    dispatch returned 422 and the feature had never worked once. Same shape as FS-379, where
    Strategic approve/reject sent `operator_id` in a body the server declared as a query
    parameter.

    `trailer_id`, not `vehicle_id`: `Shipment.trailer_id` is a foreign key to
    `yard_trailers`, and there is no vehicle column on a shipment. The picker on the
    Transportation page offered vehicles, so even a well-formed call would have written a
    vehicle id into a trailer FK — accepted silently by SQLite and refused by Postgres.
    """

    driver_id: UUID
    trailer_id: UUID


class ShipmentDispatchResponse(BaseModel):
    message: str
    shipment_id: str
    driver_id: str
    status: str


class ShipmentStatusUpdateRequest(BaseModel):
    """The new status of a shipment, in a BODY (FS-658).

    THIRD TIME FOR THIS SHAPE, and the second in this file. Declared as bare
    `status: str, actual_pickup: ..., actual_delivery: ...`, FastAPI reads every one of them
    as a QUERY parameter — a non-Pydantic scalar with no `Body(...)` marker always is. The
    client posts `{ status, note }` as JSON (`api/transportation.ts`), so the required
    `?status=` was never present and **every status update answered 422**. The two buttons
    that call it — "Mark delivered" and "Cancel" on the Transportation page — have never
    worked once.

    `ShipmentDispatchRequest` twenty lines above carries the same correction for FS-420, and
    FS-379 carried it for Strategic approve/reject. Fixing an instance is not fixing a class:
    the neighbouring route was never looked at.

    `note` is DECLARED AND REFUSED rather than quietly ignored. The client sends one and there
    is nowhere for it to go — `Shipment` has no note column — so accepting the field would
    make the API claim to record something it discards. Pydantic drops unknown fields
    silently by default, which is the same lie with less effort.
    """

    model_config = {"extra": "forbid"}

    status: str
    actual_pickup: Optional[datetime] = None
    actual_delivery: Optional[datetime] = None


class ShipmentStatusUpdateResponse(BaseModel):
    message: str
    shipment_id: str
    status: str


class VehicleCreatedResponse(BaseModel):
    id: str
    vehicleNumber: str  # noqa: N815 — vehicles endpoints are legacy-camelCase


# ==================== Carrier Endpoints ====================

@router.post("/carriers", response_model=CarrierResponse, dependencies=[Depends(require_operator_or_admin)])
async def create_carrier(
    data: CarrierCreate,
    organization_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db)
):
    """Create new carrier profile"""
    carrier = await transportation_management_service.create_carrier(
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
        carrier_name=data.carrier_name,
        dot_number=data.dot_number,
        mc_number=data.mc_number,
        ctpat_certified=data.ctpat_certified,
        insurance_on_file=data.insurance_on_file,
        safety_rating=data.safety_rating,
        csa_score=data.csa_score,
        contract_rate=data.contract_rate,
        contact_info=data.contact_info,
        # THE READER DEPENDS ON THESE AND THE WRITER DROPPED THEM (FS-662).
        # `get_carrier_compliance` computes `ctpat_status.is_valid` as
        # `certified AND expires_at AND expires_at > now`, and the same for insurance. This
        # route passed `ctpat_certified` and `insurance_on_file` and discarded both dates —
        # so every carrier created through the API had NULL expiries and reported **invalid**
        # on both counts, whatever the caller sent.
        #
        # Same pairing as the checkpoint with no inspector and the check-in with no seal
        # status: the flag was stored and the field that bounds it was not. Here the reader
        # already existed, which is what makes it the sharpest of the three.
        ctpat_expires_at=data.ctpat_expires_at,
        insurance_expires_at=data.insurance_expires_at,
        is_active=data.is_active,
        db=db
    )
    return carrier


@router.get("/carriers", response_model=List[CarrierResponse])
async def get_carriers(
    # organization_id comes from the TOKEN. As a required client-supplied query
    # parameter it was the IDOR shape app/core/tenant.py forbids — and it did not
    # even work: on get_db no tenant GUC is set, and these tables have FORCE row
    # level security, so the policy filtered EVERY row. This endpoint returned an
    # empty list to every caller, including for its own organization.
    response: Response,
    organization_id: UUID = Depends(get_tenant_org_id),
    is_active: Optional[bool] = Query(True),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0, le=MAX_OFFSET),
    db: AsyncSession = Depends(get_tenant_db)
):
    """Get carriers for organization"""
    query = select(Carrier).where(
        Carrier.organization_id == organization_id
    )
    if is_active is not None:
        query = query.where(Carrier.is_active == is_active)
    # A stable ORDER BY is what makes offset/limit paging deterministic across calls --
    # without one, Postgres is free to return rows in a different order per query plan.
    query = query.order_by(Carrier.id).offset(offset).limit(limit + 1)

    result = await db.execute(query)
    return mark_truncated(response, result.scalars().all(), limit)


@router.get("/carriers/{carrier_id}", response_model=CarrierResponse)
async def get_carrier(
    carrier_id: UUID,
    db: AsyncSession = Depends(get_tenant_db)
):
    """Get carrier details"""
    result = await db.execute(
        select(Carrier).where(Carrier.id == carrier_id)
    )
    carrier = result.scalar_one_or_none()
    if not carrier:
        raise HTTPException(status_code=404, detail="Carrier not found")
    return carrier


@router.put("/carriers/{carrier_id}", response_model=CarrierResponse, dependencies=[Depends(require_operator_or_admin)])
async def update_carrier(
    carrier_id: UUID,
    data: CarrierUpdate,
    db: AsyncSession = Depends(get_tenant_db)
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
    
    carrier.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(carrier)
    return carrier


class CertificationStatus(BaseModel):
    """Shared by C-TPAT and insurance: held, until when, and whether that is still true
    today. `is_valid` is the AND of the other two against `now` — a certification on file
    with a past expiry is on file and not valid, and the tile needs to say which."""

    certified: Optional[bool] = None
    on_file: Optional[bool] = None
    expires_at: Optional[str] = None
    is_valid: Optional[bool] = None


class CarrierDriverCompliance(BaseModel):
    total_drivers: int
    hos_violations: int
    expired_medical_certs: int
    #: Drivers whose HOS could not be judged for want of data. A missing figure is NOT a
    #: violation — counting it as one trades a false clearance for a false accusation.
    unassessable_drivers: int
    #: Judged AND passed. Subtracting only violations counted the unassessable as
    #: compliant, which is the same error one level up.
    compliant_drivers: int


class CarrierComplianceOut(BaseModel):
    """`transportation_management_service.get_carrier_compliance_summary`.

    `drivers_assessed` is the field that makes the rest readable: `hos_violations == 0`
    is trivially true for a carrier with no driver records, so `overall_compliant` used
    to clear a carrier nobody had entered data for. Hours of Service is DOT-regulated,
    and the frontend rendered a green tick for it.
    """

    carrier_id: str
    carrier_name: Optional[str] = None
    ctpat_status: CertificationStatus
    insurance_status: CertificationStatus
    safety_rating: Optional[str] = None
    #: NUMERIC column, cast to float by the service. `None` means unscored — 0 is the
    #: BEST possible CSA score, and a falsy check on it reported a spotless carrier as
    #: having no score on file.
    csa_score: Optional[float] = None
    driver_compliance: CarrierDriverCompliance
    drivers_assessed: bool
    overall_compliant: bool


class DriverHoursSummary(BaseModel):
    drive_hours_today: Optional[float] = None
    on_duty_hours_today: Optional[float] = None
    cycle_hours: Optional[float] = None
    drive_hours_remaining: Optional[float] = None
    on_duty_hours_remaining: Optional[float] = None
    cycle_hours_remaining: Optional[float] = None


class DriverHOSOut(BaseModel):
    """`HOSComplianceMonitor.check_compliance`. Three lists, kept separate on purpose.

    `missing_data` is not `violations`. A driver with no medical certificate on file has
    not broken a rule; nobody knows whether they have. `is_compliant` requires both an
    empty violations list AND an empty missing-data list, and `assessable` reports the
    second on its own so a consumer can render "unknown" rather than "clear".
    """

    driver_id: str
    is_compliant: bool
    assessable: bool
    missing_data: List[str] = Field(default_factory=list)
    violations: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    hours_summary: DriverHoursSummary


class LinehaulAssumptions(BaseModel):
    """Where the linehaul rate came from (FS-665).

    The sibling of `FuelSurchargeAssumptions`, and for the same reason its docstring gives:
    a fallback should be labelled as one. `rate_per_mile or 2.50` billed an uncontracted
    carrier at a number nobody agreed to, and a fabricated rate and a contracted one at the
    same value produced byte-identical results — so no consumer could distinguish them.
    """

    basis: str
    rate_per_mile: float
    rate_source: str
    note: str


class LinehaulCharge(BaseModel):
    """`amount` is None when the charge could NOT be estimated.

    A shipment with no route has no distance, and the per-mile charge is
    `distance * rate` — so there is no honest figure. Returning 0 would fabricate a cheap
    shipment exactly as the old 500-mile fallback fabricated an expensive one. `rate_basis`
    reads `not_estimated` and `assumptions.basis` says why.
    """

    charge_type: str
    rate_basis: str
    distance_miles: Optional[float] = None
    weight_lbs: Optional[float] = None
    mileage_charge: Optional[float] = None
    weight_charge: Optional[float] = None
    assumptions: Optional[LinehaulAssumptions] = None
    amount: Optional[float] = None


class FuelSurchargeAssumptions(BaseModel):
    """What the surcharge amount rests on (FS-533).

    The previous docstring on `FuelSurchargeCharge` said: "the honest fix is to label a
    fallback surcharge as one." This is that label, and it is a declared part of the
    response rather than a note in the source — a consumer reading `amount` can see, in
    the same payload, whether it came from a contract or from a configured average.
    """

    basis: str
    base_fuel_price_usd_per_gallon: float
    current_fuel_price_usd_per_gallon: float
    average_mpg: float
    rate_per_mile: float
    note: str


class FuelSurchargeCharge(BaseModel):
    """NOT A MEASUREMENT unless `assumptions.basis` says so.

    Without a contract fuel-surcharge table the engine derives `amount` from configured
    fleet assumptions — the current fuel price and MPG that `optimize_route` uses, plus a
    base price the surcharge is measured above. Those were three hardcoded default
    arguments that no caller ever supplied, numerically identical to the settings and
    disconnected from them (FS-533).

    `assumptions` now travels with the figure and names its `basis`, so "billed against our
    contract" and "estimated from a fleet average" are distinguishable by a consumer rather
    than only by reading the service."""

    charge_type: str
    rate_basis: str
    distance_miles: Optional[float] = None
    base_fuel_price: Optional[float] = None
    current_fuel_price: Optional[float] = None
    assumptions: Optional[FuelSurchargeAssumptions] = None
    #: None when there is no distance to estimate from — see `LinehaulCharge`.
    amount: Optional[float] = None


class ShipmentCostsOut(BaseModel):
    shipment_id: str
    linehaul: LinehaulCharge
    fuel_surcharge: FuelSurchargeCharge
    #: None when either component could not be estimated. A total of 0 under two charges
    #: that both say "not estimated" would be the same fabrication one layer up.
    total_cost: Optional[float] = None
    distance_miles: Optional[float] = None
    weight_lbs: Optional[float] = None


@router.get("/carriers/{carrier_id}/compliance", response_model=CarrierComplianceOut)
async def get_carrier_compliance(
    carrier_id: UUID,
    db: AsyncSession = Depends(get_tenant_db)
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

@router.post("/drivers", response_model=DriverResponse, dependencies=[Depends(require_operator_or_admin)])
async def create_driver(
    data: DriverCreate,
    organization_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db)
):
    """Create new driver profile"""

    # EVERY ID IN THIS BODY, AGAINST THE CALLER'S OWN ORGANISATION (FS-737). `carrier_id`,
    # `driver_id`, `trailer_id`, `shipment_id` and `route_id` all name tenant-owned rows
    # and a foreign key is checked BELOW row-level security, so each was accepted verbatim.
    await verify_refs(db, organization_id, data.model_dump(exclude_unset=True))
    driver = await transportation_management_service.create_driver(
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
        # SIX FIELDS THE SCHEMA DECLARED AND THIS ROUTE DROPPED (FS-664), four of them
        # DOT-regulated Hours of Service.
        #
        # `HOSComplianceMonitor.check_compliance` collects WHAT IS MISSING before what is
        # wrong — it requires drive hours, on-duty hours AND cycle hours, and reports
        # "cannot be assessed" when any is None. `dispatch_shipment` raises on that verdict.
        # So a driver created through this endpoint could never be dispatched at all.
        #
        # And there was no other way in. The GeoTab ELD webhook writes `hos_drive_hours_today`
        # and `hos_on_duty_hours_today` — only those two, only when that gated integration is
        # live. **`hos_cycle_hours` and `current_hos_status` have no writer anywhere but the
        # demo seeder**, which is why the seeded fleet dispatches and a real one would not.
        #
        # Accepting an initial value here does not race the sync: create sets the state the
        # operator knows, the webhook overwrites it when the ELD reports. That was the
        # question that deferred this fix, and the answer is that there is no conflict.
        current_hos_status=data.current_hos_status,
        hos_drive_hours_today=data.hos_drive_hours_today,
        hos_on_duty_hours_today=data.hos_on_duty_hours_today,
        hos_cycle_hours=data.hos_cycle_hours,
        dq_file_complete=data.dq_file_complete,
        is_active=data.is_active,
        db=db
    )
    return driver


# 49 CFR 395, from `app.core.hos_limits` (FS-475). These used to be re-declared here, with
# a comment explaining that importing them from the compliance service "would drag its
# session dependencies into this module" — true, and the reason the copy survived review.
#
# The copy was the problem, not the import. This module computes hours REMAINING, which a
# dispatcher reads before assigning a load; the compliance service decides VIOLATIONS,
# which is read afterwards. Two copies meant those two answers could disagree about the
# same driver while both looked authoritative. `hos_limits` has no imports at all, so the
# original objection no longer applies to it.
from app.core.hos_limits import MAX_DRIVE_HOURS_DAY, MAX_ON_DUTY_HOURS_DAY  # noqa: E402


def _hours_remaining(stored, consumed, limit):
    """Remaining HOS, preferring a stored figure and deriving it when there is none.

    Returns None when neither is known — the caller must render that as "unknown", not as
    a full tank and not as zero. Both readings are verdicts, and neither was earned.
    """
    if stored is not None:
        return stored
    if consumed is None:
        return None
    return round(max(0.0, limit - float(consumed)), 2)


@router.get("/drivers", response_model=List[DriverListItem])
async def get_drivers(
    response: Response,
    # organization_id comes from the TOKEN. As a required client-supplied query
    # parameter it was the IDOR shape app/core/tenant.py forbids — and it did not
    # even work: on get_db no tenant GUC is set, and these tables have FORCE row
    # level security, so the policy filtered EVERY row. This endpoint returned an
    # empty list to every caller, including for its own organization.
    organization_id: UUID = Depends(get_tenant_org_id),
    carrier_id: Optional[UUID] = None,
    is_active: Optional[bool] = Query(True),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0, le=MAX_OFFSET),
    db: AsyncSession = Depends(get_tenant_db)
):
    """Get drivers for organization (adds carrierName + MISSING UI columns)."""
    query = select(Driver).where(
        Driver.organization_id == organization_id
    )
    if carrier_id:
        query = query.where(Driver.carrier_id == carrier_id)
    if is_active is not None:
        query = query.where(Driver.is_active == is_active)
    query = query.order_by(Driver.id).offset(offset).limit(limit + 1)

    drivers = (await db.execute(query)).scalars().all()
    drivers = mark_truncated(response, drivers, limit)

    # Resolve carrier names for the listed drivers in one query (the UI shows
    # the carrier, not just its id) — mirrors get_vehicles.
    carrier_names = await _resolve_carrier_names(
        {d.carrier_id for d in drivers if d.carrier_id}, db
    )
    assignments = await _resolve_driver_assignments({str(d.id) for d in drivers}, db)

    items: List[Dict[str, Any]] = []
    for d in drivers:
        row = DriverResponse.model_validate(d).model_dump(mode="json", by_alias=True)
        row["carrierName"] = carrier_names.get(str(d.carrier_id))
        # `currentVehicleId` and `currentShipmentId` are declared by the client and were
        # produced by nothing, so the driver panel's "Current Vehicle" and "Current Shipment"
        # rows never rendered. Neither is a column on `drivers` — the association is held from
        # the other side (`vehicles.current_driver_id`, `shipments.driver_id`), which is why a
        # column-by-column comparison of the table against the type reports them as absent
        # rather than as the reverse lookups they are. Batched, not per-row.
        assignment = assignments.get(str(d.id), {})
        row["currentVehicleId"] = assignment.get("vehicle_id")
        row["currentShipmentId"] = assignment.get("shipment_id")
        row["endorsements"] = d.endorsements or []
        row["licenseExpiry"] = _iso(d.license_expiry)
        # DERIVED WHEN THE STORED COLUMN IS NULL, which it always is. Migration 042 added
        # `hos_drive_hours_remaining` and `hos_duty_hours_remaining` with no default and
        # no backfill, and NOTHING in this codebase has ever written to either — no ELD
        # sync, no ingestion path, no computation. The model comment says what they were
        # meant to be ("11 - hos_drive_hours_today") and nothing did the subtraction.
        #
        # The consequence was on the compliance tab, which counts a violation as
        # `hosDriveHoursRemaining === 0`. `null === 0` is FALSE, so every fleet came back
        # with zero violations and a green "No HOS violations detected" tick — on the
        # SUCCESS path, with the data loaded, for DOT-regulated hours.
        #
        # `hos_drive_hours_today` IS populated and is what `check_compliance` already
        # judges against, so remaining is computed from it. Left NULL when the consumed
        # figure is missing too: that driver has genuinely not reported, and inventing
        # "11 hours left" for them would be the same defect pointing the other way.
        row["hosDriveHoursRemaining"] = _hours_remaining(
            d.hos_drive_hours_remaining, d.hos_drive_hours_today, MAX_DRIVE_HOURS_DAY
        )
        row["hosDutyHoursRemaining"] = _hours_remaining(
            d.hos_duty_hours_remaining, d.hos_on_duty_hours_today, MAX_ON_DUTY_HOURS_DAY
        )
        items.append(row)
    return items


@router.get("/drivers/{driver_id}", response_model=DriverResponse)
async def get_driver(
    driver_id: UUID,
    db: AsyncSession = Depends(get_tenant_db)
):
    """Get driver details"""
    result = await db.execute(
        select(Driver).where(Driver.id == driver_id)
    )
    driver = result.scalar_one_or_none()
    if not driver:
        raise HTTPException(status_code=404, detail="Driver not found")
    return driver


@router.put("/drivers/{driver_id}", response_model=DriverResponse, dependencies=[Depends(require_operator_or_admin)])
async def update_driver(
    driver_id: UUID,
    data: DriverUpdate,
    # No organisation was needed here until the ids INSIDE the body had to be
    # checked against one — the row itself is protected by RLS (FS-737).
    organization_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db)
):
    """Update driver profile"""

    # EVERY ID IN THIS BODY, AGAINST THE CALLER'S OWN ORGANISATION (FS-737). `carrier_id`,
    # `driver_id`, `trailer_id`, `shipment_id` and `route_id` all name tenant-owned rows
    # and a foreign key is checked BELOW row-level security, so each was accepted verbatim.
    await verify_refs(db, organization_id, data.model_dump(exclude_unset=True))
    result = await db.execute(
        select(Driver).where(Driver.id == driver_id)
    )
    driver = result.scalar_one_or_none()
    if not driver:
        raise HTTPException(status_code=404, detail="Driver not found")
    
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(driver, field, value)
    
    driver.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(driver)
    return driver


@router.get("/drivers/{driver_id}/hos", response_model=DriverHOSOut)
async def get_driver_hos(
    driver_id: UUID,
    db: AsyncSession = Depends(get_tenant_db)
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

@router.post("/shipments", response_model=ShipmentResponse, dependencies=[Depends(require_operator_or_admin)])
async def create_shipment(
    data: ShipmentCreate,
    organization_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db)
):
    """Create new shipment"""

    # EVERY ID IN THIS BODY, AGAINST THE CALLER'S OWN ORGANISATION (FS-737). `carrier_id`,
    # `driver_id`, `trailer_id`, `shipment_id` and `route_id` all name tenant-owned rows
    # and a foreign key is checked BELOW row-level security, so each was accepted verbatim.
    await verify_refs(db, organization_id, data.model_dump(exclude_unset=True))
    shipment = await transportation_management_service.create_shipment(
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
        # FOUR FIELDS THE SCHEMA DECLARED AND THIS ROUTE DROPPED (FS-667).
        #
        # `temperature_required` was passed and `temperature_min`/`temperature_max` were not:
        # a reefer shipment marked as needing temperature control, with no range to control
        # to. The fourth instance of that pairing — a flag stored and the values that give it
        # meaning discarded (rule 143), after the checkpoint's inspector, the trailer's seal
        # status and the carrier's expiry dates.
        #
        # `route_id` is the one with reach beyond this route. It is how a shipment gets a
        # route, a route is where `total_distance_miles` lives, and that distance is what
        # `get_shipment_costs` bills per mile. Dropped, a shipment created through the API can
        # never be routed at create time — and FS-665 has just made the honest consequence
        # visible, since a shipment with no route now reports its charges as not estimated
        # rather than inventing 500 miles.
        route_id=data.route_id,
        priority=data.priority,
        temperature_min=data.temperature_min,
        temperature_max=data.temperature_max,
        # FS-669. `metadata` is declared on nine Create schemas across four modules and
        # passed by almost none of them; every one of those tables has a `meta_data` column.
        # A caller attaching a reference or a note to a shipment watched it vanish with a 200.
        meta_data=data.metadata,
        db=db
    )
    return shipment


@router.get("/shipments", response_model=PaginatedResponse[Dict[str, Any]])
async def get_shipments(
    # organization_id comes from the TOKEN. As a required client-supplied query
    # parameter it was the IDOR shape app/core/tenant.py forbids — and it did not
    # even work: on get_db no tenant GUC is set, and these tables have FORCE row
    # level security, so the policy filtered EVERY row. This endpoint returned an
    # empty list to every caller, including for its own organization.
    organization_id: UUID = Depends(get_tenant_org_id),
    status: Optional[str] = Query(None),
    carrier_id: Optional[UUID] = None,
    skip: int = Query(0, ge=0, le=MAX_OFFSET),
    limit: int = Query(100, ge=1, le=1000),
    db: AsyncSession = Depends(get_tenant_db)
):
    """Get shipments for organization (FS-99: {items, meta} envelope with a real total).

    Adds carrierName/driverName joins + the MISSING UI columns.
    """
    query = select(Shipment).where(
        Shipment.organization_id == organization_id
    )
    if status:
        query = query.where(Shipment.status == status)
    if carrier_id:
        query = query.where(Shipment.carrier_id == carrier_id)

    total = (await db.execute(
        select(func.count()).select_from(query.subquery())
    )).scalar_one()
    result = await db.execute(
        query.order_by(Shipment.created_at.desc()).offset(skip).limit(limit)
    )
    shipments = result.scalars().all()

    # Resolve carrier + driver names for the listed shipments in one query each.
    carrier_names = await _resolve_carrier_names(
        {s.carrier_id for s in shipments if s.carrier_id}, db
    )
    driver_ids = {s.driver_id for s in shipments if s.driver_id}
    driver_names: Dict[str, Any] = {}
    if driver_ids:
        rows = (await db.execute(
            select(Driver.id, Driver.first_name, Driver.last_name)
            .where(Driver.id.in_(driver_ids))
        )).all()
        driver_names = {str(did): f"{first} {last}".strip() for did, first, last in rows}

    items: List[Dict[str, Any]] = []
    for s in shipments:
        row = ShipmentResponse.model_validate(s).model_dump(mode="json", by_alias=True)
        row["carrierName"] = carrier_names.get(str(s.carrier_id))
        row["driverName"] = driver_names.get(str(s.driver_id))
        row["poNumber"] = s.po_number
        row["freightCharge"] = s.freight_charge
        row["palletCount"] = s.pallet_count
        items.append(row)
    return paginate(items, total, SimpleNamespace(skip=skip, limit=limit))


@router.get("/shipments/{shipment_id}", response_model=ShipmentResponse)
async def get_shipment(
    shipment_id: UUID,
    db: AsyncSession = Depends(get_tenant_db)
):
    """Get shipment details"""
    result = await db.execute(
        select(Shipment).where(Shipment.id == shipment_id)
    )
    shipment = result.scalar_one_or_none()
    if not shipment:
        raise HTTPException(status_code=404, detail="Shipment not found")
    return shipment


@router.put("/shipments/{shipment_id}", response_model=ShipmentResponse, dependencies=[Depends(require_operator_or_admin)])
async def update_shipment(
    shipment_id: UUID,
    data: ShipmentUpdate,
    # No organisation was needed here until the ids INSIDE the body had to be
    # checked against one — the row itself is protected by RLS (FS-737).
    organization_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db)
):
    """Update shipment"""

    # EVERY ID IN THIS BODY, AGAINST THE CALLER'S OWN ORGANISATION (FS-737). `carrier_id`,
    # `driver_id`, `trailer_id`, `shipment_id` and `route_id` all name tenant-owned rows
    # and a foreign key is checked BELOW row-level security, so each was accepted verbatim.
    await verify_refs(db, organization_id, data.model_dump(exclude_unset=True))
    result = await db.execute(
        select(Shipment).where(Shipment.id == shipment_id)
    )
    shipment = result.scalar_one_or_none()
    if not shipment:
        raise HTTPException(status_code=404, detail="Shipment not found")
    
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(shipment, field, value)
    
    shipment.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(shipment)
    return shipment


@router.post("/shipments/{shipment_id}/dispatch", response_model=ShipmentDispatchResponse, dependencies=[Depends(require_operator_or_admin)])
async def dispatch_shipment(
    shipment_id: UUID,
    request: ShipmentDispatchRequest,
    db: AsyncSession = Depends(get_tenant_db)
):
    """Dispatch shipment to driver"""
    try:
        shipment = await transportation_management_service.dispatch_shipment(
            shipment_id=shipment_id,
            driver_id=request.driver_id,
            trailer_id=request.trailer_id,
            db=db
        )
        return {
            "message": "Shipment dispatched",
            "shipment_id": str(shipment_id),
            # `request.driver_id`, not `driver_id` — the bare name is undefined here and
            # raised NameError on EVERY SUCCESSFUL DISPATCH. The service commits before this
            # line runs, so the shipment was dispatched and the caller got a 500: a write
            # that landed, reported as a failure.
            "driver_id": str(request.driver_id),
            "status": shipment.status
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/shipments/{shipment_id}/status", response_model=ShipmentStatusUpdateResponse, dependencies=[Depends(require_operator_or_admin)])
async def update_shipment_status(
    shipment_id: UUID,
    request: ShipmentStatusUpdateRequest,
    db: AsyncSession = Depends(get_tenant_db)
):
    """Update shipment status"""
    try:
        shipment = await transportation_management_service.update_shipment_status(
            shipment_id=shipment_id,
            status=request.status,
            actual_pickup=request.actual_pickup,
            actual_delivery=request.actual_delivery,
            db=db
        )
        return {
            "message": "Shipment status updated",
            "shipment_id": str(shipment_id),
            "status": shipment.status
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/shipments/{shipment_id}/costs", response_model=ShipmentCostsOut)
async def get_shipment_costs(
    shipment_id: UUID,
    db: AsyncSession = Depends(get_tenant_db)
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

@router.post("/routes", response_model=RouteResponse, dependencies=[Depends(require_operator_or_admin)])
async def create_route(
    data: RouteCreate,
    organization_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db)
):
    """Create optimized route"""
    route = await transportation_management_service.create_route(
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
    response: Response,
    # organization_id comes from the TOKEN. As a required client-supplied query
    # parameter it was the IDOR shape app/core/tenant.py forbids — and it did not
    # even work: on get_db no tenant GUC is set, and these tables have FORCE row
    # level security, so the policy filtered EVERY row. This endpoint returned an
    # empty list to every caller, including for its own organization.
    organization_id: UUID = Depends(get_tenant_org_id),
    is_active: Optional[bool] = Query(True),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0, le=MAX_OFFSET),
    db: AsyncSession = Depends(get_tenant_db)
):
    """Get routes for organization"""
    query = select(Route).where(
        Route.organization_id == organization_id
    )
    if is_active is not None:
        query = query.where(Route.is_active == is_active)
    query = query.order_by(Route.id).offset(offset).limit(limit + 1)

    result = await db.execute(query)
    return mark_truncated(response, result.scalars().all(), limit)


@router.put("/routes/{route_id}", response_model=RouteResponse, dependencies=[Depends(require_operator_or_admin)])
async def update_route(
    route_id: UUID,
    data: RouteUpdate,
    organization_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db)
):
    """Update a route.

    THE SCHEMA EXISTED AND NOTHING SERVED IT (FS-677). `RouteUpdate` has been in
    `schemas.py` since routes were added and no route took it, so a route's endpoints and
    cost estimates were fixed at creation. `get_shipment_costs` prices a shipment from its
    route's distance (FS-665), so a route entered with the wrong origin priced every
    shipment on it wrongly, and the only remedy was a second route plus re-pointing each
    shipment by hand.

    Scoped on `organization_id` as well as the tenant session. RLS would refuse a
    cross-tenant row anyway, but that depends on the database ROLE — the argument
    `create_dock_door` and `update_asset` both make.
    """
    result = await db.execute(
        select(Route).where(
            Route.id == route_id,
            Route.organization_id == organization_id,
        )
    )
    route = result.scalar_one_or_none()
    if not route:
        raise HTTPException(status_code=404, detail="Route not found")

    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(route, field, value)

    route.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(route)
    return route


# ==================== Load Plan Endpoints ====================

@router.post("/load-plans", response_model=LoadPlanResponse, dependencies=[Depends(require_operator_or_admin)])
async def create_load_plan(
    data: LoadPlanCreate,
    organization_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db)
):
    """Create load plan for shipment"""

    # EVERY ID IN THIS BODY, AGAINST THE CALLER'S OWN ORGANISATION (FS-737). `carrier_id`,
    # `driver_id`, `trailer_id`, `shipment_id` and `route_id` all name tenant-owned rows
    # and a foreign key is checked BELOW row-level security, so each was accepted verbatim.
    await verify_refs(db, organization_id, data.model_dump(exclude_unset=True))
    load_plan = await transportation_management_service.create_load_plan(
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
        trailer_id=data.trailer_id,
        load_sequence=data.load_sequence,
        weight_distribution=data.weight_distribution,
        space_utilization_percent=data.space_utilization_percent,
        special_instructions=data.special_instructions,
        planned_by=data.planned_by,
        # FS-669. `temperature_zones` is the cold-chain layout of the trailer and `metadata`
        # is the caller's own reference; both were declared and dropped.
        temperature_zones=data.temperature_zones,
        meta_data=data.metadata,
        db=db
    )
    return load_plan


@router.get("/shipments/{shipment_id}/load-plan", response_model=LoadPlanResponse)
async def get_load_plan(
    shipment_id: UUID,
    db: AsyncSession = Depends(get_tenant_db)
):
    """Get load plan for shipment"""
    result = await db.execute(
        select(LoadPlan).where(LoadPlan.shipment_id == shipment_id)
    )
    load_plan = result.scalar_one_or_none()
    if not load_plan:
        raise HTTPException(status_code=404, detail="Load plan not found")
    return load_plan


@router.put("/load-plans/{load_plan_id}", response_model=LoadPlanResponse, dependencies=[Depends(require_operator_or_admin)])
async def update_load_plan(
    load_plan_id: UUID,
    data: LoadPlanUpdate,
    organization_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db)
):
    """Amend a load plan (FS-677).

    There was no update schema and no route, so a plan's sequence, weight distribution and
    reefer zones were whatever the first POST said. Loading is iterative — a pallet does not
    fit, a zone is wrong — and the only remedy was a second plan for the same shipment,
    leaving two on the row contradicting each other.

    `shipment_id` is not on the update schema: a plan moved to another shipment is a
    different plan, not a corrected one.
    """

    # EVERY ID IN THIS BODY, AGAINST THE CALLER'S OWN ORGANISATION (FS-737). `carrier_id`,
    # `driver_id`, `trailer_id`, `shipment_id` and `route_id` all name tenant-owned rows
    # and a foreign key is checked BELOW row-level security, so each was accepted verbatim.
    await verify_refs(db, organization_id, data.model_dump(exclude_unset=True))
    result = await db.execute(
        select(LoadPlan).where(
            LoadPlan.id == load_plan_id,
            LoadPlan.organization_id == organization_id,
        )
    )
    load_plan = result.scalar_one_or_none()
    if not load_plan:
        raise HTTPException(status_code=404, detail="Load plan not found")

    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(load_plan, field, value)

    load_plan.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(load_plan)
    return load_plan


# ==================== Freight Charge Endpoints ====================

@router.post("/freight-charges", response_model=FreightChargeResponse, dependencies=[Depends(require_operator_or_admin)])
async def create_freight_charge(
    data: FreightChargeCreate,
    organization_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db)
):
    """Create freight charge"""

    # EVERY ID IN THIS BODY, AGAINST THE CALLER'S OWN ORGANISATION (FS-737). `carrier_id`,
    # `driver_id`, `trailer_id`, `shipment_id` and `route_id` all name tenant-owned rows
    # and a foreign key is checked BELOW row-level security, so each was accepted verbatim.
    await verify_refs(db, organization_id, data.model_dump(exclude_unset=True))
    from app.services.transportation_management import FreightBillingEngine
    billing_engine = FreightBillingEngine()
    
    charge = await billing_engine.create_freight_charge(
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
        charge_type=data.charge_type,
        amount=data.amount,
        carrier_id=data.carrier_id,
        charge_description=data.charge_description,
        rate_basis=data.rate_basis,
        quantity=data.quantity,
        rate=data.rate,
        # FS-669. A charge in the wrong currency is a wrong number, not a missing one — and
        # `currency` was declared on the schema and discarded, so every charge was recorded
        # as USD whatever the caller said.
        currency=data.currency,
        meta_data=data.metadata,
        db=db
    )
    return charge


@router.get("/shipments/{shipment_id}/freight-charges", response_model=List[FreightChargeResponse])
async def get_shipment_charges(
    shipment_id: UUID,
    db: AsyncSession = Depends(get_tenant_db)
):
    """Get freight charges for shipment"""
    result = await db.execute(
        select(FreightCharge).where(FreightCharge.shipment_id == shipment_id)
    )
    return result.scalars().all()


@router.put("/freight-charges/{charge_id}", response_model=FreightChargeResponse, dependencies=[Depends(require_operator_or_admin)])
async def update_freight_charge(
    charge_id: UUID,
    data: FreightChargeUpdate,
    organization_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db)
):
    """Correct a freight charge (FS-677).

    There was no update schema and no route. FS-665 found this same service inventing a
    500-mile default and a $2.50 rate, compounding into a $1,333.33 linehaul charge
    presented as computed — and once written, that figure could not be amended by any means
    the API offered. A charge you cannot correct is worse than one that is wrong, because
    the wrongness becomes permanent at the moment somebody notices it.

    `shipment_id` is not on the update schema: a charge moved to another shipment is a
    different charge.
    """

    # EVERY ID IN THIS BODY, AGAINST THE CALLER'S OWN ORGANISATION (FS-737). `carrier_id`,
    # `driver_id`, `trailer_id`, `shipment_id` and `route_id` all name tenant-owned rows
    # and a foreign key is checked BELOW row-level security, so each was accepted verbatim.
    await verify_refs(db, organization_id, data.model_dump(exclude_unset=True))
    result = await db.execute(
        select(FreightCharge).where(
            FreightCharge.id == charge_id,
            FreightCharge.organization_id == organization_id,
        )
    )
    charge = result.scalar_one_or_none()
    if not charge:
        raise HTTPException(status_code=404, detail="Freight charge not found")

    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(charge, field, value)

    charge.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(charge)
    return charge


# ==================== Vehicles (task D20; backed by migration 025) ====================

@router.get("/vehicles", response_model=PaginatedResponse[Dict[str, Any]])
async def get_vehicles(
    carrier_id: Optional[UUID] = None,
    skip: int = Query(0, ge=0, le=MAX_OFFSET),
    limit: int = Query(100, ge=1, le=1000),
    org_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db)
):
    """List fleet vehicles (FS-99: {items, meta} envelope; items stay legacy-camelCase).

    SCOPED TO THE CALLER'S ORG. This was `get_db` with no organization filter at all,
    on a table that carries `organization_id` but has NO row-level security — so the
    two mechanisms that normally catch this both missed. Verified against a real
    database before the fix: org A's client listed org B's vehicle. That is a
    cross-tenant read of live data, not a theoretical one.

    `vehicles.organization_id` is a `String(36)`, not a UUID column, so the comparison
    is made against `str(org_id)`.
    """
    from app.db.logistics_models import Vehicle

    # ORDERED so the cap and the offset mean something (FS-429): an unordered paged
    # list can repeat rows on one page and skip them on the next.
    query = select(Vehicle).order_by(Vehicle.vehicle_number).where(
        Vehicle.organization_id == str(org_id),
        Vehicle.is_active == True,  # noqa: E712
    )
    if carrier_id:
        query = query.where(Vehicle.carrier_id == str(carrier_id))

    total = (await db.execute(
        select(func.count()).select_from(query.subquery())
    )).scalar_one()
    vehicles = (await db.execute(query.offset(skip).limit(limit))).scalars().all()

    # Resolve carrier names for the listed vehicles in one query (the UI shows
    # the carrier, not just its id).
    carrier_ids = {v.carrier_id for v in vehicles if v.carrier_id}
    carrier_names: Dict[str, Any] = {}
    if carrier_ids:
        rows = (await db.execute(
            select(Carrier.id, Carrier.carrier_name).where(Carrier.id.in_(carrier_ids))
        )).all()
        carrier_names = {str(cid): name for cid, name in rows}

    def _iso(dt):
        return dt.isoformat() if dt else None

    items = [
        {
            "id": str(v.id),
            "vehicleNumber": v.vehicle_number,
            "carrierId": v.carrier_id,
            "carrierName": carrier_names.get(str(v.carrier_id)),
            "vin": v.vin,
            "make": v.make,
            "model": v.model,
            "year": v.year,
            "status": v.status,
            "vehicleType": v.vehicle_type,
            "fuelType": v.fuel_type,
            "licensePlate": v.license_plate,
            "dotNumber": v.dot_number,
            "grossVehicleWeight": v.gross_vehicle_weight_kg,
            "engineHours": v.engine_hours,
            "registrationExpiry": _iso(v.registration_expiry),
            "inspectionDue": _iso(v.inspection_due),
            "fuelLevel": v.fuel_level_percent,
            "odometer": v.odometer_miles,
            "geotabDeviceId": v.geotab_device_id,
            "currentDriverId": v.current_driver_id,
            "lastLocation": v.last_location or {},
        }
        for v in vehicles
    ]
    return paginate(items, total, SimpleNamespace(skip=skip, limit=limit))


@router.post("/vehicles", response_model=VehicleCreatedResponse)
async def create_vehicle(
    payload: dict,
    organization_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db)
):
    """Register a fleet vehicle."""
    from app.db.logistics_models import Vehicle

    vehicle = Vehicle(
        # FROM THE TOKEN, NEVER THE PAYLOAD. This read `payload.get("organization_id")`,
        # which let any caller file a vehicle under any organisation they named — the IDOR
        # shape this codebase forbids and has already removed from the yard, dock-door,
        # dock-schedule, maintenance-schedule and geofence handlers, each with a comment
        # saying so. Every sibling handler in THIS file already takes the org from
        # `get_tenant_org_id`; only the create missed it.
        #
        # It was also broken when the field was simply absent: `payload.get` returns None,
        # and a vehicle with no organisation belongs to no tenant — invisible to its own
        # creator through any scoped read, and picked up by anything that scans the table
        # unscoped.
        organization_id=organization_id,
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
    today = datetime.now(timezone.utc).date()
    return {
        "onTimeRate": round(len(on_time) / len(delivered), 4) if delivered else 1.0,
        "avgTransitHours": round(sum(transit_hours) / len(transit_hours), 1) if transit_hours else 0.0,
        "deliveredToday": sum(
            1 for s in delivered if s.actual_delivery and s.actual_delivery.date() == today
        ),
        "totalDelivered": len(delivered),
    }

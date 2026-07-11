"""
Transportation Management System (TMS)
Carrier management, shipment tracking, route optimization, HOS compliance
"""

from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from uuid import UUID
import structlog
from sqlalchemy import text, select, and_, or_, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import AsyncSessionLocal
from app.db.models import (
    Carrier, Driver, Shipment, Route, LoadPlan,
    FreightCharge, YardTrailer, DockAppointment
)

logger = structlog.get_logger()


class HOSComplianceMonitor:
    """Monitor driver Hours of Service compliance"""
    
    # FMCSA HOS limits
    MAX_DRIVE_HOURS_DAY = 11.0
    MAX_ON_DUTY_HOURS_DAY = 14.0
    MAX_CYCLE_HOURS = 70.0  # 8-day cycle
    REQUIRED_REST_HOURS = 10.0
    
    def check_compliance(self, driver: Driver) -> Dict[str, Any]:
        """Check driver's current HOS compliance status"""
        violations = []
        warnings = []

        # Numeric columns come back as Decimal; coerce once so the float
        # arithmetic below never mixes Decimal and float (TypeError).
        drive_hours = float(driver.hos_drive_hours_today or 0)
        on_duty_hours = float(driver.hos_on_duty_hours_today or 0)
        cycle_hours = float(driver.hos_cycle_hours or 0)

        # Check drive time
        if drive_hours >= self.MAX_DRIVE_HOURS_DAY:
            violations.append(f"Drive hours exceeded: {drive_hours}h > {self.MAX_DRIVE_HOURS_DAY}h")
        elif drive_hours >= self.MAX_DRIVE_HOURS_DAY - 1:
            warnings.append(f"Drive time nearing limit: {drive_hours}h")

        # Check on-duty time
        if on_duty_hours >= self.MAX_ON_DUTY_HOURS_DAY:
            violations.append(f"On-duty hours exceeded: {on_duty_hours}h > {self.MAX_ON_DUTY_HOURS_DAY}h")
        elif on_duty_hours >= self.MAX_ON_DUTY_HOURS_DAY - 1:
            warnings.append(f"On-duty time nearing limit: {on_duty_hours}h")

        # Check cycle hours
        if cycle_hours >= self.MAX_CYCLE_HOURS:
            violations.append(f"Cycle hours exceeded: {cycle_hours}h > {self.MAX_CYCLE_HOURS}h")
        elif cycle_hours >= self.MAX_CYCLE_HOURS - 10:
            warnings.append(f"Cycle time nearing limit: {cycle_hours}h")

        # Check medical cert
        if driver.medical_cert_expires and driver.medical_cert_expires < datetime.utcnow():
            violations.append("Medical certificate expired")
        elif driver.medical_cert_expires and driver.medical_cert_expires < datetime.utcnow() + timedelta(days=30):
            warnings.append("Medical certificate expiring soon")

        return {
            'driver_id': str(driver.id),
            'is_compliant': len(violations) == 0,
            'violations': violations,
            'warnings': warnings,
            'hours_summary': {
                'drive_hours_today': drive_hours,
                'on_duty_hours_today': on_duty_hours,
                'cycle_hours': cycle_hours,
                'drive_hours_remaining': max(0, self.MAX_DRIVE_HOURS_DAY - drive_hours),
                'on_duty_hours_remaining': max(0, self.MAX_ON_DUTY_HOURS_DAY - on_duty_hours),
                'cycle_hours_remaining': max(0, self.MAX_CYCLE_HOURS - cycle_hours)
            }
        }
    
    def can_accept_load(self, driver: Driver, estimated_hours: float) -> Dict[str, Any]:
        """Determine if driver can legally accept a new load"""
        compliance = self.check_compliance(driver)
        
        if not compliance['is_compliant']:
            return {
                'can_accept': False,
                'reason': 'HOS violations exist',
                'compliance': compliance
            }
        
        hours = compliance['hours_summary']
        
        if estimated_hours > hours['drive_hours_remaining']:
            return {
                'can_accept': False,
                'reason': f'Insufficient drive hours: need {estimated_hours}h, have {hours["drive_hours_remaining"]}h',
                'compliance': compliance
            }
        
        if estimated_hours > hours['on_duty_hours_remaining']:
            return {
                'can_accept': False,
                'reason': f'Insufficient on-duty hours: need {estimated_hours}h, have {hours["on_duty_hours_remaining"]}h',
                'compliance': compliance
            }
        
        return {
            'can_accept': True,
            'estimated_arrival_hours': estimated_hours,
            'hours_after_trip': {
                'drive_hours': driver.hos_drive_hours_today + estimated_hours,
                'on_duty_hours': driver.hos_on_duty_hours_today + estimated_hours
            },
            'compliance': compliance
        }


class FreightBillingEngine:
    """Calculate and manage freight charges"""
    
    async def calculate_linehaul(
        self,
        distance_miles: float,
        weight_lbs: float,
        rate_per_mile: Optional[float] = None,
        rate_per_hundredweight: Optional[float] = None,
        contract_rates: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """Calculate linehaul charge"""
        if contract_rates:
            rate_per_mile = contract_rates.get('per_mile', rate_per_mile)
            rate_per_hundredweight = contract_rates.get('per_cwt', rate_per_hundredweight)
        
        # Default rates if not specified
        rate_per_mile = rate_per_mile or 2.50
        
        mileage_charge = distance_miles * rate_per_mile
        
        # Weight-based charge if applicable
        weight_charge = 0
        if rate_per_hundredweight:
            hundredweight = weight_lbs / 100
            weight_charge = hundredweight * rate_per_hundredweight
        
        total = mileage_charge + weight_charge
        
        return {
            'charge_type': 'linehaul',
            'rate_basis': 'per_mile' if not rate_per_hundredweight else 'combined',
            'distance_miles': distance_miles,
            'weight_lbs': weight_lbs,
            'mileage_charge': round(mileage_charge, 2),
            'weight_charge': round(weight_charge, 2),
            'amount': round(total, 2)
        }
    
    async def calculate_fuel_surcharge(
        self,
        distance_miles: float,
        base_fuel_price: float = 2.50,
        current_fuel_price: float = 3.50,
        mpg: float = 6.0,
        contract_rates: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """Calculate fuel surcharge"""
        if contract_rates and 'fuel_surcharge_table' in contract_rates:
            # Use contract-specific fuel surcharge table
            fsc_table = contract_rates['fuel_surcharge_table']
            # Implementation would look up based on current fuel price
            rate_per_mile = fsc_table.get('default', 0.45)
        else:
            # Standard calculation
            fuel_diff = max(0, current_fuel_price - base_fuel_price)
            gallons_needed = distance_miles / mpg
            rate_per_mile = (fuel_diff * gallons_needed) / distance_miles if distance_miles > 0 else 0
        
        amount = distance_miles * rate_per_mile
        
        return {
            'charge_type': 'fuel_surcharge',
            'rate_basis': 'per_mile',
            'distance_miles': distance_miles,
            'base_fuel_price': base_fuel_price,
            'current_fuel_price': current_fuel_price,
            'amount': round(amount, 2)
        }
    
    async def create_freight_charge(
        self,
        organization_id: UUID,
        shipment_id: UUID,
        charge_type: str,
        amount: float,
        carrier_id: Optional[UUID] = None,
        charge_description: Optional[str] = None,
        rate_basis: Optional[str] = None,
        quantity: Optional[float] = None,
        rate: Optional[float] = None,
        db: Optional[AsyncSession] = None
    ) -> FreightCharge:
        """Create a freight charge record"""
        async with (db or AsyncSessionLocal()) as session:
            charge = FreightCharge(
                organization_id=organization_id,
                shipment_id=shipment_id,
                carrier_id=carrier_id,
                charge_type=charge_type,
                charge_description=charge_description,
                rate_basis=rate_basis,
                quantity=quantity,
                rate=rate,
                amount=amount
            )
            session.add(charge)
            await session.commit()
            await session.refresh(charge)
            
            logger.info(
                "freight_charge_created",
                charge_id=str(charge.id),
                shipment_id=str(shipment_id),
                charge_type=charge_type,
                amount=amount
            )
            return charge


class RouteOptimizer:
    """Optimize routes for shipments"""
    
    def optimize_route(
        self,
        origin: Dict[str, Any],
        destination: Dict[str, Any],
        waypoints: Optional[List[Dict]] = None,
        optimization_criteria: str = 'balanced'
    ) -> Dict[str, Any]:
        """
        Optimize route based on criteria
        
        Note: This is a simplified implementation.
        In production, integrate with Google Maps, HERE, or similar API.
        """
        waypoints = waypoints or []
        
        # Simplified distance calculation (would use actual routing API)
        # This is placeholder logic
        total_distance = self._estimate_distance(origin, destination, waypoints)
        
        # Calculate estimated duration (avg 50 mph + stops)
        estimated_hours = total_distance / 50
        estimated_hours += len(waypoints) * 0.5  # 30 min per stop
        
        # Fuel cost estimate (6 mpg, $3.50/gal)
        fuel_gallons = total_distance / 6
        fuel_cost = fuel_gallons * 3.50
        
        # Toll estimate (simplified)
        toll_cost = total_distance * 0.05  # 5 cents per mile average
        
        return {
            'origin': origin,
            'destination': destination,
            'waypoints': waypoints,
            'total_distance_miles': round(total_distance, 1),
            'estimated_duration_hours': round(estimated_hours, 1),
            'fuel_cost_estimate': round(fuel_cost, 2),
            'toll_cost_estimate': round(toll_cost, 2),
            'optimization_criteria': optimization_criteria
        }
    
    def _estimate_distance(
        self,
        origin: Dict[str, Any],
        destination: Dict[str, Any],
        waypoints: List[Dict]
    ) -> float:
        """Distance in miles via the routing provider seam (app.services.routing).

        Real great-circle distance summed through waypoints (OSRM road distance
        when configured), accepting both {lat,lng} and {latitude,longitude}.
        """
        from app.services.routing import estimate_distance_miles
        return estimate_distance_miles(origin, destination, waypoints)


class TransportationManagementService:
    """Core transportation management operations"""
    
    def __init__(self):
        self.hos_monitor = HOSComplianceMonitor()
        self.billing_engine = FreightBillingEngine()
        self.route_optimizer = RouteOptimizer()
    
    async def create_carrier(
        self,
        organization_id: UUID,
        carrier_name: str,
        dot_number: Optional[str] = None,
        mc_number: Optional[str] = None,
        ctpat_certified: bool = False,
        insurance_on_file: bool = False,
        safety_rating: Optional[str] = None,
        csa_score: Optional[float] = None,
        contract_rate: Optional[Dict] = None,
        contact_info: Optional[Dict] = None,
        db: Optional[AsyncSession] = None
    ) -> Carrier:
        """Create new carrier profile"""
        async with (db or AsyncSessionLocal()) as session:
            carrier = Carrier(
                organization_id=organization_id,
                carrier_name=carrier_name,
                dot_number=dot_number,
                mc_number=mc_number,
                ctpat_certified=ctpat_certified,
                insurance_on_file=insurance_on_file,
                safety_rating=safety_rating,
                csa_score=csa_score,
                contract_rate=contract_rate or {},
                contact_info=contact_info or {}
            )
            session.add(carrier)
            await session.commit()
            await session.refresh(carrier)
            
            logger.info(
                "carrier_created",
                carrier_id=str(carrier.id),
                carrier_name=carrier_name
            )
            return carrier
    
    async def create_driver(
        self,
        organization_id: UUID,
        first_name: str,
        last_name: str,
        carrier_id: Optional[UUID] = None,
        license_number: Optional[str] = None,
        license_state: Optional[str] = None,
        cdl_class: Optional[str] = None,
        hazmat_endorsed: bool = False,
        medical_cert_expires: Optional[datetime] = None,
        eld_device_id: Optional[str] = None,
        phone: Optional[str] = None,
        email: Optional[str] = None,
        db: Optional[AsyncSession] = None
    ) -> Driver:
        """Create new driver profile"""
        async with (db or AsyncSessionLocal()) as session:
            driver = Driver(
                organization_id=organization_id,
                carrier_id=carrier_id,
                first_name=first_name,
                last_name=last_name,
                license_number=license_number,
                license_state=license_state,
                cdl_class=cdl_class,
                hazmat_endorsed=hazmat_endorsed,
                medical_cert_expires=medical_cert_expires,
                eld_device_id=eld_device_id,
                phone=phone,
                email=email
            )
            session.add(driver)
            await session.commit()
            await session.refresh(driver)
            
            logger.info(
                "driver_created",
                driver_id=str(driver.id),
                name=f"{first_name} {last_name}"
            )
            return driver
    
    async def create_shipment(
        self,
        organization_id: UUID,
        shipment_number: str,
        shipment_type: str,
        origin: Dict[str, Any],
        destination: Dict[str, Any],
        scheduled_pickup: Optional[datetime] = None,
        scheduled_delivery: Optional[datetime] = None,
        carrier_id: Optional[UUID] = None,
        driver_id: Optional[UUID] = None,
        trailer_id: Optional[UUID] = None,
        total_weight_lbs: Optional[float] = None,
        total_pieces: Optional[int] = None,
        hazmat: bool = False,
        temperature_required: bool = False,
        pro_number: Optional[str] = None,
        bol_number: Optional[str] = None,
        db: Optional[AsyncSession] = None
    ) -> Shipment:
        """Create new shipment"""
        async with (db or AsyncSessionLocal()) as session:
            shipment = Shipment(
                organization_id=organization_id,
                shipment_number=shipment_number,
                pro_number=pro_number,
                bol_number=bol_number,
                shipment_type=shipment_type,
                status='planned',
                origin=origin,
                destination=destination,
                scheduled_pickup=scheduled_pickup,
                scheduled_delivery=scheduled_delivery,
                carrier_id=carrier_id,
                driver_id=driver_id,
                trailer_id=trailer_id,
                total_weight_lbs=total_weight_lbs,
                total_pieces=total_pieces,
                hazmat=hazmat,
                temperature_required=temperature_required
            )
            session.add(shipment)
            await session.commit()
            await session.refresh(shipment)
            
            logger.info(
                "shipment_created",
                shipment_id=str(shipment.id),
                shipment_number=shipment_number,
                shipment_type=shipment_type
            )
            return shipment
    
    async def dispatch_shipment(
        self,
        shipment_id: UUID,
        driver_id: UUID,
        trailer_id: UUID,
        db: Optional[AsyncSession] = None
    ) -> Shipment:
        """Dispatch shipment to driver"""
        async with (db or AsyncSessionLocal()) as session:
            result = await session.execute(
                select(Shipment).where(Shipment.id == shipment_id)
            )
            shipment = result.scalar_one_or_none()
            
            if not shipment:
                raise ValueError("Shipment not found")
            
            # Check driver HOS compliance
            driver_result = await session.execute(
                select(Driver).where(Driver.id == driver_id)
            )
            driver = driver_result.scalar_one_or_none()
            
            if driver:
                hos_check = self.hos_monitor.check_compliance(driver)
                if not hos_check['is_compliant']:
                    raise ValueError(
                        f"Driver not compliant: {', '.join(hos_check['violations'])}"
                    )
            
            shipment.status = 'dispatched'
            shipment.driver_id = driver_id
            shipment.trailer_id = trailer_id
            
            await session.commit()
            await session.refresh(shipment)
            
            logger.info(
                "shipment_dispatched",
                shipment_id=str(shipment_id),
                driver_id=str(driver_id),
                trailer_id=str(trailer_id)
            )
            return shipment
    
    async def update_shipment_status(
        self,
        shipment_id: UUID,
        status: str,
        actual_pickup: Optional[datetime] = None,
        actual_delivery: Optional[datetime] = None,
        db: Optional[AsyncSession] = None
    ) -> Shipment:
        """Update shipment status"""
        async with (db or AsyncSessionLocal()) as session:
            result = await session.execute(
                select(Shipment).where(Shipment.id == shipment_id)
            )
            shipment = result.scalar_one_or_none()
            
            if not shipment:
                raise ValueError("Shipment not found")
            
            shipment.status = status
            if actual_pickup:
                shipment.actual_pickup = actual_pickup
            if actual_delivery:
                shipment.actual_delivery = actual_delivery
            
            await session.commit()
            await session.refresh(shipment)
            
            logger.info(
                "shipment_status_updated",
                shipment_id=str(shipment_id),
                status=status
            )
            return shipment
    
    async def create_route(
        self,
        organization_id: UUID,
        origin: Dict[str, Any],
        destination: Dict[str, Any],
        waypoints: Optional[List[Dict]] = None,
        route_name: Optional[str] = None,
        optimization_criteria: str = 'balanced',
        db: Optional[AsyncSession] = None
    ) -> Route:
        """Create optimized route"""
        async with (db or AsyncSessionLocal()) as session:
            # Optimize route
            optimization = self.route_optimizer.optimize_route(
                origin=origin,
                destination=destination,
                waypoints=waypoints,
                optimization_criteria=optimization_criteria
            )
            
            route = Route(
                organization_id=organization_id,
                route_name=route_name or f"Route {origin.get('city', 'Unknown')} to {destination.get('city', 'Unknown')}",
                origin=origin,
                destination=destination,
                waypoints=waypoints or [],
                total_distance_miles=optimization['total_distance_miles'],
                estimated_duration_hours=optimization['estimated_duration_hours'],
                fuel_cost_estimate=optimization['fuel_cost_estimate'],
                toll_cost_estimate=optimization['toll_cost_estimate'],
                optimization_criteria=optimization_criteria
            )
            session.add(route)
            await session.commit()
            await session.refresh(route)
            
            logger.info(
                "route_created",
                route_id=str(route.id),
                distance_miles=optimization['total_distance_miles']
            )
            return route
    
    async def create_load_plan(
        self,
        organization_id: UUID,
        shipment_id: UUID,
        trailer_id: Optional[UUID] = None,
        load_sequence: Optional[List[Dict]] = None,
        weight_distribution: Optional[Dict] = None,
        space_utilization_percent: Optional[float] = None,
        special_instructions: Optional[str] = None,
        planned_by: Optional[UUID] = None,
        db: Optional[AsyncSession] = None
    ) -> LoadPlan:
        """Create load plan for shipment"""
        async with (db or AsyncSessionLocal()) as session:
            load_plan = LoadPlan(
                organization_id=organization_id,
                shipment_id=shipment_id,
                trailer_id=trailer_id,
                load_sequence=load_sequence or [],
                weight_distribution=weight_distribution or {},
                space_utilization_percent=space_utilization_percent,
                special_instructions=special_instructions,
                planned_by=planned_by
            )
            session.add(load_plan)
            await session.commit()
            await session.refresh(load_plan)
            
            logger.info(
                "load_plan_created",
                load_plan_id=str(load_plan.id),
                shipment_id=str(shipment_id)
            )
            return load_plan
    
    async def get_driver_hos_status(
        self,
        driver_id: UUID,
        db: Optional[AsyncSession] = None
    ) -> Dict[str, Any]:
        """Get driver HOS compliance status"""
        async with (db or AsyncSessionLocal()) as session:
            result = await session.execute(
                select(Driver).where(Driver.id == driver_id)
            )
            driver = result.scalar_one_or_none()
            
            if not driver:
                raise ValueError("Driver not found")
            
            return self.hos_monitor.check_compliance(driver)
    
    async def get_carrier_compliance_summary(
        self,
        carrier_id: UUID,
        db: Optional[AsyncSession] = None
    ) -> Dict[str, Any]:
        """Get carrier compliance summary"""
        async with (db or AsyncSessionLocal()) as session:
            result = await session.execute(
                select(Carrier).where(Carrier.id == carrier_id)
            )
            carrier = result.scalar_one_or_none()
            
            if not carrier:
                raise ValueError("Carrier not found")
            
            # Get all drivers for carrier
            drivers_result = await session.execute(
                select(Driver).where(Driver.carrier_id == carrier_id)
            )
            drivers = drivers_result.scalars().all()
            
            # Check compliance for each driver
            hos_violations = 0
            expired_medical_certs = 0
            
            for driver in drivers:
                compliance = self.hos_monitor.check_compliance(driver)
                if not compliance['is_compliant']:
                    hos_violations += 1
                if driver.medical_cert_expires and driver.medical_cert_expires < datetime.utcnow():
                    expired_medical_certs += 1
            
            return {
                'carrier_id': str(carrier_id),
                'carrier_name': carrier.carrier_name,
                'ctpat_status': {
                    'certified': carrier.ctpat_certified,
                    'expires_at': carrier.ctpat_expires_at.isoformat() if carrier.ctpat_expires_at else None,
                    'is_valid': (
                        carrier.ctpat_certified and 
                        carrier.ctpat_expires_at and 
                        carrier.ctpat_expires_at > datetime.utcnow()
                    )
                },
                'insurance_status': {
                    'on_file': carrier.insurance_on_file,
                    'expires_at': carrier.insurance_expires_at.isoformat() if carrier.insurance_expires_at else None,
                    'is_valid': (
                        carrier.insurance_on_file and
                        carrier.insurance_expires_at and
                        carrier.insurance_expires_at > datetime.utcnow()
                    )
                },
                'safety_rating': carrier.safety_rating,
                'csa_score': float(carrier.csa_score) if carrier.csa_score else None,
                'driver_compliance': {
                    'total_drivers': len(drivers),
                    'hos_violations': hos_violations,
                    'expired_medical_certs': expired_medical_certs,
                    'compliant_drivers': len(drivers) - hos_violations
                },
                'overall_compliant': (
                    carrier.ctpat_certified and
                    carrier.insurance_on_file and
                    hos_violations == 0
                )
            }
    
    async def calculate_shipment_costs(
        self,
        shipment_id: UUID,
        db: Optional[AsyncSession] = None
    ) -> Dict[str, Any]:
        """Calculate all costs for a shipment"""
        async with (db or AsyncSessionLocal()) as session:
            result = await session.execute(
                select(Shipment).where(Shipment.id == shipment_id)
            )
            shipment = result.scalar_one_or_none()
            
            if not shipment:
                raise ValueError("Shipment not found")
            
            # Get route if assigned
            route = None
            if shipment.route_id:
                route_result = await session.execute(
                    select(Route).where(Route.id == shipment.route_id)
                )
                route = route_result.scalar_one_or_none()
            
            # Get carrier contract rates
            contract_rates = {}
            if shipment.carrier_id:
                carrier_result = await session.execute(
                    select(Carrier).where(Carrier.id == shipment.carrier_id)
                )
                carrier = carrier_result.scalar_one_or_none()
                if carrier:
                    contract_rates = carrier.contract_rate or {}
            
            distance = route.total_distance_miles if route else 500.0
            weight = shipment.total_weight_lbs or 0
            
            # Calculate linehaul
            linehaul = await self.billing_engine.calculate_linehaul(
                distance_miles=distance,
                weight_lbs=weight,
                contract_rates=contract_rates
            )
            
            # Calculate fuel surcharge
            fuel_surcharge = await self.billing_engine.calculate_fuel_surcharge(
                distance_miles=distance,
                contract_rates=contract_rates
            )
            
            total_cost = linehaul['amount'] + fuel_surcharge['amount']
            
            return {
                'shipment_id': str(shipment_id),
                'linehaul': linehaul,
                'fuel_surcharge': fuel_surcharge,
                'total_cost': round(total_cost, 2),
                'distance_miles': distance,
                'weight_lbs': weight
            }


# Global instance
transportation_management_service = TransportationManagementService()

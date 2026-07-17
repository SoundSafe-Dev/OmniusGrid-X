"""
Logistics Correlation Engine
Cross-references YMS/TMS data with manufacturing operations for compliance,
liability reduction, safety enhancement, and operational efficiency.
"""

from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Any, Tuple
from uuid import UUID
import structlog
from sqlalchemy import text, select, and_, or_, func, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import AsyncSessionLocal
from app.db.models import (
    YardTrailer, DockDoor, DockAppointment, DriverWaitTime,
    Shipment, Carrier, Driver, TruckAssetCorrelation, LoadQualityLog,
    Asset, Operation, Alarm, Telemetry
)
from app.services.yard_management import yard_management_service, DetentionCalculator
from app.services.transportation_management import transportation_management_service
from app.services.correlation_ai_engine import correlation_ai_engine
from app.models.domain_interaction import (
    DomainType,
    CorrelationScenario,
    CrossDomainLink,
    OperationalMetric
)

logger = structlog.get_logger()


class DockProductionSynchronizer:
    """Synchronize dock schedules with production forecasts"""
    
    async def sync_dock_with_production(
        self,
        appointment_id: UUID,
        db: Optional[AsyncSession] = None
    ) -> Dict[str, Any]:
        """Align dock appointment with production operation forecast"""
        async with (db or AsyncSessionLocal()) as session:
            # Get appointment
            appt_result = await session.execute(
                select(DockAppointment).where(DockAppointment.id == appointment_id)
            )
            appointment = appt_result.scalar_one_or_none()
            
            if not appointment:
                raise ValueError("Appointment not found")
            
            if not appointment.operation_id:
                return {
                    'appointment_id': str(appointment_id),
                    'sync_status': 'no_operation_linked',
                    'recommendation': 'Link to production operation for better sync'
                }
            
            # Get linked operation
            op_result = await session.execute(
                select(Operation).where(Operation.id == appointment.operation_id)
            )
            operation = op_result.scalar_one_or_none()
            
            if not operation:
                return {
                    'appointment_id': str(appointment_id),
                    'sync_status': 'operation_not_found',
                    'recommendation': 'Check operation linkage'
                }
            
            # Calculate readiness status
            if operation.completed_at:
                # Operation already done
                status = 'completed'
                estimated_completion = operation.completed_at
                risk_score = 0
            elif operation.started_at:
                # Operation in progress - estimate completion
                estimated_completion = await self._estimate_completion(
                    session, operation
                )
                
                if appointment.scheduled_start:
                    time_diff = (estimated_completion - appointment.scheduled_start).total_seconds() / 60
                    
                    if time_diff < -30:  # Will be ready 30+ min early
                        status = 'early'
                        risk_score = 10
                    elif time_diff < 15:  # Within acceptable window
                        status = 'on_time'
                        risk_score = 25
                    elif time_diff < 60:  # Up to 1 hour late
                        status = 'at_risk'
                        risk_score = 60
                    else:  # More than 1 hour late
                        status = 'late'
                        risk_score = 90
                else:
                    status = 'unknown'
                    risk_score = 50
            else:
                # Operation not started
                status = 'not_started'
                estimated_completion = await self._estimate_completion(
                    session, operation
                )
                
                if appointment.scheduled_start:
                    time_to_appointment = (appointment.scheduled_start - datetime.now(timezone.utc)).total_seconds() / 60
                    if time_to_appointment < 60:
                        risk_score = 80  # High risk - appointment soon but not started
                    else:
                        risk_score = 40
                else:
                    risk_score = 50
            
            # Update or create correlation record
            await self._update_correlation_record(
                session, appointment, operation, status, estimated_completion, risk_score
            )
            
            await session.commit()
            
            return {
                'appointment_id': str(appointment_id),
                'operation_id': str(operation.id),
                'sync_status': status,
                'estimated_completion': estimated_completion.isoformat() if estimated_completion else None,
                'scheduled_dock_time': appointment.scheduled_start.isoformat() if appointment.scheduled_start else None,
                'detention_risk_score': risk_score,
                'recommendations': self._generate_sync_recommendations(status, risk_score)
            }
    
    async def _estimate_completion(
        self,
        session: AsyncSession,
        operation: Operation
    ) -> datetime:
        """Estimate operation completion time based on telemetry and history"""
        if operation.completed_at:
            return operation.completed_at
        
        # Use planned duration if available
        if operation.planned_duration:
            if operation.started_at:
                return operation.started_at + timedelta(seconds=float(operation.planned_duration))
            else:
                # Not started yet - add to current time
                return datetime.now(timezone.utc) + timedelta(seconds=float(operation.planned_duration))
        
        # Default estimate: check asset performance
        result = await session.execute(
            select(func.avg(Operation.actual_duration)).where(
                and_(
                    Operation.asset_id == operation.asset_id,
                    Operation.status == 'completed',
                    Operation.completed_at > datetime.now(timezone.utc) - timedelta(days=30)
                )
            )
        )
        avg_duration = result.scalar() or 3600  # Default 1 hour
        
        if operation.started_at:
            return operation.started_at + timedelta(seconds=float(avg_duration))
        else:
            return datetime.now(timezone.utc) + timedelta(seconds=float(avg_duration))
    
    async def _update_correlation_record(
        self,
        session: AsyncSession,
        appointment: DockAppointment,
        operation: Operation,
        status: str,
        estimated_completion: Optional[datetime],
        risk_score: float
    ):
        """Update truck-asset correlation record"""
        result = await session.execute(
            select(TruckAssetCorrelation).where(
                and_(
                    TruckAssetCorrelation.shipment_id == appointment.shipment_id,
                    TruckAssetCorrelation.operation_id == operation.id
                )
            )
        )
        correlation = result.scalar_one_or_none()
        
        if correlation:
            correlation.asset_completion_forecast = estimated_completion
            correlation.efficiency_score = max(0, 100 - risk_score)
        else:
            correlation = TruckAssetCorrelation(
                organization_id=appointment.organization_id,
                shipment_id=appointment.shipment_id,
                trailer_id=appointment.trailer_id,
                asset_id=operation.asset_id,
                operation_id=operation.id,
                asset_completion_forecast=estimated_completion,
                efficiency_score=max(0, 100 - risk_score)
            )
            session.add(correlation)
    
    def _generate_sync_recommendations(self, status: str, risk_score: float) -> List[str]:
        """Generate recommendations based on sync status"""
        recommendations = []
        
        if status == 'late' or risk_score > 70:
            recommendations.append("Notify carrier of potential delay")
            recommendations.append("Consider requesting detention waiver")
        elif status == 'at_risk':
            recommendations.append("Monitor production closely")
            recommendations.append("Prepare backup dock door")
        elif status == 'early':
            recommendations.append("Notify carrier of early readiness")
            recommendations.append("Consider expediting truck arrival")
        
        return recommendations
    
    async def get_sync_dashboard(
        self,
        organization_id: UUID,
        date: Optional[datetime] = None,
        db: Optional[AsyncSession] = None
    ) -> Dict[str, Any]:
        """Get dock-production sync dashboard for date"""
        async with (db or AsyncSessionLocal()) as session:
            date = date or datetime.now(timezone.utc)
            start_of_day = date.replace(hour=0, minute=0, second=0, microsecond=0)
            end_of_day = start_of_day + timedelta(days=1)
            
            # Get all appointments for day
            result = await session.execute(
                select(DockAppointment).where(
                    and_(
                        DockAppointment.organization_id == organization_id,
                        DockAppointment.scheduled_start >= start_of_day,
                        DockAppointment.scheduled_start < end_of_day
                    )
                )
            )
            appointments = result.scalars().all()
            
            sync_status = {
                'on_time': 0,
                'early': 0,
                'at_risk': 0,
                'late': 0,
                'not_started': 0,
                'no_operation': 0
            }
            
            total_appointments = len(appointments)
            linked_appointments = 0
            
            for appt in appointments:
                if appt.operation_id:
                    linked_appointments += 1
                    # Run sync analysis
                    try:
                        sync = await self.sync_dock_with_production(appt.id, session)
                        status = sync.get('sync_status', 'unknown')
                        if status in sync_status:
                            sync_status[status] += 1
                        else:
                            sync_status['no_operation'] += 1
                    except Exception as e:
                        logger.warning(
                            "sync_analysis_failed",
                            appointment_id=str(appt.id),
                            error=str(e)
                        )
                else:
                    sync_status['no_operation'] += 1
            
            sync_percent = (
                (sync_status['on_time'] + sync_status['early']) / total_appointments * 100
                if total_appointments > 0 else 0
            )
            
            return {
                'date': date.date().isoformat(),
                'total_appointments': total_appointments,
                'linked_to_production': linked_appointments,
                'sync_status_breakdown': sync_status,
                'production_dock_sync_percent': round(sync_percent, 1),
                'at_risk_count': sync_status['at_risk'] + sync_status['late'],
                'early_count': sync_status['early']
            }


class DetentionRiskPredictor:
    """Predict detention risk for upcoming appointments"""
    
    async def predict_risk(
        self,
        appointment_id: UUID,
        db: Optional[AsyncSession] = None
    ) -> Dict[str, Any]:
        """Predict detention risk for an appointment"""
        async with (db or AsyncSessionLocal()) as session:
            # Get appointment details
            appt_result = await session.execute(
                select(DockAppointment).where(DockAppointment.id == appointment_id)
            )
            appointment = appt_result.scalar_one_or_none()
            
            if not appointment:
                raise ValueError("Appointment not found")
            
            risk_factors = []
            risk_score = 0
            
            # Factor 1: Production sync status
            if appointment.operation_id:
                sync_result = await session.execute(
                    select(TruckAssetCorrelation).where(
                        TruckAssetCorrelation.operation_id == appointment.operation_id
                    )
                )
                correlation = sync_result.scalar_one_or_none()
                
                if correlation and correlation.efficiency_score:
                    production_risk = 100 - correlation.efficiency_score
                    risk_score += production_risk * 0.4  # 40% weight
                    if production_risk > 50:
                        risk_factors.append(f"Production delay risk: {production_risk:.0f}%")
            
            # Factor 2: Carrier historical performance
            if appointment.carrier_id:
                carrier_result = await session.execute(
                    select(Carrier).where(Carrier.id == appointment.carrier_id)
                )
                carrier = carrier_result.scalar_one_or_none()
                
                if carrier and carrier.csa_score:
                    # Higher CSA score = more violations = higher risk
                    carrier_risk = min(100, carrier.csa_score * 2)
                    risk_score += carrier_risk * 0.2  # 20% weight
                    if carrier.csa_score > 50:
                        risk_factors.append(f"Carrier CSA score elevated: {carrier.csa_score}")
            
            # Factor 3: Historical detention at this facility
            historical_detention = await self._get_historical_detention_rate(
                session, appointment.organization_id, appointment.carrier_id
            )
            risk_score += historical_detention * 0.2  # 20% weight
            if historical_detention > 30:
                risk_factors.append(f"Historical detention rate: {historical_detention:.0f}%")
            
            # Factor 4: Time of day (peak hours = more risk)
            if appointment.scheduled_start:
                hour = appointment.scheduled_start.hour
                if 8 <= hour <= 10 or 14 <= hour <= 16:  # Peak hours
                    risk_score += 10
                    risk_factors.append("Peak hour appointment")
            
            # Factor 5: Priority level
            if appointment.priority == 'critical':
                risk_score += 5  # Critical loads have less flexibility
            
            # Calculate predicted detention time
            predicted_minutes = 0
            if risk_score > 75:
                predicted_minutes = 120  # 2 hours
            elif risk_score > 50:
                predicted_minutes = 60  # 1 hour
            elif risk_score > 25:
                predicted_minutes = 30  # 30 minutes
            
            # Determine risk level
            if risk_score >= 75:
                risk_level = 'critical'
            elif risk_score >= 50:
                risk_level = 'high'
            elif risk_score >= 25:
                risk_level = 'medium'
            else:
                risk_level = 'low'
            
            recommendations = self._generate_risk_recommendations(
                risk_level, risk_factors
            )
            
            return {
                'appointment_id': str(appointment_id),
                'risk_score': round(risk_score, 1),
                'risk_level': risk_level,
                'factors': risk_factors,
                'predicted_detention_minutes': predicted_minutes,
                'recommended_actions': recommendations
            }
    
    async def _get_historical_detention_rate(
        self,
        session: AsyncSession,
        organization_id: UUID,
        carrier_id: Optional[UUID]
    ) -> float:
        """Get historical detention rate for facility/carrier"""
        query = """
            SELECT 
                COUNT(*) as total,
                SUM(CASE WHEN detention_charge > 0 THEN 1 ELSE 0 END) as detention_count
            FROM driver_wait_times
            WHERE organization_id = :org_id
            AND check_in_at > NOW() - INTERVAL '30 days'
        """
        
        params = {'org_id': str(organization_id)}
        
        if carrier_id:
            # Need to join with drivers to get carrier
            query = """
                SELECT 
                    COUNT(*) as total,
                    SUM(CASE WHEN dwt.detention_charge > 0 THEN 1 ELSE 0 END) as detention_count
                FROM driver_wait_times dwt
                JOIN drivers d ON d.id = dwt.driver_id
                WHERE dwt.organization_id = :org_id
                AND d.carrier_id = :carrier_id
                AND dwt.check_in_at > NOW() - INTERVAL '30 days'
            """
            params['carrier_id'] = str(carrier_id)
        
        result = await session.execute(text(query), params)
        row = result.fetchone()
        
        if row and row.total > 0:
            return (row.detention_count or 0) / row.total * 100
        return 10.0  # Default 10% assumption
    
    def _generate_risk_recommendations(
        self,
        risk_level: str,
        factors: List[str]
    ) -> List[str]:
        """Generate recommendations based on risk level"""
        recommendations = []
        
        if risk_level == 'critical':
            recommendations.append("Contact carrier immediately to discuss delay protocols")
            recommendations.append("Pre-authorize detention charges with finance")
            recommendations.append("Consider expedited production for this load")
        elif risk_level == 'high':
            recommendations.append("Monitor production status hourly")
            recommendations.append("Alert yard supervisor of potential congestion")
            recommendations.append("Prepare backup dock assignment")
        elif risk_level == 'medium':
            recommendations.append("Include in daily operations briefing")
            recommendations.append("Track carrier ETA closely")
        
        return recommendations


class LoadQualityCorrelator:
    """Correlate shipping defects to manufacturing root causes"""
    
    async def log_quality_issue(
        self,
        organization_id: UUID,
        shipment_id: UUID,
        defect_type: str,
        severity: str,
        quantity_affected: float,
        asset_id: Optional[UUID] = None,
        operation_id: Optional[UUID] = None,
        carrier_liable: bool = False,
        db: Optional[AsyncSession] = None
    ) -> LoadQualityLog:
        """Log a quality issue and correlate to manufacturing"""
        async with (db or AsyncSessionLocal()) as session:
            # Analyze root cause if manufacturing data available
            root_cause_analysis = await self._analyze_root_cause(
                session, asset_id, operation_id, defect_type
            )
            
            log = LoadQualityLog(
                organization_id=organization_id,
                shipment_id=shipment_id,
                asset_id=asset_id,
                operation_id=operation_id,
                defect_type=defect_type,
                severity=severity,
                quantity_affected=quantity_affected,
                root_cause_asset=root_cause_analysis.get('root_cause_asset'),
                root_cause_operation=root_cause_analysis.get('root_cause_operation'),
                manufacturing_correlation_score=root_cause_analysis.get('correlation_score'),
                carrier_liable=carrier_liable
            )
            session.add(log)
            await session.commit()
            await session.refresh(log)
            
            logger.info(
                "quality_issue_logged",
                log_id=str(log.id),
                shipment_id=str(shipment_id),
                defect_type=defect_type,
                correlation_score=root_cause_analysis.get('correlation_score')
            )
            return log
    
    async def _analyze_root_cause(
        self,
        session: AsyncSession,
        asset_id: Optional[UUID],
        operation_id: Optional[UUID],
        defect_type: str
    ) -> Dict[str, Any]:
        """Analyze root cause correlation"""
        result = {
            'root_cause_asset': asset_id,
            'root_cause_operation': operation_id,
            'correlation_score': 0.5  # Default moderate correlation
        }
        
        if not asset_id:
            return result
        
        # Check for alarms on asset during operation
        if operation_id:
            op_result = await session.execute(
                select(Operation).where(Operation.id == operation_id)
            )
            operation = op_result.scalar_one_or_none()
            
            if operation and operation.started_at:
                time_window_start = operation.started_at
                time_window_end = operation.completed_at or datetime.now(timezone.utc)
                
                # Count critical alarms during operation
                alarm_result = await session.execute(
                    select(func.count(Alarm.id)).where(
                        and_(
                            Alarm.asset_id == asset_id,
                            Alarm.severity == 'critical',
                            Alarm.occurred_at >= time_window_start,
                            Alarm.occurred_at <= time_window_end
                        )
                    )
                )
                critical_alarms = alarm_result.scalar() or 0
                
                # Count telemetry anomalies
                # (simplified - would do actual anomaly detection)
                
                # Increase correlation score if alarms occurred
                if critical_alarms > 0:
                    result['correlation_score'] = min(0.95, 0.5 + (critical_alarms * 0.15))
                
                # Check for similar defects from this asset/operation combo
                similar_result = await session.execute(
                    select(func.count(LoadQualityLog.id)).where(
                        and_(
                            LoadQualityLog.root_cause_asset == asset_id,
                            LoadQualityLog.root_cause_operation == operation_id,
                            LoadQualityLog.defect_type == defect_type
                        )
                    )
                )
                similar_count = similar_result.scalar() or 0
                
                if similar_count > 0:
                    result['correlation_score'] = min(0.95, result['correlation_score'] + 0.1)
        
        return result
    
    async def get_quality_analytics(
        self,
        organization_id: UUID,
        start_date: datetime,
        end_date: datetime,
        db: Optional[AsyncSession] = None
    ) -> Dict[str, Any]:
        """Get quality correlation analytics"""
        async with (db or AsyncSessionLocal()) as session:
            # Get all quality issues in date range
            result = await session.execute(
                select(LoadQualityLog).where(
                    and_(
                        LoadQualityLog.organization_id == organization_id,
                        LoadQualityLog.created_at >= start_date,
                        LoadQualityLog.created_at <= end_date
                    )
                )
            )
            issues = result.scalars().all()
            
            # Aggregate by defect type
            defect_types = {}
            manufacturing_liability = 0.0
            carrier_liability = 0.0
            
            for issue in issues:
                if issue.defect_type not in defect_types:
                    defect_types[issue.defect_type] = {
                        'count': 0,
                        'total_quantity': 0,
                        'avg_correlation_score': 0
                    }
                
                defect_types[issue.defect_type]['count'] += 1
                defect_types[issue.defect_type]['total_quantity'] += float(issue.quantity_affected or 0)
                
                if issue.manufacturing_correlation_score:
                    defect_types[issue.defect_type]['avg_correlation_score'] = (
                        defect_types[issue.defect_type]['avg_correlation_score'] + 
                        float(issue.manufacturing_correlation_score)
                    ) / 2
                
                # Track liability
                if issue.carrier_liable:
                    carrier_liability += float(issue.claim_amount or 0)
                else:
                    manufacturing_liability += float(issue.claim_amount or 0)
            
            # Get top problem assets
            asset_result = await session.execute(
                select(
                    LoadQualityLog.root_cause_asset,
                    func.count(LoadQualityLog.id).label('issue_count'),
                    func.sum(LoadQualityLog.quantity_affected).label('total_qty')
                ).where(
                    and_(
                        LoadQualityLog.organization_id == organization_id,
                        LoadQualityLog.created_at >= start_date,
                        LoadQualityLog.created_at <= end_date,
                        LoadQualityLog.root_cause_asset.isnot(None)
                    )
                ).group_by(LoadQualityLog.root_cause_asset)
                .order_by(desc('issue_count'))
                .limit(5)
            )
            top_assets = [
                {
                    'asset_id': str(row.root_cause_asset),
                    'issue_count': row.issue_count,
                    'total_quantity_affected': float(row.total_qty or 0)
                }
                for row in asset_result.fetchall()
            ]
            
            return {
                'total_issues': len(issues),
                'defect_breakdown': defect_types,
                'manufacturing_liability': round(manufacturing_liability, 2),
                'carrier_liability': round(carrier_liability, 2),
                'total_claims': round(manufacturing_liability + carrier_liability, 2),
                'top_problem_assets': top_assets
            }


class LogisticsCorrelationEngine:
    """Main correlation engine service"""
    
    def __init__(self):
        self.dock_sync = DockProductionSynchronizer()
        self.risk_predictor = DetentionRiskPredictor()
        self.quality_correlator = LoadQualityCorrelator()
        self.ai_engine = correlation_ai_engine
    
    async def convert_to_correlation_scenario(
        self,
        organization_id: UUID,
        appointment_id: Optional[UUID] = None,
        shipment_id: Optional[UUID] = None,
        asset_id: Optional[UUID] = None,
        db: Optional[AsyncSession] = None
    ) -> CorrelationScenario:
        """
        Convert real-time API data into CorrelationScenario format for AI analysis.
        
        Args:
            organization_id: Organization ID
            appointment_id: Optional dock appointment ID
            shipment_id: Optional shipment ID
            asset_id: Optional asset ID
            db: Database session
            
        Returns:
            CorrelationScenario ready for AI analysis
        """
        async with (db or AsyncSessionLocal()) as session:
            scenario_id = f"SCENARIO_LIVE_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
            active_domains = []
            domain_links = []
            ingested_metrics = []
            
            # Collect data based on provided IDs
            if appointment_id:
                # Get appointment data
                appt_result = await session.execute(
                    select(DockAppointment).where(DockAppointment.id == appointment_id)
                )
                appointment = appt_result.scalar_one_or_none()
                
                if appointment:
                    active_domains.append(DomainType.LOG)
                    ingested_metrics.append(OperationalMetric(
                        endpoint="/api/v1/logistics/dock-production-sync",
                        payload_snapshot={
                            "appointment_id": str(appointment.id),
                            "scheduled_start": appointment.scheduled_start.isoformat() if appointment.scheduled_start else None,
                            "status": appointment.status
                        }
                    ))
            
            if asset_id:
                # Get asset data
                asset_result = await session.execute(
                    select(Asset).where(Asset.id == asset_id)
                )
                asset = asset_result.scalar_one_or_none()
                
                if asset:
                    active_domains.append(DomainType.PROD)
                    ingested_metrics.append(OperationalMetric(
                        endpoint="/api/v1/oee/current/" + str(asset_id),
                        payload_snapshot={
                            "asset_id": str(asset.id),
                            "asset_name": asset.name,
                            "packml_state": asset.current_packml_state
                        }
                    ))
            
            if shipment_id:
                # Get shipment data
                shipment_result = await session.execute(
                    select(Shipment).where(Shipment.id == shipment_id)
                )
                shipment = shipment_result.scalar_one_or_none()
                
                if shipment:
                    active_domains.append(DomainType.LOG)
                    ingested_metrics.append(OperationalMetric(
                        endpoint="/api/v1/transportation/shipments/" + str(shipment_id),
                        payload_snapshot={
                            "shipment_number": shipment.shipment_number,
                            "status": shipment.status,
                            "priority": shipment.priority
                        }
                    ))
            
            # Create domain links if multiple domains
            if len(active_domains) > 1:
                for i in range(len(active_domains) - 1):
                    domain_links.append(CrossDomainLink(
                        source_domain=active_domains[i],
                        target_domain=active_domains[i + 1],
                        interaction_key=str(shipment_id or asset_id or appointment_id),
                        severity_impact=0.7,
                        correlation_type="temporal"
                    ))
            
            return CorrelationScenario(
                scenario_id=scenario_id,
                active_domains=active_domains,
                domain_links=domain_links,
                ingested_metrics=ingested_metrics
            )
    
    async def analyze_with_ai(
        self,
        organization_id: UUID,
        appointment_id: Optional[UUID] = None,
        shipment_id: Optional[UUID] = None,
        asset_id: Optional[UUID] = None,
        db: Optional[AsyncSession] = None
    ) -> Dict[str, Any]:
        """
        Run AI correlation analysis on real-time data.
        
        Args:
            organization_id: Organization ID
            appointment_id: Optional dock appointment ID
            shipment_id: Optional shipment ID
            asset_id: Optional asset ID
            db: Database session
            
        Returns:
            AI analysis results
        """
        # Convert to CorrelationScenario
        scenario = await self.convert_to_correlation_scenario(
            organization_id=organization_id,
            appointment_id=appointment_id,
            shipment_id=shipment_id,
            asset_id=asset_id,
            db=db
        )
        
        # Run AI analysis
        analysis = await self.ai_engine.analyze_scenario(scenario, db)
        
        return analysis
    
    async def get_correlation_dashboard(
        self,
        organization_id: UUID,
        date: Optional[datetime] = None,
        db: Optional[AsyncSession] = None
    ) -> Dict[str, Any]:
        """Get comprehensive correlation dashboard"""
        async with (db or AsyncSessionLocal()) as session:
            date = date or datetime.now(timezone.utc)
            start_of_day = date.replace(hour=0, minute=0, second=0, microsecond=0)
            end_of_day = start_of_day + timedelta(days=1)
            
            # Get dock sync metrics
            sync_metrics = await self.dock_sync.get_sync_dashboard(
                organization_id, date, session
            )
            
            # Get truck arrival metrics
            arrivals_result = await session.execute(
                select(func.count(YardTrailer.id)).where(
                    and_(
                        YardTrailer.organization_id == organization_id,
                        YardTrailer.check_in_at >= start_of_day,
                        YardTrailer.check_in_at < end_of_day
                    )
                )
            )
            truck_arrivals = arrivals_result.scalar() or 0
            
            # Get detention charges for day
            detention_result = await session.execute(
                select(func.sum(DriverWaitTime.detention_charge)).where(
                    and_(
                        DriverWaitTime.organization_id == organization_id,
                        DriverWaitTime.check_in_at >= start_of_day,
                        DriverWaitTime.check_in_at < end_of_day
                    )
                )
            )
            total_detention = detention_result.scalar() or 0.0
            
            # Get dwell time average
            dwell_result = await session.execute(
                select(
                    func.avg(
                        func.extract(
                            'epoch', 
                            func.coalesce(YardTrailer.check_out_at, func.now()) - YardTrailer.check_in_at
                        ) / 3600
                    )
                ).where(
                    and_(
                        YardTrailer.organization_id == organization_id,
                        YardTrailer.check_in_at >= start_of_day - timedelta(days=7)  # Last 7 days avg
                    )
                )
            )
            avg_dwell = dwell_result.scalar() or 0.0
            
            # Get HOS violations
            hos_violations = await session.execute(
                select(func.count(Driver.id)).where(
                    and_(
                        Driver.organization_id == organization_id,
                        or_(
                            Driver.hos_drive_hours_today > 11,
                            Driver.hos_on_duty_hours_today > 14
                        )
                    )
                )
            )
            hos_count = hos_violations.scalar() or 0
            
            # Get quality issues
            quality_result = await session.execute(
                select(func.count(LoadQualityLog.id)).where(
                    and_(
                        LoadQualityLog.organization_id == organization_id,
                        LoadQualityLog.created_at >= start_of_day,
                        LoadQualityLog.created_at < end_of_day
                    )
                )
            )
            quality_issues = quality_result.scalar() or 0
            
            return {
                'date': date.date().isoformat(),
                'truck_arrivals_today': truck_arrivals,
                'production_dock_sync_percent': sync_metrics['production_dock_sync_percent'],
                'at_risk_appointments': sync_metrics['at_risk_count'],
                'avg_dwell_time_hours': round(float(avg_dwell), 2),
                'total_detention_charges': round(float(total_detention), 2),
                'hos_violations': hos_count,
                'quality_issues_today': quality_issues,
                'sync_breakdown': sync_metrics['sync_status_breakdown']
            }
    
    async def optimize_truck_asset_assignment(
        self,
        organization_id: UUID,
        shipment_id: UUID,
        db: Optional[AsyncSession] = None
    ) -> Dict[str, Any]:
        """Find optimal asset-truck assignment to minimize detention"""
        async with (db or AsyncSessionLocal()) as session:
            # Get shipment details
            shipment_result = await session.execute(
                select(Shipment).where(Shipment.id == shipment_id)
            )
            shipment = shipment_result.scalar_one_or_none()
            
            if not shipment:
                raise ValueError("Shipment not found")
            
            # Get available assets that match shipment requirements
            asset_result = await session.execute(
                select(Asset).where(
                    and_(
                        Asset.organization_id == organization_id,
                        Asset.is_active == True,
                        or_(
                            Asset.current_packml_state == 'Idle',
                            Asset.current_packml_state == 'Complete'
                        )
                    )
                )
            )
            available_assets = asset_result.scalars().all()
            
            # Score each asset for this shipment
            scored_assets = []
            for asset in available_assets:
                score = await self._score_asset_for_shipment(
                    session, asset, shipment
                )
                scored_assets.append({
                    'asset_id': str(asset.id),
                    'asset_name': asset.name,
                    'score': score['score'],
                    'estimated_ready_time': score['estimated_ready_time'],
                    'factors': score['factors']
                })
            
            # Sort by score (highest first)
            scored_assets.sort(key=lambda x: x['score'], reverse=True)
            
            return {
                'shipment_id': str(shipment_id),
                'optimal_assets': scored_assets[:5],
                'recommendation': (
                    f"Assign to asset {scored_assets[0]['asset_name']}" 
                    if scored_assets else "No suitable assets found"
                )
            }
    
    async def _score_asset_for_shipment(
        self,
        session: AsyncSession,
        asset: Asset,
        shipment: Shipment
    ) -> Dict[str, Any]:
        """Score an asset for a specific shipment"""
        score = 50  # Base score
        factors = []
        
        # Check current state
        if asset.current_packml_state == 'Idle':
            score += 30
            estimated_ready = datetime.now(timezone.utc)
            factors.append("Asset idle and ready")
        elif asset.current_packml_state == 'Complete':
            score += 20
            estimated_ready = datetime.now(timezone.utc)
            factors.append("Previous job complete")
        else:
            # Get current operation
            op_result = await session.execute(
                select(Operation).where(
                    and_(
                        Operation.asset_id == asset.id,
                        Operation.status.in_(['running', 'paused'])
                    )
                ).order_by(desc(Operation.started_at))
            )
            current_op = op_result.scalar_one_or_none()
            
            if current_op:
                estimated_ready = await self.dock_sync._estimate_completion(
                    session, current_op
                )
                minutes_to_ready = (estimated_ready - datetime.now(timezone.utc)).total_seconds() / 60
                
                if minutes_to_ready < 30:
                    score += 10
                    factors.append(f"Completes in {minutes_to_ready:.0f} min")
                elif minutes_to_ready < 60:
                    score += 0
                    factors.append(f"Completes in {minutes_to_ready:.0f} min")
                else:
                    score -= 20
                    factors.append(f"Busy for {minutes_to_ready:.0f} min")
            else:
                estimated_ready = datetime.now(timezone.utc)
        
        # Check historical quality issues
        quality_result = await session.execute(
            select(func.count(LoadQualityLog.id)).where(
                and_(
                    LoadQualityLog.root_cause_asset == asset.id,
                    LoadQualityLog.created_at > datetime.now(timezone.utc) - timedelta(days=30)
                )
            )
        )
        recent_issues = quality_result.scalar() or 0
        
        if recent_issues == 0:
            score += 15
            factors.append("No quality issues in 30 days")
        else:
            score -= recent_issues * 5
            factors.append(f"{recent_issues} quality issues recently")
        
        # Check asset OEE (would need actual OEE calculation)
        # For now, use placeholder
        
        return {
            'score': max(0, min(100, score)),
            'estimated_ready_time': estimated_ready.isoformat(),
            'factors': factors
        }


# Global instance
logistics_correlation_engine = LogisticsCorrelationEngine()

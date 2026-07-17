"""
Oracle Correlation Patterns

Correlation patterns for Oracle Cloud ERP-specific scenarios:
- Financial anomaly detection (invoice fraud, payment delays)
- Supply chain correlations (shipments + logistics)
- HR correlations (employee + access control)
- Project correlations (project + operational data)
"""

from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta, timezone
import structlog
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_

from app.db.models import (
    ERPEntity,
    ERPCorrelation,
    ERPIntegrationEvent
)

logger = structlog.get_logger()


class OracleCorrelationPatterns:
    """
    Oracle ERP correlation patterns for detecting anomalies and insights.
    
    Maps Oracle events to operational domains and creates
    correlation patterns with sensor data.
    """
    
    # Domain mappings for Oracle entities
    ORACLE_DOMAIN_MAPPINGS = {
        "Invoice": "FINANCE",
        "Shipment": "LOGISTICS_FLEET",
        "Employee": "HR",
        "Project": "PROJECT_MANAGEMENT"
    }
    
    def __init__(self, organization_id: str, integration_id: str):
        self.organization_id = organization_id
        self.integration_id = integration_id
        
        logger.info(
            "oracle_correlation_patterns_initialized",
            organization_id=organization_id,
            integration_id=integration_id
        )
    
    async def analyze_invoice_anomalies(
        self,
        db: AsyncSession,
        invoice_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Analyze invoice for financial anomalies.
        
        Args:
            db: Database session
            invoice_data: Invoice data
            
        Returns:
            Dict with anomaly analysis results
        """
        anomalies = []
        risk_score = 0
        
        # Check for overdue invoices
        if invoice_data.get("due_date"):
            due_date = datetime.fromisoformat(invoice_data["due_date"])
            if due_date < datetime.now(timezone.utc) and invoice_data.get("status") != "paid":
                anomalies.append({
                    "type": "overdue_invoice",
                    "severity": "high",
                    "message": f"Invoice {invoice_data.get('invoice_number')} is overdue"
                })
                risk_score += 30
        
        # Check for unusual amount
        if invoice_data.get("total_amount"):
            # Compare with historical average for this supplier
            avg_amount = await self._get_supplier_avg_invoice_amount(
                db,
                invoice_data.get("supplier_id")
            )
            
            if avg_amount and invoice_data["total_amount"] > avg_amount * 5:
                anomalies.append({
                    "type": "unusual_amount",
                    "severity": "high",
                    "message": f"Invoice amount {invoice_data['total_amount']} is 5x above average for supplier"
                })
                risk_score += 40
        
        # Check for duplicate invoices
        duplicate_check = await self._check_duplicate_invoice(
            db,
            invoice_data.get("invoice_number"),
            invoice_data.get("supplier_id")
        )
        
        if duplicate_check:
            anomalies.append({
                "type": "duplicate_invoice",
                "severity": "critical",
                "message": f"Potential duplicate invoice {invoice_data.get('invoice_number')}"
            })
            risk_score += 50
        
        # Create correlation record if anomalies found
        if anomalies:
            await self._create_correlation(
                db,
                "financial_anomaly",
                invoice_data,
                risk_score,
                {"anomalies": anomalies}
            )
        
        logger.info(
            "oracle_invoice_anomaly_analysis_completed",
            invoice_number=invoice_data.get("invoice_number"),
            anomaly_count=len(anomalies),
            risk_score=risk_score
        )
        
        return {
            "invoice_number": invoice_data.get("invoice_number"),
            "anomalies": anomalies,
            "risk_score": risk_score,
            "requires_action": risk_score > 50
        }
    
    async def analyze_shipment_correlation(
        self,
        db: AsyncSession,
        shipment_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Correlate shipment data with logistics operations.
        
        Args:
            db: Database session
            shipment_data: Shipment data
            
        Returns:
            Dict with correlation analysis results
        """
        correlations = []
        
        # Check for delayed shipments
        if shipment_data.get("expected_delivery"):
            expected_delivery = datetime.fromisoformat(shipment_data["expected_delivery"])
            if expected_delivery < datetime.now(timezone.utc) and shipment_data.get("status") != "delivered":
                correlations.append({
                    "type": "shipment_delay",
                    "severity": "high",
                    "message": f"Shipment {shipment_data.get('shipment_number')} is delayed"
                })
        
        # Check for shipment in transit without recent updates
        if shipment_data.get("status") == "in_transit":
            # Check if shipment has been in transit too long
            ship_date = shipment_data.get("ship_date")
            if ship_date:
                ship_datetime = datetime.fromisoformat(ship_date)
                days_in_transit = (datetime.now(timezone.utc) - ship_datetime).days
                
                if days_in_transit > 14:  # 2 weeks threshold
                    correlations.append({
                        "type": "long_transit_time",
                        "severity": "medium",
                        "message": f"Shipment in transit for {days_in_transit} days"
                    })
        
        # Correlate with yard management if destination is a warehouse
        if shipment_data.get("destination"):
            # Check if there's a dock appointment for this shipment
            dock_correlation = await self._check_dock_appointment(
                db,
                shipment_data.get("shipment_number")
            )
            
            if dock_correlation:
                correlations.append({
                    "type": "dock_appointment",
                    "message": f"Shipment has dock appointment scheduled",
                    "appointment": dock_correlation
                })
        
        logger.info(
            "oracle_shipment_correlation_completed",
            shipment_number=shipment_data.get("shipment_number"),
            correlation_count=len(correlations)
        )
        
        return {
            "shipment_number": shipment_data.get("shipment_number"),
            "correlations": correlations
        }
    
    async def analyze_employee_correlation(
        self,
        db: AsyncSession,
        employee_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Correlate employee data with access control and HR data.
        
        Args:
            db: Database session
            employee_data: Employee data
            
        Returns:
            Dict with correlation analysis results
        """
        correlations = []
        
        # Check for inactive employees with recent access
        if not employee_data.get("is_active"):
            recent_access = await self._check_recent_access(
                db,
                employee_data.get("employee_id")
            )
            
            if recent_access:
                correlations.append({
                    "type": "inactive_employee_access",
                    "severity": "high",
                    "message": "Inactive employee has recent access events",
                    "access_events": recent_access
                })
        
        # Check for overtime patterns
        overtime_anomalies = await self._check_overtime_anomalies(
            db,
            employee_data.get("employee_id")
        )
        
        if overtime_anomalies:
            correlations.append({
                "type": "overtime_anomaly",
                "severity": "medium",
                "message": "Employee has unusual overtime patterns",
                "anomalies": overtime_anomalies
            })
        
        logger.info(
            "oracle_employee_correlation_completed",
            employee_id=employee_data.get("employee_id"),
            correlation_count=len(correlations)
        )
        
        return {
            "employee_id": employee_data.get("employee_id"),
            "correlations": correlations
        }
    
    async def analyze_project_correlation(
        self,
        db: AsyncSession,
        project_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Correlate project data with operational data.
        
        Args:
            db: Database session
            project_data: Project data
            
        Returns:
            Dict with correlation analysis results
        """
        correlations = []
        
        # Check for budget overruns
        if project_data.get("budget"):
            # Compare with actual spend (would need to query financial data)
            # For now, just flag if project is near end date
            if project_data.get("end_date"):
                end_date = datetime.fromisoformat(project_data["end_date"])
                days_remaining = (end_date - datetime.now(timezone.utc)).days
                
                if days_remaining < 30 and project_data.get("status") == "executing":
                    correlations.append({
                        "type": "project_deadline",
                        "severity": "high",
                        "message": f"Project ending in {days_remaining} days, status still executing"
                    })
        
        # Check for projects on hold
        if project_data.get("status") == "on_hold":
            correlations.append({
                "type": "project_on_hold",
                "severity": "medium",
                "message": "Project is currently on hold"
            })
        
        logger.info(
            "oracle_project_correlation_completed",
            project_id=project_data.get("project_id"),
            correlation_count=len(correlations)
        )
        
        return {
            "project_id": project_data.get("project_id"),
            "correlations": correlations
        }
    
    async def analyze_cash_flow_correlation(
        self,
        db: AsyncSession,
        time_period: str = "30d"
    ) -> Dict[str, Any]:
        """
        Analyze cash flow by correlating invoices and payments.
        
        Args:
            db: Database session
            time_period: Time period to analyze (e.g., "30d", "90d")
            
        Returns:
            Dict with cash flow analysis results
        """
        # Calculate time period
        days = int(time_period.replace("d", ""))
        start_date = datetime.now(timezone.utc) - timedelta(days=days)
        
        # Get invoices in period
        result = await db.execute(
            select(ERPEntity).where(
                and_(
                    ERPEntity.entity_type == "Invoice",
                    ERPEntity.created_at >= start_date,
                    ERPEntity.is_active == True
                )
            )
        )
        invoices = result.scalars().all()
        
        # Calculate metrics
        total_invoiced = sum(
            inv.entity_data.get("total_amount", 0)
            for inv in invoices
        )
        
        overdue_invoices = [
            inv for inv in invoices
            if inv.entity_data.get("status") == "overdue"
        ]
        
        overdue_amount = sum(
            inv.entity_data.get("total_amount", 0)
            for inv in overdue_invoices
        )
        
        paid_invoices = [
            inv for inv in invoices
            if inv.entity_data.get("status") == "paid"
        ]
        
        paid_amount = sum(
            inv.entity_data.get("total_amount", 0)
            for inv in paid_invoices
        )
        
        # Cash flow health
        cash_flow_health = "healthy"
        if overdue_amount > total_invoiced * 0.2:
            cash_flow_health = "at_risk"
        if overdue_amount > total_invoiced * 0.4:
            cash_flow_health = "critical"
        
        logger.info(
            "oracle_cash_flow_analysis_completed",
            time_period=time_period,
            total_invoiced=total_invoiced,
            overdue_amount=overdue_amount,
            cash_flow_health=cash_flow_health
        )
        
        return {
            "time_period": time_period,
            "total_invoiced": total_invoiced,
            "overdue_amount": overdue_amount,
            "overdue_count": len(overdue_invoices),
            "paid_amount": paid_amount,
            "paid_count": len(paid_invoices),
            "cash_flow_health": cash_flow_health,
            "requires_action": cash_flow_health in ["at_risk", "critical"]
        }
    
    async def _create_correlation(
        self,
        db: AsyncSession,
        correlation_type: str,
        erp_event: Dict[str, Any],
        correlation_score: float,
        metadata: Dict[str, Any]
    ):
        """
        Create a correlation record.
        
        Args:
            db: Database session
            correlation_type: Type of correlation
            erp_event: ERP event data
            correlation_score: Correlation confidence score
            metadata: Additional metadata
        """
        correlation = ERPCorrelation(
            organization_id=self.organization_id,
            correlation_type=correlation_type,
            correlation_score=correlation_score,
            correlation_metadata=metadata,
            created_at=datetime.now(timezone.utc)
        )
        
        db.add(correlation)
        await db.commit()
    
    async def _get_supplier_avg_invoice_amount(
        self,
        db: AsyncSession,
        supplier_id: str
    ) -> Optional[float]:
        """Get average invoice amount for supplier."""
        result = await db.execute(
            select(ERPEntity).where(
                and_(
                    ERPEntity.entity_type == "Invoice",
                    ERPEntity.entity_data["supplier_id"].astext == supplier_id,
                    ERPEntity.is_active == True
                )
            )
        )
        invoices = result.scalars().all()
        
        if not invoices:
            return None
        
        amounts = [inv.entity_data.get("total_amount", 0) for inv in invoices]
        return sum(amounts) / len(amounts) if amounts else None
    
    async def _check_duplicate_invoice(
        self,
        db: AsyncSession,
        invoice_number: str,
        supplier_id: str
    ) -> bool:
        """Check for duplicate invoice."""
        result = await db.execute(
            select(ERPEntity).where(
                and_(
                    ERPEntity.entity_type == "Invoice",
                    ERPEntity.entity_data["invoice_number"].astext == invoice_number,
                    ERPEntity.entity_data["supplier_id"].astext == supplier_id,
                    ERPEntity.is_active == True
                )
            )
        )
        return result.scalar_one_or_none() is not None
    
    async def _check_dock_appointment(
        self,
        db: AsyncSession,
        shipment_number: str
    ) -> Optional[Dict[str, Any]]:
        """Check for dock appointment for shipment."""
        # This would integrate with yard management system
        return None
    
    async def _check_recent_access(
        self,
        db: AsyncSession,
        employee_id: str
    ) -> List[Dict[str, Any]]:
        """Check for recent access events."""
        # This would integrate with access control system
        return []
    
    async def _check_overtime_anomalies(
        self,
        db: AsyncSession,
        employee_id: str
    ) -> List[Dict[str, Any]]:
        """Check for overtime anomalies."""
        # This would integrate with HR/time tracking system
        return []

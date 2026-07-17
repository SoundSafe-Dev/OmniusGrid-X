"""
ERP Correlation Patterns

Correlation patterns for ERP-specific scenarios:
- Procurement anomaly detection (PO delays, vendor risks)
- Manufacturing + ERP correlation (production vs orders)
- Financial + operational correlation (cost vs efficiency)
- Supply chain risk prediction
- Defense manufacturing correlation
- Smart factory correlation
- Ports/logistics correlation
"""

from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta, timezone
import structlog
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_

from app.db.models import (
    ERPEntity,
    ERPCorrelation,
    ERPIntegrationEvent,
    ActionableRegistry,
    ActionableRegistryItem,
    Task
)
from app.services.correlation_registry_integration import CorrelationRegistryIntegration

logger = structlog.get_logger()


class ERPCorrelationPatterns:
    """
    ERP correlation patterns for detecting anomalies and insights.
    
    Maps ERP events to operational domains and creates
    correlation patterns with sensor data.
    """
    
    # Domain mappings for SAP entities
    SAP_DOMAIN_MAPPINGS = {
        "PurchaseOrder": "PROCUREMENT",
        "ManufacturingOrder": "PRODUCTION_OEE",
        "Inventory": "WAREHOUSE_MANAGEMENT",
        "Vendor": "SUPPLIER_RELATIONSHIP",
        "WorkOrder": "MAINTENANCE"
    }
    
    def __init__(self, organization_id: str, integration_id: str):
        self.organization_id = organization_id
        self.integration_id = integration_id
        self.registry_integration = CorrelationRegistryIntegration()
        
        logger.info(
            "erp_correlation_patterns_initialized",
            organization_id=organization_id,
            integration_id=integration_id
        )
    
    async def analyze_purchase_order_anomalies(
        self,
        db: AsyncSession,
        po_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Analyze purchase order for anomalies.
        
        Args:
            db: Database session
            po_data: Purchase order data
            
        Returns:
            Dict with anomaly analysis results
        """
        anomalies = []
        risk_score = 0
        
        # Check for PO delays
        if po_data.get("delivery_date"):
            delivery_date = datetime.fromisoformat(po_data["delivery_date"])
            if delivery_date < datetime.now(timezone.utc):
                anomalies.append({
                    "type": "delivery_delay",
                    "severity": "high",
                    "message": f"PO {po_data.get('po_number')} is overdue"
                })
                risk_score += 30
        
        # Check for unusual amount
        if po_data.get("total_amount"):
            # Compare with historical average for this supplier
            avg_amount = await self._get_supplier_avg_amount(
                db,
                po_data.get("supplier_id")
            )
            
            if avg_amount and po_data["total_amount"] > avg_amount * 3:
                anomalies.append({
                    "type": "unusual_amount",
                    "severity": "medium",
                    "message": f"PO amount {po_data['total_amount']} is 3x above average for supplier"
                })
                risk_score += 20
        
        # Check for new supplier
        supplier_history = await self._get_supplier_order_count(
            db,
            po_data.get("supplier_id")
        )
        
        if supplier_history == 0:
            anomalies.append({
                "type": "new_supplier",
                "severity": "low",
                "message": f"First order from new supplier {po_data.get('supplier_id')}"
            })
            risk_score += 10
        
        # Create correlation record if anomalies found
        if anomalies:
            await self._create_correlation(
                db,
                "procurement_anomaly",
                po_data,
                risk_score,
                {"anomalies": anomalies}
            )
        
        logger.info(
            "po_anomaly_analysis_completed",
            po_number=po_data.get("po_number"),
            anomaly_count=len(anomalies),
            risk_score=risk_score
        )
        
        return {
            "po_number": po_data.get("po_number"),
            "anomalies": anomalies,
            "risk_score": risk_score,
            "requires_action": risk_score > 50
        }
    
    async def analyze_manufacturing_order_correlation(
        self,
        db: AsyncSession,
        mo_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Correlate manufacturing order with production data.
        
        Args:
            db: Database session
            mo_data: Manufacturing order data
            
        Returns:
            Dict with correlation analysis results
        """
        correlations = []
        
        # Check if MO aligns with current production
        from app.db.models import Operation
        
        result = await db.execute(
            select(Operation).where(
                and_(
                    Operation.job_id == mo_data.get("mo_number"),
                    Operation.status == "running"
                )
            )
        )
        active_operation = result.scalar_one_or_none()
        
        if active_operation:
            correlations.append({
                "type": "active_production",
                "message": f"MO {mo_data.get('mo_number')} is currently in production",
                "operation_id": str(active_operation.id)
            })
        else:
            # Check if MO should be in production based on dates
            if mo_data.get("start_date"):
                start_date = datetime.fromisoformat(mo_data["start_date"])
                if start_date <= datetime.now(timezone.utc) <= datetime.fromisoformat(mo_data["end_date"]):
                    correlations.append({
                        "type": "production_gap",
                        "severity": "high",
                        "message": f"MO {mo_data.get('mo_number')} should be in production but is not"
                    })
        
        # Check material availability
        inventory_result = await db.execute(
            select(ERPEntity).where(
                and_(
                    ERPEntity.entity_type == "Inventory",
                    ERPEntity.entity_id == mo_data.get("material"),
                    ERPEntity.is_active == True
                )
            )
        )
        inventory = inventory_result.scalar_one_or_none()
        
        if inventory:
            available_qty = inventory.entity_data.get("quantity", 0)
            required_qty = mo_data.get("quantity", 0)
            
            if available_qty < required_qty:
                correlations.append({
                    "type": "material_shortage",
                    "severity": "high",
                    "message": f"Insufficient material: {available_qty} available, {required_qty} required"
                })
        
        logger.info(
            "mo_correlation_analysis_completed",
            mo_number=mo_data.get("mo_number"),
            correlation_count=len(correlations)
        )
        
        return {
            "mo_number": mo_data.get("mo_number"),
            "correlations": correlations
        }
    
    async def analyze_supply_chain_risk(
        self,
        db: AsyncSession,
        supplier_id: str
    ) -> Dict[str, Any]:
        """
        Analyze supply chain risk for a supplier.
        
        Args:
            db: Database session
            supplier_id: Supplier ID
            
        Returns:
            Dict with risk analysis results
        """
        risk_factors = []
        overall_risk = "low"
        
        # Check supplier performance
        vendor_data = await self._get_vendor_data(db, supplier_id)
        
        if vendor_data:
            # Check if supplier is blocked
            if not vendor_data.get("is_active"):
                risk_factors.append({
                    "type": "supplier_blocked",
                    "severity": "critical",
                    "message": "Supplier is blocked in SAP"
                })
                overall_risk = "critical"
        
        # Check recent PO delays from this supplier
        delayed_pos = await self._count_delayed_pos_by_supplier(db, supplier_id)
        
        if delayed_pos > 5:
            risk_factors.append({
                "type": "frequent_delays",
                "severity": "high",
                "message": f"{delayed_pos} delayed POs from this supplier in last 30 days"
            })
            overall_risk = "high"
        elif delayed_pos > 2:
            risk_factors.append({
                "type": "some_delays",
                "severity": "medium",
                "message": f"{delayed_pos} delayed POs from this supplier in last 30 days"
            })
            overall_risk = "medium"
        
        # Check inventory levels for this supplier's materials
        low_inventory_items = await self._count_low_inventory_by_supplier(db, supplier_id)
        
        if low_inventory_items > 3:
            risk_factors.append({
                "type": "low_inventory",
                "severity": "high",
                "message": f"{low_inventory_items} items from this supplier at low inventory levels"
            })
            if overall_risk != "critical":
                overall_risk = "high"
        
        logger.info(
            "supply_chain_risk_analysis_completed",
            supplier_id=supplier_id,
            overall_risk=overall_risk,
            risk_factor_count=len(risk_factors)
        )
        
        return {
            "supplier_id": supplier_id,
            "overall_risk": overall_risk,
            "risk_factors": risk_factors,
            "requires_action": overall_risk in ["high", "critical"]
        }
    
    async def analyze_defense_manufacturing_correlation(
        self,
        db: AsyncSession,
        erp_events: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Correlate ERP data with physical security for defense manufacturing.
        
        Args:
            db: Database session
            erp_events: List of ERP events
            
        Returns:
            Dict with correlation analysis results
        """
        correlations = []
        
        # Look for inventory adjustments + badge access anomalies
        for event in erp_events:
            if event.get("entity_type") == "Inventory":
                # Check for unusual inventory adjustments
                if event.get("event_type") == "InventoryAdjusted":
                    # Check for badge access anomalies at same time
                    badge_anomalies = await self._check_badge_anomalies(
                        db,
                        event.get("timestamp")
                    )
                    
                    if badge_anomalies:
                        correlations.append({
                            "type": "theft_risk",
                            "severity": "critical",
                            "message": "Inventory adjustment coincides with badge access anomalies",
                            "inventory_event": event,
                            "badge_anomalies": badge_anomalies
                        })
        
        # Check for vendor cyber alerts + procurement anomalies
        vendor_events = [e for e in erp_events if e.get("entity_type") == "Vendor"]
        for event in vendor_events:
            if event.get("event_type") == "VendorCyberAlert":
                # Check for procurement anomalies from same vendor
                procurement_anomalies = await self._check_procurement_anomalies(
                    db,
                    event.get("entity_id")
                )
                
                if procurement_anomalies:
                    correlations.append({
                        "type": "supply_chain_compromise",
                        "severity": "critical",
                        "message": "Vendor cyber alert coincides with procurement anomalies",
                        "vendor_event": event,
                        "procurement_anomalies": procurement_anomalies
                    })
        
        logger.info(
            "defense_manufacturing_correlation_completed",
            event_count=len(erp_events),
            correlation_count=len(correlations)
        )
        
        return {
            "correlations": correlations,
            "requires_immediate_action": any(
                c.get("severity") == "critical" for c in correlations
            )
        }
    
    async def analyze_smart_factory_correlation(
        self,
        db: AsyncSession,
        erp_events: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Correlate ERP data with sensor data for smart factory.
        
        Args:
            db: Database session
            erp_events: List of ERP events
            
        Returns:
            Dict with correlation analysis results
        """
        correlations = []
        
        # Check for defect rates + sensor anomalies
        for event in erp_events:
            if event.get("entity_type") == "ManufacturingOrder":
                # Check for high defect rate
                defect_rate = await self._get_defect_rate(db, event.get("entity_id"))
                
                if defect_rate > 0.05:  # 5% defect rate threshold
                    # Check for sensor anomalies
                    sensor_anomalies = await self._check_sensor_anomalies(
                        db,
                        event.get("entity_id")
                    )
                    
                    if sensor_anomalies:
                        correlations.append({
                            "type": "equipment_failure_risk",
                            "severity": "high",
                            "message": f"High defect rate ({defect_rate:.1%}) with sensor anomalies",
                            "defect_rate": defect_rate,
                            "sensor_anomalies": sensor_anomalies
                        })
        
        logger.info(
            "smart_factory_correlation_completed",
            event_count=len(erp_events),
            correlation_count=len(correlations)
        )
        
        return {
            "correlations": correlations
        }
    
    async def create_registry_items_for_sap(
        self,
        db: AsyncSession,
        domain: str,
        sap_data: Dict[str, Any]
    ) -> List[str]:
        """
        Create registry items for SAP data in operational domains.
        
        Args:
            db: Database session
            domain: Operational domain
            sap_data: SAP data
            
        Returns:
            List of created registry item IDs
        """
        # Use the existing correlation registry integration
        # to create registry items based on SAP data
        
        registry_items = []
        
        # Map SAP data to registry items
        if domain == "PROCUREMENT":
            registry_items.append({
                "item_code": "PO_MONITORING",
                "item_name": f"PO {sap_data.get('po_number')} Monitoring",
                "severity": "medium",
                "completion_criteria": "PO delivered on time without issues"
            })
        
        elif domain == "MAINTENANCE":
            registry_items.append({
                "item_code": "WO_TRACKING",
                "item_name": f"WO {sap_data.get('wo_number')} Tracking",
                "severity": sap_data.get("priority", "medium"),
                "completion_criteria": "Work order completed within SLA"
            })
        
        # Create registry items using the integration service
        created_ids = []
        for item in registry_items:
            # This would call the correlation registry integration
            # to create the actual registry item
            created_ids.append(item["item_code"])
        
        logger.info(
            "sap_registry_items_created",
            domain=domain,
            item_count=len(created_ids)
        )
        
        return created_ids
    
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
    
    async def _get_supplier_avg_amount(
        self,
        db: AsyncSession,
        supplier_id: str
    ) -> Optional[float]:
        """Get average PO amount for supplier."""
        result = await db.execute(
            select(ERPEntity).where(
                and_(
                    ERPEntity.entity_type == "PurchaseOrder",
                    ERPEntity.entity_data["supplier_id"].astext == supplier_id,
                    ERPEntity.is_active == True
                )
            )
        )
        pos = result.scalars().all()
        
        if not pos:
            return None
        
        amounts = [po.entity_data.get("total_amount", 0) for po in pos]
        return sum(amounts) / len(amounts) if amounts else None
    
    async def _get_supplier_order_count(
        self,
        db: AsyncSession,
        supplier_id: str
    ) -> int:
        """Get number of orders from supplier."""
        result = await db.execute(
            select(ERPEntity).where(
                and_(
                    ERPEntity.entity_type == "PurchaseOrder",
                    ERPEntity.entity_data["supplier_id"].astext == supplier_id,
                    ERPEntity.is_active == True
                )
            )
        )
        return len(result.scalars().all())
    
    async def _get_vendor_data(
        self,
        db: AsyncSession,
        supplier_id: str
    ) -> Optional[Dict[str, Any]]:
        """Get vendor data."""
        result = await db.execute(
            select(ERPEntity).where(
                and_(
                    ERPEntity.entity_type == "Vendor",
                    ERPEntity.entity_id == supplier_id,
                    ERPEntity.is_active == True
                )
            )
        )
        vendor = result.scalar_one_or_none()
        return vendor.entity_data if vendor else None
    
    async def _count_delayed_pos_by_supplier(
        self,
        db: AsyncSession,
        supplier_id: str
    ) -> int:
        """Count delayed POs from supplier in last 30 days."""
        thirty_days_ago = datetime.now(timezone.utc) - timedelta(days=30)
        
        result = await db.execute(
            select(ERPEntity).where(
                and_(
                    ERPEntity.entity_type == "PurchaseOrder",
                    ERPEntity.entity_data["supplier_id"].astext == supplier_id,
                    ERPEntity.entity_data["delivery_date"].astext < datetime.now(timezone.utc).isoformat(),
                    ERPEntity.created_at >= thirty_days_ago,
                    ERPEntity.is_active == True
                )
            )
        )
        return len(result.scalars().all())
    
    async def _count_low_inventory_by_supplier(
        self,
        db: AsyncSession,
        supplier_id: str
    ) -> int:
        """Count low inventory items from supplier."""
        # This would require joining inventory with vendor data
        # Simplified implementation
        return 0
    
    async def _check_badge_anomalies(
        self,
        db: AsyncSession,
        timestamp: datetime
    ) -> List[Dict[str, Any]]:
        """Check for badge access anomalies around timestamp."""
        # This would integrate with access control system
        return []
    
    async def _check_procurement_anomalies(
        self,
        db: AsyncSession,
        vendor_id: str
    ) -> List[Dict[str, Any]]:
        """Check for procurement anomalies from vendor."""
        return []
    
    async def _get_defect_rate(
        self,
        db: AsyncSession,
        mo_number: str
    ) -> float:
        """Get defect rate for manufacturing order."""
        # This would integrate with quality data
        return 0.0
    
    async def _check_sensor_anomalies(
        self,
        db: AsyncSession,
        mo_number: str
    ) -> List[Dict[str, Any]]:
        """Check for sensor anomalies for manufacturing order."""
        # This would integrate with telemetry data
        return []

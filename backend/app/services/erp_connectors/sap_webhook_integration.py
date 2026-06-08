"""
SAP Webhook Integration

SAP Event Mesh webhook integration for real-time events:
- PO_CREATED events
- PO_CHANGED events
- Inventory change notifications
- Production status updates
- Work order events
"""

from typing import Dict, Any, Optional, List
from datetime import datetime
import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.erp_webhook_receiver import ERPWebhookReceiver
from app.services.erp_correlation_patterns import ERPCorrelationPatterns
from app.db.models import ERPIntegrationEvent

logger = structlog.get_logger()


class SAPWebhookIntegration:
    """
    SAP Event Mesh webhook integration.
    
    Handles real-time events from SAP Event Mesh and
    processes them through the correlation engine.
    """
    
    # SAP Event Mesh event types
    SAP_EVENT_TYPES = {
        "PurchaseOrderCreated": "PO_CREATED",
        "PurchaseOrderChanged": "PO_CHANGED",
        "PurchaseOrderDeleted": "PO_DELETED",
        "InventoryChanged": "INVENTORY_CHANGED",
        "ProductionOrderCreated": "MO_CREATED",
        "ProductionOrderChanged": "MO_CHANGED",
        "MaintenanceOrderCreated": "WO_CREATED",
        "MaintenanceOrderChanged": "WO_CHANGED"
    }
    
    def __init__(self, organization_id: str, integration_id: str):
        self.organization_id = organization_id
        self.integration_id = integration_id
        self.webhook_receiver = ERPWebhookReceiver(integration_id, organization_id)
        self.correlation_patterns = ERPCorrelationPatterns(organization_id, integration_id)
        
        # Register event processors
        self._register_event_processors()
        
        logger.info(
            "sap_webhook_integration_initialized",
            organization_id=organization_id,
            integration_id=integration_id
        )
    
    def _register_event_processors(self):
        """Register event processors for SAP event types."""
        self.webhook_receiver.register_event_processor(
            "PurchaseOrderCreated",
            self._process_po_created
        )
        
        self.webhook_receiver.register_event_processor(
            "PurchaseOrderChanged",
            self._process_po_changed
        )
        
        self.webhook_receiver.register_event_processor(
            "InventoryChanged",
            self._process_inventory_changed
        )
        
        self.webhook_receiver.register_event_processor(
            "ProductionOrderCreated",
            self._process_mo_created
        )
        
        self.webhook_receiver.register_event_processor(
            "MaintenanceOrderCreated",
            self._process_wo_created
        )
    
    async def receive_sap_event(
        self,
        event_data: Dict[str, Any],
        event_type: str,
        event_id: str,
        db: AsyncSession
    ) -> Dict[str, Any]:
        """
        Receive and process SAP event from Event Mesh.
        
        Args:
            event_data: Event payload
            event_type: Event type
            event_id: Event ID
            db: Database session
            
        Returns:
            Dict with processing status
        """
        # Map SAP event type to internal type
        internal_event_type = self.SAP_EVENT_TYPES.get(event_type, event_type)
        
        # Prepare event data for webhook receiver
        webhook_data = {
            "event_type": internal_event_type,
            "event_id": event_id,
            "source_system": "SAP",
            "entity_type": self._extract_entity_type(event_type),
            "entity_id": self._extract_entity_id(event_data, event_type),
            "timestamp": datetime.utcnow().isoformat(),
            **event_data
        }
        
        # Process through webhook receiver
        result = await self.webhook_receiver.receive_webhook(
            request=None,  # Not using FastAPI request here
            event_data=webhook_data,
            x_event_type=internal_event_type,
            x_event_id=event_id,
            x_source_system="SAP"
        )
        
        logger.info(
            "sap_event_processed",
            event_type=event_type,
            event_id=event_id,
            status=result.get("status")
        )
        
        return result
    
    async def _process_po_created(
        self,
        event_data: Dict[str, Any],
        event_record_id: str
    ):
        """
        Process PO created event.
        
        Args:
            event_data: Event data
            event_record_id: Event record ID
        """
        logger.info(
            "processing_po_created",
            po_number=event_data.get("PurchaseOrder")
        )
        
        # Store PO data
        from app.services.erp_data_transformer import ERPDataTransformer
        transformer = ERPDataTransformer(self.organization_id, self.integration_id)
        
        normalized_po = transformer.transform_purchase_order(event_data)
        
        # Store in database
        db = next(get_db())
        try:
            await self._store_entity(
                db,
                "PurchaseOrder",
                event_data.get("PurchaseOrder"),
                normalized_po,
                "SAP"
            )
            
            # Analyze for anomalies
            anomaly_result = await self.correlation_patterns.analyze_purchase_order_anomalies(
                db,
                normalized_po
            )
            
            if anomaly_result.get("requires_action"):
                # Create alert or task
                await self._create_alert_for_po_anomaly(db, normalized_po, anomaly_result)
            
        finally:
            await db.close()
    
    async def _process_po_changed(
        self,
        event_data: Dict[str, Any],
        event_record_id: str
    ):
        """
        Process PO changed event.
        
        Args:
            event_data: Event data
            event_record_id: Event record ID
        """
        logger.info(
            "processing_po_changed",
            po_number=event_data.get("PurchaseOrder")
        )
        
        # Update existing PO data
        from app.services.erp_data_transformer import ERPDataTransformer
        transformer = ERPDataTransformer(self.organization_id, self.integration_id)
        
        normalized_po = transformer.transform_purchase_order(event_data)
        
        db = next(get_db())
        try:
            await self._store_entity(
                db,
                "PurchaseOrder",
                event_data.get("PurchaseOrder"),
                normalized_po,
                "SAP"
            )
            
            # Check for status changes that require attention
            if normalized_po.get("status") in ["rejected", "cancelled"]:
                await self._create_alert_for_po_status_change(db, normalized_po)
            
        finally:
            await db.close()
    
    async def _process_inventory_changed(
        self,
        event_data: Dict[str, Any],
        event_record_id: str
    ):
        """
        Process inventory changed event.
        
        Args:
            event_data: Event data
            event_record_id: Event record ID
        """
        logger.info(
            "processing_inventory_changed",
            material=event_data.get("Material")
        )
        
        from app.services.erp_data_transformer import ERPDataTransformer
        transformer = ERPDataTransformer(self.organization_id, self.integration_id)
        
        normalized_inventory = transformer.transform_inventory(event_data)
        
        db = next(get_db())
        try:
            await self._store_entity(
                db,
                "Inventory",
                event_data.get("Material"),
                normalized_inventory,
                "SAP"
            )
            
            # Check for low inventory
            if normalized_inventory.get("quantity", 0) < 100:  # Threshold
                await self._create_alert_for_low_inventory(db, normalized_inventory)
            
        finally:
            await db.close()
    
    async def _process_mo_created(
        self,
        event_data: Dict[str, Any],
        event_record_id: str
    ):
        """
        Process manufacturing order created event.
        
        Args:
            event_data: Event data
            event_record_id: Event record ID
        """
        logger.info(
            "processing_mo_created",
            mo_number=event_data.get("ManufacturingOrder")
        )
        
        from app.services.erp_data_transformer import ERPDataTransformer
        transformer = ERPDataTransformer(self.organization_id, self.integration_id)
        
        normalized_mo = transformer.transform_manufacturing_order(event_data)
        
        db = next(get_db())
        try:
            await self._store_entity(
                db,
                "ManufacturingOrder",
                event_data.get("ManufacturingOrder"),
                normalized_mo,
                "SAP"
            )
            
            # Correlate with production data
            correlation_result = await self.correlation_patterns.analyze_manufacturing_order_correlation(
                db,
                normalized_mo
            )
            
            # Create registry item for production domain
            await self.correlation_patterns.create_registry_items_for_sap(
                db,
                "PRODUCTION_OEE",
                normalized_mo
            )
            
        finally:
            await db.close()
    
    async def _process_wo_created(
        self,
        event_data: Dict[str, Any],
        event_record_id: str
    ):
        """
        Process work order created event.
        
        Args:
            event_data: Event data
            event_record_id: Event record ID
        """
        logger.info(
            "processing_wo_created",
            wo_number=event_data.get("MaintenanceOrder")
        )
        
        from app.services.erp_data_transformer import ERPDataTransformer
        transformer = ERPDataTransformer(self.organization_id, self.integration_id)
        
        normalized_wo = transformer.transform_work_order(event_data)
        
        db = next(get_db())
        try:
            await self._store_entity(
                db,
                "WorkOrder",
                event_data.get("MaintenanceOrder"),
                normalized_wo,
                "SAP"
            )
            
            # Create registry item for maintenance domain
            await self.correlation_patterns.create_registry_items_for_sap(
                db,
                "MAINTENANCE",
                normalized_wo
            )
            
            # High priority WOs should create immediate tasks
            if normalized_wo.get("priority") in ["critical", "high"]:
                await self._create_task_for_work_order(db, normalized_wo)
            
        finally:
            await db.close()
    
    def _extract_entity_type(self, event_type: str) -> str:
        """Extract entity type from SAP event type."""
        if "PurchaseOrder" in event_type:
            return "PurchaseOrder"
        elif "Inventory" in event_type:
            return "Inventory"
        elif "ProductionOrder" in event_type:
            return "ManufacturingOrder"
        elif "MaintenanceOrder" in event_type:
            return "WorkOrder"
        return "Unknown"
    
    def _extract_entity_id(self, event_data: Dict[str, Any], event_type: str) -> str:
        """Extract entity ID from event data."""
        if "PurchaseOrder" in event_type:
            return event_data.get("PurchaseOrder", "")
        elif "Inventory" in event_type:
            return event_data.get("Material", "")
        elif "ProductionOrder" in event_type:
            return event_data.get("ManufacturingOrder", "")
        elif "MaintenanceOrder" in event_type:
            return event_data.get("MaintenanceOrder", "")
        return ""
    
    async def _store_entity(
        self,
        db: AsyncSession,
        entity_type: str,
        entity_id: str,
        entity_data: Dict[str, Any],
        source_system: str
    ):
        """Store entity in database."""
        from app.db.models import ERPEntity
        from sqlalchemy import select, and_
        
        # Check if entity exists
        result = await db.execute(
            select(ERPEntity).where(
                and_(
                    ERPEntity.integration_id == self.integration_id,
                    ERPEntity.entity_type == entity_type,
                    ERPEntity.entity_id == entity_id
                )
            )
        )
        existing = result.scalar_one_or_none()
        
        if existing:
            # Update existing
            existing.valid_to = datetime.utcnow()
            existing.is_active = False
            
            new_entity = ERPEntity(
                organization_id=self.organization_id,
                integration_id=self.integration_id,
                entity_type=entity_type,
                entity_id=entity_id,
                entity_data=entity_data,
                source_system=source_system,
                is_active=True,
                valid_from=datetime.utcnow()
            )
            db.add(new_entity)
        else:
            # Create new
            entity = ERPEntity(
                organization_id=self.organization_id,
                integration_id=self.integration_id,
                entity_type=entity_type,
                entity_id=entity_id,
                entity_data=entity_data,
                source_system=source_system,
                is_active=True,
                valid_from=datetime.utcnow()
            )
            db.add(entity)
        
        await db.commit()
    
    async def _create_alert_for_po_anomaly(
        self,
        db: AsyncSession,
        po_data: Dict[str, Any],
        anomaly_result: Dict[str, Any]
    ):
        """Create alert for PO anomaly."""
        # This would integrate with the alarm/alert system
        logger.warning(
            "po_anomaly_alert",
            po_number=po_data.get("po_number"),
            anomalies=anomaly_result.get("anomalies")
        )
    
    async def _create_alert_for_po_status_change(
        self,
        db: AsyncSession,
        po_data: Dict[str, Any]
    ):
        """Create alert for PO status change."""
        logger.warning(
            "po_status_change_alert",
            po_number=po_data.get("po_number"),
            status=po_data.get("status")
        )
    
    async def _create_alert_for_low_inventory(
        self,
        db: AsyncSession,
        inventory_data: Dict[str, Any]
    ):
        """Create alert for low inventory."""
        logger.warning(
            "low_inventory_alert",
            material=inventory_data.get("material"),
            quantity=inventory_data.get("quantity")
        )
    
    async def _create_task_for_work_order(
        self,
        db: AsyncSession,
        wo_data: Dict[str, Any]
    ):
        """Create task for high-priority work order."""
        from app.db.models import Task, TaskColumn
        from sqlalchemy import select
        
        # Get default column for maintenance tasks
        result = await db.execute(
            select(TaskColumn).where(
                TaskColumn.column_type == "in_progress"
            )
        )
        column = result.scalar_one_or_none()
        
        if column:
            task = Task(
                board_id=column.board_id,
                column_id=column.id,
                title=f"SAP Work Order: {wo_data.get('wo_number')}",
                description=wo_data.get("description", ""),
                task_type="maintenance_cm",
                priority=wo_data.get("priority", "medium"),
                status="ready",
                custom_fields={
                    "sap_wo_number": wo_data.get("wo_number"),
                    "equipment": wo_data.get("equipment"),
                    "functional_location": wo_data.get("functional_location")
                }
            )
            db.add(task)
            await db.commit()
            
            logger.info(
                "task_created_for_sap_wo",
                wo_number=wo_data.get("wo_number"),
                task_id=str(task.id)
            )

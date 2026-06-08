"""
SAP Data Extraction Service

Service for extracting and storing SAP data:
- Purchase orders (procurement domain)
- Manufacturing orders (production domain)
- Inventory data (warehouse management)
- Vendor master data (supplier relationship)
- Work order data (maintenance domain)
"""

from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
import structlog

from app.services.erp_connectors.sap_connector import SAPConnector
from app.db.models import (
    ERPEntity,
    ERPSyncStatus,
    ERPIntegrationEvent,
    IntegrationConfiguration
)
from app.services.erp_data_transformer import ERPDataTransformer

logger = structlog.get_logger()


class SAPDataExtractionService:
    """
    Service for extracting and storing SAP data.
    
    Orchestrates data extraction from SAP using the connector,
    transforms the data, and stores it in the database.
    """
    
    def __init__(
        self,
        connector: SAPConnector,
        organization_id: str,
        integration_id: str
    ):
        self.connector = connector
        self.organization_id = organization_id
        self.integration_id = integration_id
        self.transformer = ERPDataTransformer(organization_id, integration_id)
        
        logger.info(
            "sap_data_extraction_service_initialized",
            organization_id=organization_id,
            integration_id=integration_id
        )
    
    async def extract_purchase_orders(
        self,
        db: AsyncSession,
        filters: Optional[Dict[str, Any]] = None,
        limit: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Extract purchase orders from SAP.
        
        Args:
            db: Database session
            filters: Optional filters
            limit: Optional limit
            
        Returns:
            Dict with extraction results
        """
        start_time = datetime.utcnow()
        
        try:
            # Fetch data from SAP
            po_data = await self.connector.fetch_purchase_orders(filters, limit)
            
            # Transform and store data
            stored_count = 0
            for po in po_data:
                # Transform SAP data to normalized format
                normalized = self.transformer.transform_purchase_order(po)
                
                # Store in database
                await self._store_entity(
                    db,
                    "PurchaseOrder",
                    po.get("PurchaseOrder"),
                    normalized,
                    "SAP"
                )
                stored_count += 1
            
            # Update sync status
            await self._update_sync_status(
                db,
                "PurchaseOrder",
                "completed",
                stored_count,
                0,
                (datetime.utcnow() - start_time).total_seconds()
            )
            
            logger.info(
                "sap_purchase_orders_extracted",
                count=stored_count,
                duration_seconds=(datetime.utcnow() - start_time).total_seconds()
            )
            
            return {
                "status": "success",
                "entity_type": "PurchaseOrder",
                "records_extracted": stored_count,
                "duration_seconds": (datetime.utcnow() - start_time).total_seconds()
            }
            
        except Exception as e:
            logger.error(
                "sap_purchase_orders_extraction_failed",
                error=str(e)
            )
            
            await self._update_sync_status(
                db,
                "PurchaseOrder",
                "failed",
                0,
                1,
                (datetime.utcnow() - start_time).total_seconds()
            )
            
            raise
    
    async def extract_manufacturing_orders(
        self,
        db: AsyncSession,
        filters: Optional[Dict[str, Any]] = None,
        limit: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Extract manufacturing orders from SAP.
        
        Args:
            db: Database session
            filters: Optional filters
            limit: Optional limit
            
        Returns:
            Dict with extraction results
        """
        start_time = datetime.utcnow()
        
        try:
            # Fetch data from SAP
            mo_data = await self.connector.fetch_manufacturing_orders(filters, limit)
            
            # Transform and store data
            stored_count = 0
            for mo in mo_data:
                normalized = self.transformer.transform_manufacturing_order(mo)
                
                await self._store_entity(
                    db,
                    "ManufacturingOrder",
                    mo.get("ManufacturingOrder"),
                    normalized,
                    "SAP"
                )
                stored_count += 1
            
            # Update sync status
            await self._update_sync_status(
                db,
                "ManufacturingOrder",
                "completed",
                stored_count,
                0,
                (datetime.utcnow() - start_time).total_seconds()
            )
            
            logger.info(
                "sap_manufacturing_orders_extracted",
                count=stored_count,
                duration_seconds=(datetime.utcnow() - start_time).total_seconds()
            )
            
            return {
                "status": "success",
                "entity_type": "ManufacturingOrder",
                "records_extracted": stored_count,
                "duration_seconds": (datetime.utcnow() - start_time).total_seconds()
            }
            
        except Exception as e:
            logger.error(
                "sap_manufacturing_orders_extraction_failed",
                error=str(e)
            )
            
            await self._update_sync_status(
                db,
                "ManufacturingOrder",
                "failed",
                0,
                1,
                (datetime.utcnow() - start_time).total_seconds()
            )
            
            raise
    
    async def extract_inventory(
        self,
        db: AsyncSession,
        filters: Optional[Dict[str, Any]] = None,
        limit: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Extract inventory data from SAP.
        
        Args:
            db: Database session
            filters: Optional filters
            limit: Optional limit
            
        Returns:
            Dict with extraction results
        """
        start_time = datetime.utcnow()
        
        try:
            # Fetch data from SAP
            inventory_data = await self.connector.fetch_inventory(filters, limit)
            
            # Transform and store data
            stored_count = 0
            for inventory in inventory_data:
                normalized = self.transformer.transform_inventory(inventory)
                
                await self._store_entity(
                    db,
                    "Inventory",
                    inventory.get("Material"),
                    normalized,
                    "SAP"
                )
                stored_count += 1
            
            # Update sync status
            await self._update_sync_status(
                db,
                "Inventory",
                "completed",
                stored_count,
                0,
                (datetime.utcnow() - start_time).total_seconds()
            )
            
            logger.info(
                "sap_inventory_extracted",
                count=stored_count,
                duration_seconds=(datetime.utcnow() - start_time).total_seconds()
            )
            
            return {
                "status": "success",
                "entity_type": "Inventory",
                "records_extracted": stored_count,
                "duration_seconds": (datetime.utcnow() - start_time).total_seconds()
            }
            
        except Exception as e:
            logger.error(
                "sap_inventory_extraction_failed",
                error=str(e)
            )
            
            await self._update_sync_status(
                db,
                "Inventory",
                "failed",
                0,
                1,
                (datetime.utcnow() - start_time).total_seconds()
            )
            
            raise
    
    async def extract_vendors(
        self,
        db: AsyncSession,
        filters: Optional[Dict[str, Any]] = None,
        limit: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Extract vendor master data from SAP.
        
        Args:
            db: Database session
            filters: Optional filters
            limit: Optional limit
            
        Returns:
            Dict with extraction results
        """
        start_time = datetime.utcnow()
        
        try:
            # Fetch data from SAP
            vendor_data = await self.connector.fetch_vendors(filters, limit)
            
            # Transform and store data
            stored_count = 0
            for vendor in vendor_data:
                normalized = self.transformer.transform_vendor(vendor)
                
                await self._store_entity(
                    db,
                    "Vendor",
                    vendor.get("Supplier"),
                    normalized,
                    "SAP"
                )
                stored_count += 1
            
            # Update sync status
            await self._update_sync_status(
                db,
                "Vendor",
                "completed",
                stored_count,
                0,
                (datetime.utcnow() - start_time).total_seconds()
            )
            
            logger.info(
                "sap_vendors_extracted",
                count=stored_count,
                duration_seconds=(datetime.utcnow() - start_time).total_seconds()
            )
            
            return {
                "status": "success",
                "entity_type": "Vendor",
                "records_extracted": stored_count,
                "duration_seconds": (datetime.utcnow() - start_time).total_seconds()
            }
            
        except Exception as e:
            logger.error(
                "sap_vendors_extraction_failed",
                error=str(e)
            )
            
            await self._update_sync_status(
                db,
                "Vendor",
                "failed",
                0,
                1,
                (datetime.utcnow() - start_time).total_seconds()
            )
            
            raise
    
    async def extract_work_orders(
        self,
        db: AsyncSession,
        filters: Optional[Dict[str, Any]] = None,
        limit: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Extract maintenance work orders from SAP.
        
        Args:
            db: Database session
            filters: Optional filters
            limit: Optional limit
            
        Returns:
            Dict with extraction results
        """
        start_time = datetime.utcnow()
        
        try:
            # Fetch data from SAP
            wo_data = await self.connector.fetch_work_orders(filters, limit)
            
            # Transform and store data
            stored_count = 0
            for wo in wo_data:
                normalized = self.transformer.transform_work_order(wo)
                
                await self._store_entity(
                    db,
                    "WorkOrder",
                    wo.get("MaintenanceOrder"),
                    normalized,
                    "SAP"
                )
                stored_count += 1
            
            # Update sync status
            await self._update_sync_status(
                db,
                "WorkOrder",
                "completed",
                stored_count,
                0,
                (datetime.utcnow() - start_time).total_seconds()
            )
            
            logger.info(
                "sap_work_orders_extracted",
                count=stored_count,
                duration_seconds=(datetime.utcnow() - start_time).total_seconds()
            )
            
            return {
                "status": "success",
                "entity_type": "WorkOrder",
                "records_extracted": stored_count,
                "duration_seconds": (datetime.utcnow() - start_time).total_seconds()
            }
            
        except Exception as e:
            logger.error(
                "sap_work_orders_extraction_failed",
                error=str(e)
            )
            
            await self._update_sync_status(
                db,
                "WorkOrder",
                "failed",
                0,
                1,
                (datetime.utcnow() - start_time).total_seconds()
            )
            
            raise
    
    async def extract_all_entities(
        self,
        db: AsyncSession,
        filters: Optional[Dict[str, Any]] = None,
        limit: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Extract all SAP entity types.
        
        Args:
            db: Database session
            filters: Optional filters
            limit: Optional limit per entity type
            
        Returns:
            Dict with overall extraction results
        """
        results = {}
        
        # Extract each entity type
        entity_types = [
            "purchase_orders",
            "manufacturing_orders",
            "inventory",
            "vendors",
            "work_orders"
        ]
        
        for entity_type in entity_types:
            try:
                if entity_type == "purchase_orders":
                    result = await self.extract_purchase_orders(db, filters, limit)
                elif entity_type == "manufacturing_orders":
                    result = await self.extract_manufacturing_orders(db, filters, limit)
                elif entity_type == "inventory":
                    result = await self.extract_inventory(db, filters, limit)
                elif entity_type == "vendors":
                    result = await self.extract_vendors(db, filters, limit)
                elif entity_type == "work_orders":
                    result = await self.extract_work_orders(db, filters, limit)
                
                results[entity_type] = result
                
            except Exception as e:
                logger.error(
                    "entity_extraction_failed",
                    entity_type=entity_type,
                    error=str(e)
                )
                results[entity_type] = {
                    "status": "failed",
                    "error": str(e)
                }
        
        # Calculate overall stats
        total_extracted = sum(
            r.get("records_extracted", 0)
            for r in results.values()
            if r.get("status") == "success"
        )
        
        failed_count = sum(
            1 for r in results.values()
            if r.get("status") == "failed"
        )
        
        logger.info(
            "sap_all_entities_extraction_completed",
            total_extracted=total_extracted,
            failed_count=failed_count
        )
        
        return {
            "status": "completed",
            "total_extracted": total_extracted,
            "failed_count": failed_count,
            "results": results
        }
    
    async def _store_entity(
        self,
        db: AsyncSession,
        entity_type: str,
        entity_id: str,
        entity_data: Dict[str, Any],
        source_system: str
    ):
        """
        Store entity in database with upsert logic.
        
        Args:
            db: Database session
            entity_type: Type of entity
            entity_id: Entity ID
            entity_data: Entity data
            source_system: Source system name
        """
        # Check if entity already exists
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
            # Update existing record
            # Mark old version as inactive
            existing.valid_to = datetime.utcnow()
            existing.is_active = False
            
            # Create new version
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
            # Create new entity
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
    
    async def _update_sync_status(
        self,
        db: AsyncSession,
        entity_type: str,
        status: str,
        records_synced: int,
        records_failed: int,
        duration_seconds: float
    ):
        """
        Update sync status for entity type.
        
        Args:
            db: Database session
            entity_type: Entity type
            status: Sync status
            records_synced: Number of records synced
            records_failed: Number of records failed
            duration_seconds: Duration of sync
        """
        result = await db.execute(
            select(ERPSyncStatus).where(
                and_(
                    ERPSyncStatus.integration_id == self.integration_id,
                    ERPSyncStatus.entity_type == entity_type
                )
            )
        )
        sync_status = result.scalar_one_or_none()
        
        now = datetime.utcnow()
        
        if sync_status:
            sync_status.last_sync_at = now
            sync_status.last_sync_status = status
            sync_status.records_synced = records_synced
            sync_status.records_failed = records_failed
            sync_status.sync_duration_seconds = duration_seconds
            sync_status.updated_at = now
        else:
            sync_status = ERPSyncStatus(
                organization_id=self.organization_id,
                integration_id=self.integration_id,
                entity_type=entity_type,
                last_sync_at=now,
                last_sync_status=status,
                records_synced=records_synced,
                records_failed=records_failed,
                sync_duration_seconds=duration_seconds,
                created_at=now,
                updated_at=now
            )
            db.add(sync_status)
        
        await db.commit()

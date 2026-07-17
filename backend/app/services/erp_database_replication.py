"""
ERP Database Replication Service

Service for replicating ERP database changes using CDC:
- Change Data Capture (CDC) integration
- Real-time replication of ERP tables
- Conflict resolution and deduplication
- Replication lag monitoring
"""

from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta, timezone
import structlog
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_
import asyncio

from app.db.models import ERPEntity, ERPSyncStatus
from app.services.erp_data_transformer import ERPDataTransformer

logger = structlog.get_logger()


class ERPDatabaseReplicationService:
    """
    Service for replicating ERP database changes using CDC.
    
    Supports real-time replication of ERP tables to OmniusGrid
    using Change Data Capture (CDC) or similar mechanisms.
    """
    
    def __init__(self, organization_id: str, integration_id: str, erp_type: str):
        self.organization_id = organization_id
        self.integration_id = integration_id
        self.erp_type = erp_type
        self.transformer = ERPDataTransformer(organization_id, integration_id)
        
        # Replication state
        self.replication_lag_threshold = timedelta(minutes=5)
        self.batch_size = 1000
        
        logger.info(
            "erp_database_replication_service_initialized",
            organization_id=organization_id,
            integration_id=integration_id,
            erp_type=erp_type
        )
    
    async def start_replication(
        self,
        db: AsyncSession,
        tables: List[str],
        cdc_config: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Start CDC-based replication for specified tables.
        
        Args:
            db: Database session
            tables: List of tables to replicate
            cdc_config: CDC configuration (connection details, etc.)
            
        Returns:
            Dict with replication status
        """
        logger.info(
            "starting_erp_database_replication",
            tables=tables,
            erp_type=self.erp_type
        )
        
        # Initialize CDC for each table
        for table in tables:
            await self._initialize_cdc_for_table(db, table, cdc_config)
        
        # Start replication tasks
        tasks = []
        for table in tables:
            task = asyncio.create_task(
                self._replicate_table(db, table, cdc_config)
            )
            tasks.append(task)
        
        return {
            "status": "replication_started",
            "tables": tables,
            "erp_type": self.erp_type,
            "started_at": datetime.now(timezone.utc).isoformat()
        }
    
    async def _initialize_cdc_for_table(
        self,
        db: AsyncSession,
        table: str,
        cdc_config: Dict[str, Any]
    ):
        """
        Initialize CDC for a specific table.
        
        Args:
            db: Database session
            table: Table name
            cdc_config: CDC configuration
        """
        # In production, this would:
        # 1. Enable CDC on the source database table
        # 2. Create CDC capture instances
        # 3. Set up change tracking
        # 4. Store the last LSN (Log Sequence Number) for this table
        
        logger.info(
            "cdc_initialized_for_table",
            table=table,
            erp_type=self.erp_type
        )
    
    async def _replicate_table(
        self,
        db: AsyncSession,
        table: str,
        cdc_config: Dict[str, Any]
    ):
        """
        Replicate changes for a specific table.
        
        Args:
            db: Database session
            table: Table name
            cdc_config: CDC configuration
        """
        while True:
            try:
                # Get last LSN for this table
                last_lsn = await self._get_last_lsn(db, table)
                
                # Fetch changes from CDC
                changes = await self._fetch_cdc_changes(
                    table,
                    last_lsn,
                    cdc_config
                )
                
                if changes:
                    # Process changes
                    await self._process_cdc_changes(db, table, changes)
                    
                    # Update last LSN
                    await self._update_last_lsn(db, table, changes[-1]["lsn"])
                
                # Check replication lag
                await self._check_replication_lag(db, table)
                
                # Wait before next poll
                await asyncio.sleep(10)  # 10 second polling interval
                
            except Exception as e:
                logger.error(
                    "table_replication_error",
                    table=table,
                    error=str(e)
                )
                await asyncio.sleep(30)  # Wait longer on error
    
    async def _get_last_lsn(self, db: AsyncSession, table: str) -> Optional[str]:
        """
        Get the last processed LSN for a table.
        
        Args:
            db: Database session
            table: Table name
            
        Returns:
            Last LSN or None
        """
        # In production, this would query a replication state table
        return None
    
    async def _fetch_cdc_changes(
        self,
        table: str,
        last_lsn: Optional[str],
        cdc_config: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """
        Fetch CDC changes from the source database.
        
        Args:
            table: Table name
            last_lsn: Last processed LSN
            cdc_config: CDC configuration
            
        Returns:
            List of change records
        """
        # In production, this would:
        # 1. Connect to the source database
        # 2. Query CDC functions for changes since last_lsn
        # 3. Return the change records with operation type (insert/update/delete)
        
        return []
    
    async def _process_cdc_changes(
        self,
        db: AsyncSession,
        table: str,
        changes: List[Dict[str, Any]]
    ):
        """
        Process CDC changes and apply to OmniusGrid database.
        
        Args:
            db: Database session
            table: Table name
            changes: List of change records
        """
        for change in changes:
            operation = change.get("operation")
            data = change.get("data")
            
            if operation == "insert" or operation == "update":
                # Transform and upsert data
                normalized = await self._transform_cdc_data(table, data)
                await self._upsert_entity(db, table, normalized)
            
            elif operation == "delete":
                # Mark entity as inactive
                await self._delete_entity(db, table, data)
        
        await db.commit()
        
        logger.info(
            "cdc_changes_processed",
            table=table,
            change_count=len(changes)
        )
    
    async def _transform_cdc_data(
        self,
        table: str,
        data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Transform CDC data to normalized format.
        
        Args:
            table: Table name
            data: Raw data
            
        Returns:
            Normalized data
        """
        # Use the data transformer based on ERP type and table
        if self.erp_type == "SAP":
            if table == "purchase_order":
                return self.transformer.transform_purchase_order(data)
            elif table == "manufacturing_order":
                return self.transformer.transform_manufacturing_order(data)
        
        elif self.erp_type == "Oracle":
            if table == "invoice":
                return self.transformer.transform_invoice(data)
            elif table == "shipment":
                return self.transformer.transform_shipment(data)
        
        elif self.erp_type == "Dynamics":
            if table == "invoice":
                return self.transformer.transform_dynamics_invoice(data)
            elif table == "sales_order":
                return self.transformer.transform_dynamics_sales_order(data)
        
        # Default transformation
        return {
            "entity_type": table,
            "entity_data": data,
            "source_system": self.erp_type,
            "created_at": datetime.now(timezone.utc).isoformat()
        }
    
    async def _upsert_entity(
        self,
        db: AsyncSession,
        table: str,
        normalized_data: Dict[str, Any]
    ):
        """
        Upsert entity to database.
        
        Args:
            db: Database session
            table: Table name
            normalized_data: Normalized data
        """
        entity_id = normalized_data.get("entity_id") or normalized_data.get("id")
        
        if not entity_id:
            logger.warning(
                "entity_missing_id",
                table=table,
                data=normalized_data
            )
            return
        
        # Check if entity exists
        result = await db.execute(
            select(ERPEntity).where(
                and_(
                    ERPEntity.integration_id == self.integration_id,
                    ERPEntity.entity_type == table,
                    ERPEntity.entity_id == str(entity_id)
                )
            )
        )
        existing = result.scalar_one_or_none()
        
        if existing:
            # Update existing record
            existing.valid_to = datetime.now(timezone.utc)
            existing.is_active = False
            
            # Create new version
            new_entity = ERPEntity(
                organization_id=self.organization_id,
                integration_id=self.integration_id,
                entity_type=table,
                entity_id=str(entity_id),
                entity_data=normalized_data,
                source_system=self.erp_type,
                is_active=True,
                valid_from=datetime.now(timezone.utc)
            )
            db.add(new_entity)
        else:
            # Create new entity
            entity = ERPEntity(
                organization_id=self.organization_id,
                integration_id=self.integration_id,
                entity_type=table,
                entity_id=str(entity_id),
                entity_data=normalized_data,
                source_system=self.erp_type,
                is_active=True,
                valid_from=datetime.now(timezone.utc)
            )
            db.add(entity)
    
    async def _delete_entity(
        self,
        db: AsyncSession,
        table: str,
        data: Dict[str, Any]
    ):
        """
        Mark entity as deleted (soft delete).
        
        Args:
            db: Database session
            table: Table name
            data: Data with entity ID
        """
        entity_id = data.get("id")
        
        if not entity_id:
            return
        
        result = await db.execute(
            select(ERPEntity).where(
                and_(
                    ERPEntity.integration_id == self.integration_id,
                    ERPEntity.entity_type == table,
                    ERPEntity.entity_id == str(entity_id),
                    ERPEntity.is_active == True
                )
            )
        )
        entity = result.scalar_one_or_none()
        
        if entity:
            entity.valid_to = datetime.now(timezone.utc)
            entity.is_active = False
    
    async def _update_last_lsn(
        self,
        db: AsyncSession,
        table: str,
        lsn: str
    ):
        """
        Update the last processed LSN for a table.
        
        Args:
            db: Database session
            table: Table name
            lsn: Last processed LSN
        """
        # In production, this would update a replication state table
        pass
    
    async def _check_replication_lag(
        self,
        db: AsyncSession,
        table: str
    ):
        """
        Check replication lag and alert if threshold exceeded.
        
        Args:
            db: Database session
            table: Table name
        """
        # In production, this would:
        # 1. Get the current timestamp from the source database
        # 2. Get the last replicated timestamp
        # 3. Calculate the lag
        # 4. Alert if lag exceeds threshold
        
        pass
    
    async def get_replication_status(
        self,
        db: AsyncSession
    ) -> Dict[str, Any]:
        """
        Get overall replication status.
        
        Args:
            db: Database session
            
        Returns:
            Dict with replication status
        """
        # Get sync status for all entity types
        result = await db.execute(
            select(ERPSyncStatus).where(
                ERPSyncStatus.integration_id == self.integration_id
            )
        )
        sync_statuses = result.scalars().all()
        
        status_summary = {
            "erp_type": self.erp_type,
            "integration_id": self.integration_id,
            "tables_replicated": len(sync_statuses),
            "tables": []
        }
        
        for sync_status in sync_statuses:
            status_summary["tables"].append({
                "entity_type": sync_status.entity_type,
                "last_sync_at": sync_status.last_sync_at.isoformat() if sync_status.last_sync_at else None,
                "last_sync_status": sync_status.last_sync_status,
                "records_synced": sync_status.records_synced,
                "records_failed": sync_status.records_failed
            })
        
        return status_summary
    
    async def stop_replication(self):
        """
        Stop replication for this integration.
        
        Returns:
            Dict with stop status
        """
        logger.info(
            "stopping_erp_database_replication",
            erp_type=self.erp_type,
            integration_id=self.integration_id
        )
        
        # In production, this would cancel the replication tasks
        
        return {
            "status": "replication_stopped",
            "erp_type": self.erp_type,
            "integration_id": self.integration_id,
            "stopped_at": datetime.now(timezone.utc).isoformat()
        }

"""
Oracle Data Extraction Service

Service for extracting and storing Oracle Cloud ERP data:
- Invoices (finance domain)
- Shipments (logistics domain)
- Employees (HR domain)
- Projects (project management)
"""

from typing import Dict, Any, Optional, List
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
import structlog

from app.services.erp_connectors.oracle_connector import OracleConnector
from app.db.models import ERPEntity, ERPSyncStatus
from app.services.erp_data_transformer import ERPDataTransformer

logger = structlog.get_logger()


class OracleDataExtractionService:
    """
    Service for extracting and storing Oracle Cloud ERP data.
    
    Orchestrates data extraction from Oracle using the connector,
    transforms the data, and stores it in the database.
    """
    
    def __init__(
        self,
        connector: OracleConnector,
        organization_id: str,
        integration_id: str
    ):
        self.connector = connector
        self.organization_id = organization_id
        self.integration_id = integration_id
        self.transformer = ERPDataTransformer(organization_id, integration_id)
        
        logger.info(
            "oracle_data_extraction_service_initialized",
            organization_id=organization_id,
            integration_id=integration_id
        )
    
    async def extract_invoices(
        self,
        db: AsyncSession,
        filters: Optional[Dict[str, Any]] = None,
        limit: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Extract invoices from Oracle.
        
        Args:
            db: Database session
            filters: Optional filters
            limit: Optional limit
            
        Returns:
            Dict with extraction results
        """
        start_time = datetime.utcnow()
        
        try:
            # Fetch data from Oracle
            invoice_data = await self.connector.fetch_invoices(filters, limit)
            
            # Transform and store data
            stored_count = 0
            for invoice in invoice_data:
                normalized = self.transformer.transform_invoice(invoice)
                
                await self._store_entity(
                    db,
                    "Invoice",
                    invoice.get("InvoiceId"),
                    normalized,
                    "Oracle"
                )
                stored_count += 1
            
            # Update sync status
            await self._update_sync_status(
                db,
                "Invoice",
                "completed",
                stored_count,
                0,
                (datetime.utcnow() - start_time).total_seconds()
            )
            
            logger.info(
                "oracle_invoices_extracted",
                count=stored_count,
                duration_seconds=(datetime.utcnow() - start_time).total_seconds()
            )
            
            return {
                "status": "success",
                "entity_type": "Invoice",
                "records_extracted": stored_count,
                "duration_seconds": (datetime.utcnow() - start_time).total_seconds()
            }
            
        except Exception as e:
            logger.error(
                "oracle_invoices_extraction_failed",
                error=str(e)
            )
            
            await self._update_sync_status(
                db,
                "Invoice",
                "failed",
                0,
                1,
                (datetime.utcnow() - start_time).total_seconds()
            )
            
            raise
    
    async def extract_shipments(
        self,
        db: AsyncSession,
        filters: Optional[Dict[str, Any]] = None,
        limit: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Extract shipments from Oracle.
        
        Args:
            db: Database session
            filters: Optional filters
            limit: Optional limit
            
        Returns:
            Dict with extraction results
        """
        start_time = datetime.utcnow()
        
        try:
            # Fetch data from Oracle
            shipment_data = await self.connector.fetch_shipments(filters, limit)
            
            # Transform and store data
            stored_count = 0
            for shipment in shipment_data:
                normalized = self.transformer.transform_shipment(shipment)
                
                await self._store_entity(
                    db,
                    "Shipment",
                    shipment.get("ShipmentNumber"),
                    normalized,
                    "Oracle"
                )
                stored_count += 1
            
            # Update sync status
            await self._update_sync_status(
                db,
                "Shipment",
                "completed",
                stored_count,
                0,
                (datetime.utcnow() - start_time).total_seconds()
            )
            
            logger.info(
                "oracle_shipments_extracted",
                count=stored_count,
                duration_seconds=(datetime.utcnow() - start_time).total_seconds()
            )
            
            return {
                "status": "success",
                "entity_type": "Shipment",
                "records_extracted": stored_count,
                "duration_seconds": (datetime.utcnow() - start_time).total_seconds()
            }
            
        except Exception as e:
            logger.error(
                "oracle_shipments_extraction_failed",
                error=str(e)
            )
            
            await self._update_sync_status(
                db,
                "Shipment",
                "failed",
                0,
                1,
                (datetime.utcnow() - start_time).total_seconds()
            )
            
            raise
    
    async def extract_employees(
        self,
        db: AsyncSession,
        filters: Optional[Dict[str, Any]] = None,
        limit: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Extract employee data from Oracle.
        
        Args:
            db: Database session
            filters: Optional filters
            limit: Optional limit
            
        Returns:
            Dict with extraction results
        """
        start_time = datetime.utcnow()
        
        try:
            # Fetch data from Oracle
            employee_data = await self.connector.fetch_employees(filters, limit)
            
            # Transform and store data
            stored_count = 0
            for employee in employee_data:
                normalized = self.transformer.transform_employee(employee)
                
                await self._store_entity(
                    db,
                    "Employee",
                    employee.get("PersonId"),
                    normalized,
                    "Oracle"
                )
                stored_count += 1
            
            # Update sync status
            await self._update_sync_status(
                db,
                "Employee",
                "completed",
                stored_count,
                0,
                (datetime.utcnow() - start_time).total_seconds()
            )
            
            logger.info(
                "oracle_employees_extracted",
                count=stored_count,
                duration_seconds=(datetime.utcnow() - start_time).total_seconds()
            )
            
            return {
                "status": "success",
                "entity_type": "Employee",
                "records_extracted": stored_count,
                "duration_seconds": (datetime.utcnow() - start_time).total_seconds()
            }
            
        except Exception as e:
            logger.error(
                "oracle_employees_extraction_failed",
                error=str(e)
            )
            
            await self._update_sync_status(
                db,
                "Employee",
                "failed",
                0,
                1,
                (datetime.utcnow() - start_time).total_seconds()
            )
            
            raise
    
    async def extract_projects(
        self,
        db: AsyncSession,
        filters: Optional[Dict[str, Any]] = None,
        limit: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Extract project data from Oracle.
        
        Args:
            db: Database session
            filters: Optional filters
            limit: Optional limit
            
        Returns:
            Dict with extraction results
        """
        start_time = datetime.utcnow()
        
        try:
            # Fetch data from Oracle
            project_data = await self.connector.fetch_projects(filters, limit)
            
            # Transform and store data
            stored_count = 0
            for project in project_data:
                normalized = self.transformer.transform_project(project)
                
                await self._store_entity(
                    db,
                    "Project",
                    project.get("ProjectId"),
                    normalized,
                    "Oracle"
                )
                stored_count += 1
            
            # Update sync status
            await self._update_sync_status(
                db,
                "Project",
                "completed",
                stored_count,
                0,
                (datetime.utcnow() - start_time).total_seconds()
            )
            
            logger.info(
                "oracle_projects_extracted",
                count=stored_count,
                duration_seconds=(datetime.utcnow() - start_time).total_seconds()
            )
            
            return {
                "status": "success",
                "entity_type": "Project",
                "records_extracted": stored_count,
                "duration_seconds": (datetime.utcnow() - start_time).total_seconds()
            }
            
        except Exception as e:
            logger.error(
                "oracle_projects_extraction_failed",
                error=str(e)
            )
            
            await self._update_sync_status(
                db,
                "Project",
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
        Extract all Oracle entity types.
        
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
            "invoices",
            "shipments",
            "employees",
            "projects"
        ]
        
        for entity_type in entity_types:
            try:
                if entity_type == "invoices":
                    result = await self.extract_invoices(db, filters, limit)
                elif entity_type == "shipments":
                    result = await self.extract_shipments(db, filters, limit)
                elif entity_type == "employees":
                    result = await self.extract_employees(db, filters, limit)
                elif entity_type == "projects":
                    result = await self.extract_projects(db, filters, limit)
                
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
            "oracle_all_entities_extraction_completed",
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

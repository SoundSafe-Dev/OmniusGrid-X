"""
Dynamics 365 Data Extraction Service

Service for extracting and storing Dynamics 365 data:
- Invoices (finance domain)
- Payments (finance domain)
- Products (supply chain domain)
- Sales orders (CRM domain)
- Accounts/Contacts (CRM domain)
- Projects (project management)
"""

from typing import Dict, Any, Optional, List
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
import structlog

from app.services.erp_connectors.dynamics_connector import DynamicsConnector
from app.db.models import ERPEntity, ERPSyncStatus
from app.services.erp_data_transformer import ERPDataTransformer

logger = structlog.get_logger()


class DynamicsDataExtractionService:
    """
    Service for extracting and storing Dynamics 365 data.
    
    Orchestrates data extraction from Dynamics using the connector,
    transforms the data, and stores it in the database.
    """
    
    def __init__(
        self,
        connector: DynamicsConnector,
        organization_id: str,
        integration_id: str
    ):
        self.connector = connector
        self.organization_id = organization_id
        self.integration_id = integration_id
        self.transformer = ERPDataTransformer(organization_id, integration_id)
        
        logger.info(
            "dynamics_data_extraction_service_initialized",
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
        Extract invoices from Dynamics.
        
        Args:
            db: Database session
            filters: Optional filters
            limit: Optional limit
            
        Returns:
            Dict with extraction results
        """
        start_time = datetime.now(timezone.utc)
        
        try:
            # Fetch data from Dynamics
            invoice_data = await self.connector.fetch_invoices(filters, limit)
            
            # Transform and store data
            stored_count = 0
            for invoice in invoice_data:
                normalized = self.transformer.transform_dynamics_invoice(invoice)
                
                await self._store_entity(
                    db,
                    "Invoice",
                    invoice.get("invoiceid"),
                    normalized,
                    "Dynamics"
                )
                stored_count += 1
            
            # Update sync status
            await self._update_sync_status(
                db,
                "Invoice",
                "completed",
                stored_count,
                0,
                (datetime.now(timezone.utc) - start_time).total_seconds()
            )
            
            logger.info(
                "dynamics_invoices_extracted",
                count=stored_count,
                duration_seconds=(datetime.now(timezone.utc) - start_time).total_seconds()
            )
            
            return {
                "status": "success",
                "entity_type": "Invoice",
                "records_extracted": stored_count,
                "duration_seconds": (datetime.now(timezone.utc) - start_time).total_seconds()
            }
            
        except Exception as e:
            logger.error(
                "dynamics_invoices_extraction_failed",
                error=str(e)
            )
            
            await self._update_sync_status(
                db,
                "Invoice",
                "failed",
                0,
                1,
                (datetime.now(timezone.utc) - start_time).total_seconds()
            )
            
            raise
    
    async def extract_payments(
        self,
        db: AsyncSession,
        filters: Optional[Dict[str, Any]] = None,
        limit: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Extract payments from Dynamics.
        
        Args:
            db: Database session
            filters: Optional filters
            limit: Optional limit
            
        Returns:
            Dict with extraction results
        """
        start_time = datetime.now(timezone.utc)
        
        try:
            # Fetch data from Dynamics
            payment_data = await self.connector.fetch_payments(filters, limit)
            
            # Transform and store data
            stored_count = 0
            for payment in payment_data:
                normalized = self.transformer.transform_dynamics_payment(payment)
                
                await self._store_entity(
                    db,
                    "Payment",
                    payment.get("paymentid"),
                    normalized,
                    "Dynamics"
                )
                stored_count += 1
            
            # Update sync status
            await self._update_sync_status(
                db,
                "Payment",
                "completed",
                stored_count,
                0,
                (datetime.now(timezone.utc) - start_time).total_seconds()
            )
            
            logger.info(
                "dynamics_payments_extracted",
                count=stored_count,
                duration_seconds=(datetime.now(timezone.utc) - start_time).total_seconds()
            )
            
            return {
                "status": "success",
                "entity_type": "Payment",
                "records_extracted": stored_count,
                "duration_seconds": (datetime.now(timezone.utc) - start_time).total_seconds()
            }
            
        except Exception as e:
            logger.error(
                "dynamics_payments_extraction_failed",
                error=str(e)
            )
            
            await self._update_sync_status(
                db,
                "Payment",
                "failed",
                0,
                1,
                (datetime.now(timezone.utc) - start_time).total_seconds()
            )
            
            raise
    
    async def extract_products(
        self,
        db: AsyncSession,
        filters: Optional[Dict[str, Any]] = None,
        limit: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Extract products from Dynamics.
        
        Args:
            db: Database session
            filters: Optional filters
            limit: Optional limit
            
        Returns:
            Dict with extraction results
        """
        start_time = datetime.now(timezone.utc)
        
        try:
            # Fetch data from Dynamics
            product_data = await self.connector.fetch_products(filters, limit)
            
            # Transform and store data
            stored_count = 0
            for product in product_data:
                normalized = self.transformer.transform_dynamics_product(product)
                
                await self._store_entity(
                    db,
                    "Product",
                    product.get("productid"),
                    normalized,
                    "Dynamics"
                )
                stored_count += 1
            
            # Update sync status
            await self._update_sync_status(
                db,
                "Product",
                "completed",
                stored_count,
                0,
                (datetime.now(timezone.utc) - start_time).total_seconds()
            )
            
            logger.info(
                "dynamics_products_extracted",
                count=stored_count,
                duration_seconds=(datetime.now(timezone.utc) - start_time).total_seconds()
            )
            
            return {
                "status": "success",
                "entity_type": "Product",
                "records_extracted": stored_count,
                "duration_seconds": (datetime.now(timezone.utc) - start_time).total_seconds()
            }
            
        except Exception as e:
            logger.error(
                "dynamics_products_extraction_failed",
                error=str(e)
            )
            
            await self._update_sync_status(
                db,
                "Product",
                "failed",
                0,
                1,
                (datetime.now(timezone.utc) - start_time).total_seconds()
            )
            
            raise
    
    async def extract_sales_orders(
        self,
        db: AsyncSession,
        filters: Optional[Dict[str, Any]] = None,
        limit: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Extract sales orders from Dynamics.
        
        Args:
            db: Database session
            filters: Optional filters
            limit: Optional limit
            
        Returns:
            Dict with extraction results
        """
        start_time = datetime.now(timezone.utc)
        
        try:
            # Fetch data from Dynamics
            order_data = await self.connector.fetch_orders(filters, limit)
            
            # Transform and store data
            stored_count = 0
            for order in order_data:
                normalized = self.transformer.transform_dynamics_sales_order(order)
                
                await self._store_entity(
                    db,
                    "SalesOrder",
                    order.get("salesorderid"),
                    normalized,
                    "Dynamics"
                )
                stored_count += 1
            
            # Update sync status
            await self._update_sync_status(
                db,
                "SalesOrder",
                "completed",
                stored_count,
                0,
                (datetime.now(timezone.utc) - start_time).total_seconds()
            )
            
            logger.info(
                "dynamics_sales_orders_extracted",
                count=stored_count,
                duration_seconds=(datetime.now(timezone.utc) - start_time).total_seconds()
            )
            
            return {
                "status": "success",
                "entity_type": "SalesOrder",
                "records_extracted": stored_count,
                "duration_seconds": (datetime.now(timezone.utc) - start_time).total_seconds()
            }
            
        except Exception as e:
            logger.error(
                "dynamics_sales_orders_extraction_failed",
                error=str(e)
            )
            
            await self._update_sync_status(
                db,
                "SalesOrder",
                "failed",
                0,
                1,
                (datetime.now(timezone.utc) - start_time).total_seconds()
            )
            
            raise
    
    async def extract_accounts(
        self,
        db: AsyncSession,
        filters: Optional[Dict[str, Any]] = None,
        limit: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Extract CRM accounts from Dynamics.
        
        Args:
            db: Database session
            filters: Optional filters
            limit: Optional limit
            
        Returns:
            Dict with extraction results
        """
        start_time = datetime.now(timezone.utc)
        
        try:
            # Fetch data from Dynamics
            account_data = await self.connector.fetch_accounts(filters, limit)
            
            # Transform and store data
            stored_count = 0
            for account in account_data:
                normalized = self.transformer.transform_dynamics_account(account)
                
                await self._store_entity(
                    db,
                    "Account",
                    account.get("accountid"),
                    normalized,
                    "Dynamics"
                )
                stored_count += 1
            
            # Update sync status
            await self._update_sync_status(
                db,
                "Account",
                "completed",
                stored_count,
                0,
                (datetime.now(timezone.utc) - start_time).total_seconds()
            )
            
            logger.info(
                "dynamics_accounts_extracted",
                count=stored_count,
                duration_seconds=(datetime.now(timezone.utc) - start_time).total_seconds()
            )
            
            return {
                "status": "success",
                "entity_type": "Account",
                "records_extracted": stored_count,
                "duration_seconds": (datetime.now(timezone.utc) - start_time).total_seconds()
            }
            
        except Exception as e:
            logger.error(
                "dynamics_accounts_extraction_failed",
                error=str(e)
            )
            
            await self._update_sync_status(
                db,
                "Account",
                "failed",
                0,
                1,
                (datetime.now(timezone.utc) - start_time).total_seconds()
            )
            
            raise
    
    async def extract_projects(
        self,
        db: AsyncSession,
        filters: Optional[Dict[str, Any]] = None,
        limit: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Extract projects from Dynamics.
        
        Args:
            db: Database session
            filters: Optional filters
            limit: Optional limit
            
        Returns:
            Dict with extraction results
        """
        start_time = datetime.now(timezone.utc)
        
        try:
            # Fetch data from Dynamics
            project_data = await self.connector.fetch_projects(filters, limit)
            
            # Transform and store data
            stored_count = 0
            for project in project_data:
                normalized = self.transformer.transform_dynamics_project(project)
                
                await self._store_entity(
                    db,
                    "Project",
                    project.get("msdyn_projectid"),
                    normalized,
                    "Dynamics"
                )
                stored_count += 1
            
            # Update sync status
            await self._update_sync_status(
                db,
                "Project",
                "completed",
                stored_count,
                0,
                (datetime.now(timezone.utc) - start_time).total_seconds()
            )
            
            logger.info(
                "dynamics_projects_extracted",
                count=stored_count,
                duration_seconds=(datetime.now(timezone.utc) - start_time).total_seconds()
            )
            
            return {
                "status": "success",
                "entity_type": "Project",
                "records_extracted": stored_count,
                "duration_seconds": (datetime.now(timezone.utc) - start_time).total_seconds()
            }
            
        except Exception as e:
            logger.error(
                "dynamics_projects_extraction_failed",
                error=str(e)
            )
            
            await self._update_sync_status(
                db,
                "Project",
                "failed",
                0,
                1,
                (datetime.now(timezone.utc) - start_time).total_seconds()
            )
            
            raise
    
    async def extract_all_entities(
        self,
        db: AsyncSession,
        filters: Optional[Dict[str, Any]] = None,
        limit: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Extract all Dynamics entity types.
        
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
            "payments",
            "products",
            "sales_orders",
            "accounts",
            "projects"
        ]
        
        for entity_type in entity_types:
            try:
                if entity_type == "invoices":
                    result = await self.extract_invoices(db, filters, limit)
                elif entity_type == "payments":
                    result = await self.extract_payments(db, filters, limit)
                elif entity_type == "products":
                    result = await self.extract_products(db, filters, limit)
                elif entity_type == "sales_orders":
                    result = await self.extract_sales_orders(db, filters, limit)
                elif entity_type == "accounts":
                    result = await self.extract_accounts(db, filters, limit)
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
            "dynamics_all_entities_extraction_completed",
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
            existing.valid_to = datetime.now(timezone.utc)
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
                valid_from=datetime.now(timezone.utc)
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
                valid_from=datetime.now(timezone.utc)
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
        
        now = datetime.now(timezone.utc)
        
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

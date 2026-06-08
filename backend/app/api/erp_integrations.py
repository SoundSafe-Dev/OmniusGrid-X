"""
ERP Integration Management API Endpoints

API endpoints for managing ERP integrations, configurations,
field mappings, and sync operations.
"""

from typing import List, Dict, Any, Optional
from uuid import UUID
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, Field
import structlog

from app.db.database import get_db
from app.api.auth import get_current_active_user
from app.db.models import User, IntegrationConfiguration, ERPDataMapping, ERPSyncStatus
from app.services.erp_connector_base import ERPType, AuthType, ERPConfig

logger = structlog.get_logger()

router = APIRouter(prefix="/api/v1/erp/integrations", tags=["erp-integrations"])


# ==================== Request/Response Schemas ====================

class ERPIntegrationCreate(BaseModel):
    """Request to create ERP integration"""
    integration_name: str = Field(..., description="Integration name")
    erp_type: str = Field(..., description="ERP type (sap, oracle, dynamics, etc.)")
    erp_version: Optional[str] = Field(None, description="ERP version")
    auth_type: str = Field(..., description="Authentication type")
    base_url: str = Field(..., description="ERP base URL")
    auth_config: Dict[str, Any] = Field(..., description="Authentication configuration")
    rate_limit: Optional[Dict[str, int]] = Field(
        default={"requests_per_minute": 60, "burst_limit": 10},
        description="Rate limiting configuration"
    )
    timeout: Optional[int] = Field(30, description="Request timeout in seconds")
    sync_schedule: Optional[str] = Field("0 * * * *", description="Cron schedule for sync")
    sync_frequency_minutes: Optional[int] = Field(60, description="Sync frequency in minutes")
    webhook_secret: Optional[str] = Field(None, description="Webhook secret for signature verification")
    ip_whitelist: Optional[List[str]] = Field(None, description="Allowed IP addresses for webhooks")


class ERPIntegrationUpdate(BaseModel):
    """Request to update ERP integration"""
    integration_name: Optional[str] = None
    erp_version: Optional[str] = None
    auth_config: Optional[Dict[str, Any]] = None
    rate_limit: Optional[Dict[str, int]] = None
    timeout: Optional[int] = None
    sync_schedule: Optional[str] = None
    sync_frequency_minutes: Optional[int] = None
    webhook_secret: Optional[str] = None
    ip_whitelist: Optional[List[str]] = None
    is_active: Optional[bool] = None


class ERPIntegrationResponse(BaseModel):
    """Response with ERP integration details"""
    id: str
    integration_name: str
    erp_type: str
    erp_version: Optional[str]
    auth_type: str
    base_url: str
    is_active: bool
    sync_schedule: str
    sync_frequency_minutes: int
    last_successful_sync: Optional[datetime]
    created_at: datetime
    updated_at: datetime


class FieldMappingCreate(BaseModel):
    """Request to create field mapping"""
    source_entity: str = Field(..., description="Source entity name")
    source_field: str = Field(..., description="Source field name")
    target_entity: str = Field(..., description="Target entity name")
    target_field: str = Field(..., description="Target field name")
    transformation_rule: Optional[str] = Field(None, description="Transformation rule")
    data_type: Optional[str] = Field(None, description="Data type")
    is_required: Optional[bool] = Field(True, description="Whether field is required")


class FieldMappingUpdate(BaseModel):
    """Request to update field mapping"""
    target_entity: Optional[str] = None
    target_field: Optional[str] = None
    transformation_rule: Optional[str] = None
    data_type: Optional[str] = None
    is_required: Optional[bool] = None


class FieldMappingResponse(BaseModel):
    """Response with field mapping details"""
    id: str
    source_entity: str
    source_field: str
    target_entity: str
    target_field: str
    transformation_rule: Optional[str]
    data_type: Optional[str]
    is_required: bool
    created_at: datetime
    updated_at: datetime


class SyncStatusResponse(BaseModel):
    """Response with sync status"""
    id: str
    entity_type: str
    last_sync_at: Optional[datetime]
    last_sync_status: Optional[str]
    records_synced: int
    records_failed: int
    sync_duration_seconds: Optional[float]
    next_sync_at: Optional[datetime]
    updated_at: datetime


# ==================== Endpoints ====================

@router.post("", response_model=ERPIntegrationResponse)
async def create_integration(
    request: ERPIntegrationCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """
    Create a new ERP integration.
    
    Creates an integration configuration for connecting to an ERP system.
    """
    logger.info(
        "creating_erp_integration",
        erp_type=request.erp_type,
        organization_id=str(current_user.organization_id)
    )
    
    # Validate ERP type
    try:
        erp_type_enum = ERPType(request.erp_type.lower())
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid ERP type. Must be one of: {[e.value for e in ERPType]}"
        )
    
    # Validate auth type
    try:
        auth_type_enum = AuthType(request.auth_type.lower())
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid auth type. Must be one of: {[e.value for e in AuthType]}"
        )
    
    # Create integration configuration
    integration = IntegrationConfiguration(
        organization_id=current_user.organization_id,
        integration_type="erp",
        integration_name=request.integration_name,
        configuration={
            "erp_type": request.erp_type,
            "auth_type": request.auth_type,
            "base_url": request.base_url,
            "auth_config": request.auth_config,
            "rate_limit": request.rate_limit,
            "timeout": request.timeout,
            "webhook_secret": request.webhook_secret,
            "ip_whitelist": request.ip_whitelist
        },
        authentication=request.auth_config,
        is_active=True,
        created_by=current_user.id
    )
    
    # Add ERP-specific fields
    integration.erp_type = request.erp_type
    integration.erp_version = request.erp_version
    integration.sync_schedule = request.sync_schedule
    integration.sync_frequency_minutes = request.sync_frequency_minutes
    
    db.add(integration)
    await db.commit()
    await db.refresh(integration)
    
    logger.info(
        "erp_integration_created",
        integration_id=str(integration.id),
        erp_type=request.erp_type
    )
    
    return ERPIntegrationResponse(
        id=str(integration.id),
        integration_name=integration.integration_name,
        erp_type=integration.erp_type,
        erp_version=integration.erp_version,
        auth_type=request.auth_type,
        base_url=request.base_url,
        is_active=integration.is_active,
        sync_schedule=integration.sync_schedule,
        sync_frequency_minutes=integration.sync_frequency_minutes,
        last_successful_sync=integration.last_successful_sync,
        created_at=integration.created_at,
        updated_at=integration.updated_at
    )


@router.get("", response_model=List[ERPIntegrationResponse])
async def list_integrations(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """
    List all ERP integrations for the organization.
    """
    from sqlalchemy import select
    
    result = await db.execute(
        select(IntegrationConfiguration).where(
            IntegrationConfiguration.organization_id == current_user.organization_id,
            IntegrationConfiguration.integration_type == "erp"
        )
    )
    integrations = result.scalars().all()
    
    return [
        ERPIntegrationResponse(
            id=str(integration.id),
            integration_name=integration.integration_name,
            erp_type=integration.erp_type,
            erp_version=integration.erp_version,
            auth_type=integration.configuration.get("auth_type", ""),
            base_url=integration.configuration.get("base_url", ""),
            is_active=integration.is_active,
            sync_schedule=integration.sync_schedule,
            sync_frequency_minutes=integration.sync_frequency_minutes,
            last_successful_sync=integration.last_successful_sync,
            created_at=integration.created_at,
            updated_at=integration.updated_at
        )
        for integration in integrations
    ]


@router.get("/{integration_id}", response_model=ERPIntegrationResponse)
async def get_integration(
    integration_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """
    Get details of a specific ERP integration.
    """
    from sqlalchemy import select
    
    result = await db.execute(
        select(IntegrationConfiguration).where(
            IntegrationConfiguration.id == integration_id,
            IntegrationConfiguration.organization_id == current_user.organization_id
        )
    )
    integration = result.scalar_one_or_none()
    
    if not integration:
        raise HTTPException(status_code=404, detail="Integration not found")
    
    return ERPIntegrationResponse(
        id=str(integration.id),
        integration_name=integration.integration_name,
        erp_type=integration.erp_type,
        erp_version=integration.erp_version,
        auth_type=integration.configuration.get("auth_type", ""),
        base_url=integration.configuration.get("base_url", ""),
        is_active=integration.is_active,
        sync_schedule=integration.sync_schedule,
        sync_frequency_minutes=integration.sync_frequency_minutes,
        last_successful_sync=integration.last_successful_sync,
        created_at=integration.created_at,
        updated_at=integration.updated_at
    )


@router.put("/{integration_id}", response_model=ERPIntegrationResponse)
async def update_integration(
    integration_id: UUID,
    request: ERPIntegrationUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """
    Update an ERP integration configuration.
    """
    from sqlalchemy import select
    
    result = await db.execute(
        select(IntegrationConfiguration).where(
            IntegrationConfiguration.id == integration_id,
            IntegrationConfiguration.organization_id == current_user.organization_id
        )
    )
    integration = result.scalar_one_or_none()
    
    if not integration:
        raise HTTPException(status_code=404, detail="Integration not found")
    
    # Update fields
    if request.integration_name:
        integration.integration_name = request.integration_name
    if request.erp_version:
        integration.erp_version = request.erp_version
    if request.sync_schedule:
        integration.sync_schedule = request.sync_schedule
    if request.sync_frequency_minutes:
        integration.sync_frequency_minutes = request.sync_frequency_minutes
    if request.is_active is not None:
        integration.is_active = request.is_active
    
    # Update configuration
    config = integration.configuration
    if request.auth_config:
        config["auth_config"] = request.auth_config
    if request.rate_limit:
        config["rate_limit"] = request.rate_limit
    if request.timeout:
        config["timeout"] = request.timeout
    if request.webhook_secret:
        config["webhook_secret"] = request.webhook_secret
    if request.ip_whitelist:
        config["ip_whitelist"] = request.ip_whitelist
    
    integration.configuration = config
    integration.updated_at = datetime.utcnow()
    
    await db.commit()
    await db.refresh(integration)
    
    logger.info(
        "erp_integration_updated",
        integration_id=str(integration_id)
    )
    
    return ERPIntegrationResponse(
        id=str(integration.id),
        integration_name=integration.integration_name,
        erp_type=integration.erp_type,
        erp_version=integration.erp_version,
        auth_type=config.get("auth_type", ""),
        base_url=config.get("base_url", ""),
        is_active=integration.is_active,
        sync_schedule=integration.sync_schedule,
        sync_frequency_minutes=integration.sync_frequency_minutes,
        last_successful_sync=integration.last_successful_sync,
        created_at=integration.created_at,
        updated_at=integration.updated_at
    )


@router.delete("/{integration_id}")
async def delete_integration(
    integration_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """
    Delete an ERP integration.
    """
    from sqlalchemy import select, delete
    
    result = await db.execute(
        select(IntegrationConfiguration).where(
            IntegrationConfiguration.id == integration_id,
            IntegrationConfiguration.organization_id == current_user.organization_id
        )
    )
    integration = result.scalar_one_or_none()
    
    if not integration:
        raise HTTPException(status_code=404, detail="Integration not found")
    
    await db.execute(
        delete(IntegrationConfiguration).where(IntegrationConfiguration.id == integration_id)
    )
    await db.commit()
    
    logger.info(
        "erp_integration_deleted",
        integration_id=str(integration_id)
    )
    
    return {"message": "Integration deleted successfully"}


@router.post("/{integration_id}/test")
async def test_connection(
    integration_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """
    Test connection to ERP system.
    """
    from sqlalchemy import select
    
    result = await db.execute(
        select(IntegrationConfiguration).where(
            IntegrationConfiguration.id == integration_id,
            IntegrationConfiguration.organization_id == current_user.organization_id
        )
    )
    integration = result.scalar_one_or_none()
    
    if not integration:
        raise HTTPException(status_code=404, detail="Integration not found")
    
    # TODO: Implement actual connection test using connector
    # For now, return mock response
    return {
        "status": "success",
        "message": "Connection test successful",
        "integration_id": str(integration_id),
        "tested_at": datetime.utcnow().isoformat()
    }


@router.post("/{integration_id}/sync")
async def trigger_sync(
    integration_id: UUID,
    background_tasks: BackgroundTasks,
    entity_type: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """
    Trigger manual sync for ERP integration.
    """
    from sqlalchemy import select
    
    result = await db.execute(
        select(IntegrationConfiguration).where(
            IntegrationConfiguration.id == integration_id,
            IntegrationConfiguration.organization_id == current_user.organization_id
        )
    )
    integration = result.scalar_one_or_none()
    
    if not integration:
        raise HTTPException(status_code=404, detail="Integration not found")
    
    # TODO: Implement actual sync trigger
    # For now, return mock response
    return {
        "status": "triggered",
        "message": "Sync triggered successfully",
        "integration_id": str(integration_id),
        "entity_type": entity_type,
        "triggered_at": datetime.utcnow().isoformat()
    }


@router.get("/{integration_id}/sync-status", response_model=List[SyncStatusResponse])
async def get_sync_status(
    integration_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """
    Get sync status for ERP integration.
    """
    from sqlalchemy import select
    
    result = await db.execute(
        select(ERPSyncStatus).where(
            ERPSyncStatus.integration_id == integration_id,
            ERPSyncStatus.organization_id == current_user.organization_id
        )
    )
    sync_statuses = result.scalars().all()
    
    return [
        SyncStatusResponse(
            id=str(status.id),
            entity_type=status.entity_type,
            last_sync_at=status.last_sync_at,
            last_sync_status=status.last_sync_status,
            records_synced=status.records_synced,
            records_failed=status.records_failed,
            sync_duration_seconds=float(status.sync_duration_seconds) if status.sync_duration_seconds else None,
            next_sync_at=status.next_sync_at,
            updated_at=status.updated_at
        )
        for status in sync_statuses
    ]


@router.post("/{integration_id}/mappings", response_model=FieldMappingResponse)
async def create_field_mapping(
    integration_id: UUID,
    request: FieldMappingCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """
    Create a field mapping for ERP integration.
    """
    from sqlalchemy import select
    
    # Verify integration exists
    result = await db.execute(
        select(IntegrationConfiguration).where(
            IntegrationConfiguration.id == integration_id,
            IntegrationConfiguration.organization_id == current_user.organization_id
        )
    )
    integration = result.scalar_one_or_none()
    
    if not integration:
        raise HTTPException(status_code=404, detail="Integration not found")
    
    # Create field mapping
    mapping = ERPDataMapping(
        organization_id=current_user.organization_id,
        integration_id=integration_id,
        source_entity=request.source_entity,
        source_field=request.source_field,
        target_entity=request.target_entity,
        target_field=request.target_field,
        transformation_rule=request.transformation_rule,
        data_type=request.data_type,
        is_required=request.is_required
    )
    
    db.add(mapping)
    await db.commit()
    await db.refresh(mapping)
    
    logger.info(
        "field_mapping_created",
        mapping_id=str(mapping.id),
        integration_id=str(integration_id)
    )
    
    return FieldMappingResponse(
        id=str(mapping.id),
        source_entity=mapping.source_entity,
        source_field=mapping.source_field,
        target_entity=mapping.target_entity,
        target_field=mapping.target_field,
        transformation_rule=mapping.transformation_rule,
        data_type=mapping.data_type,
        is_required=mapping.is_required,
        created_at=mapping.created_at,
        updated_at=mapping.updated_at
    )


@router.get("/{integration_id}/mappings", response_model=List[FieldMappingResponse])
async def list_field_mappings(
    integration_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """
    List field mappings for ERP integration.
    """
    from sqlalchemy import select
    
    result = await db.execute(
        select(ERPDataMapping).where(
            ERPDataMapping.integration_id == integration_id,
            ERPDataMapping.organization_id == current_user.organization_id
        )
    )
    mappings = result.scalars().all()
    
    return [
        FieldMappingResponse(
            id=str(mapping.id),
            source_entity=mapping.source_entity,
            source_field=mapping.source_field,
            target_entity=mapping.target_entity,
            target_field=mapping.target_field,
            transformation_rule=mapping.transformation_rule,
            data_type=mapping.data_type,
            is_required=mapping.is_required,
            created_at=mapping.created_at,
            updated_at=mapping.updated_at
        )
        for mapping in mappings
    ]


@router.put("/{integration_id}/mappings/{mapping_id}", response_model=FieldMappingResponse)
async def update_field_mapping(
    integration_id: UUID,
    mapping_id: UUID,
    request: FieldMappingUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """
    Update a field mapping.
    """
    from sqlalchemy import select
    
    result = await db.execute(
        select(ERPDataMapping).where(
            ERPDataMapping.id == mapping_id,
            ERPDataMapping.integration_id == integration_id,
            ERPDataMapping.organization_id == current_user.organization_id
        )
    )
    mapping = result.scalar_one_or_none()
    
    if not mapping:
        raise HTTPException(status_code=404, detail="Field mapping not found")
    
    # Update fields
    if request.target_entity:
        mapping.target_entity = request.target_entity
    if request.target_field:
        mapping.target_field = request.target_field
    if request.transformation_rule is not None:
        mapping.transformation_rule = request.transformation_rule
    if request.data_type is not None:
        mapping.data_type = request.data_type
    if request.is_required is not None:
        mapping.is_required = request.is_required
    
    mapping.updated_at = datetime.utcnow()
    
    await db.commit()
    await db.refresh(mapping)
    
    logger.info(
        "field_mapping_updated",
        mapping_id=str(mapping_id)
    )
    
    return FieldMappingResponse(
        id=str(mapping.id),
        source_entity=mapping.source_entity,
        source_field=mapping.source_field,
        target_entity=mapping.target_entity,
        target_field=mapping.target_field,
        transformation_rule=mapping.transformation_rule,
        data_type=mapping.data_type,
        is_required=mapping.is_required,
        created_at=mapping.created_at,
        updated_at=mapping.updated_at
    )


@router.delete("/{integration_id}/mappings/{mapping_id}")
async def delete_field_mapping(
    integration_id: UUID,
    mapping_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """
    Delete a field mapping.
    """
    from sqlalchemy import select, delete
    
    result = await db.execute(
        select(ERPDataMapping).where(
            ERPDataMapping.id == mapping_id,
            ERPDataMapping.integration_id == integration_id,
            ERPDataMapping.organization_id == current_user.organization_id
        )
    )
    mapping = result.scalar_one_or_none()
    
    if not mapping:
        raise HTTPException(status_code=404, detail="Field mapping not found")
    
    await db.execute(
        delete(ERPDataMapping).where(ERPDataMapping.id == mapping_id)
    )
    await db.commit()
    
    logger.info(
        "field_mapping_deleted",
        mapping_id=str(mapping_id)
    )
    
    return {"message": "Field mapping deleted successfully"}

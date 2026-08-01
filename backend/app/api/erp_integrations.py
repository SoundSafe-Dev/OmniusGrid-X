"""
ERP Integration Management API Endpoints

API endpoints for managing ERP integrations, configurations,
field mappings, and sync operations.
"""

from typing import List, Dict, Any, Optional
from uuid import UUID
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, Field
import structlog

from app.core.tenant import get_tenant_db, tenant_session
# NOTE (FS-56, for HARSH's review): ERP routes now use get_tenant_db — 020's
# RLS policies were rewritten onto the canonical app.current_org_id GUC, and a
# session that never sets it would read zero rows under any non-owner DB role.
from app.api.auth import get_current_active_user
from app.db.models import User, IntegrationConfiguration, ERPDataMapping, ERPSyncStatus, ERPEntity
from app.services.erp_connector_base import ERPType, AuthType, ERPConfig
from app.services.erp_connector_factory import (
    ERPConnectorFactory,
    ERPConnectorUnavailable,
    UnsupportedERPType,
)

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
    db: AsyncSession = Depends(get_tenant_db),
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
    db: AsyncSession = Depends(get_tenant_db),
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
    db: AsyncSession = Depends(get_tenant_db),
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
    db: AsyncSession = Depends(get_tenant_db),
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
    integration.updated_at = datetime.now(timezone.utc)
    
    await db.commit()
    
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
    db: AsyncSession = Depends(get_tenant_db),
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
    db: AsyncSession = Depends(get_tenant_db),
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

    # Build the concrete connector and run its real health check.
    tested_at = datetime.now(timezone.utc)
    try:
        connector = ERPConnectorFactory.create(integration)
    except UnsupportedERPType as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except ERPConnectorUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    try:
        health = await connector.health_check()
        status, message = interpret_health(health)
        details = health
    except Exception as exc:  # real connection failure — report, don't 500
        status, message, details = "error", str(exc), {}
    finally:
        try:
            await connector.close()
        except Exception:
            pass

    # Persist the outcome on the integration row.
    integration.health_status = status
    integration.last_health_check = tested_at
    await db.commit()

    return {
        "status": status,
        "message": message,
        "details": details,
        "integration_id": str(integration_id),
        "tested_at": tested_at.isoformat(),
    }


@router.post("/{integration_id}/sync")
async def trigger_sync(
    integration_id: UUID,
    background_tasks: BackgroundTasks,
    entity_type: Optional[str] = None,
    db: AsyncSession = Depends(get_tenant_db),
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

    # Resolve which entity types to sync: explicit param, else the distinct
    # source entities from the field mappings.
    if entity_type:
        entity_types = [entity_type]
    else:
        maps = await db.execute(
            select(ERPDataMapping.source_entity).where(
                ERPDataMapping.integration_id == integration_id
            ).distinct()
        )
        entity_types = [row[0] for row in maps.all() if row[0]]

    if not entity_types:
        raise HTTPException(
            status_code=400,
            detail="No entity_type given and no field mappings to infer entities from",
        )

    # Run off the request path so long syncs don't block the response.
    background_tasks.add_task(
        run_erp_sync, str(integration_id), str(current_user.organization_id), entity_types
    )
    return {
        "status": "triggered",
        "message": f"Sync triggered for {len(entity_types)} entity type(s)",
        "integration_id": str(integration_id),
        "entity_types": entity_types,
        "triggered_at": datetime.now(timezone.utc).isoformat(),
    }


def interpret_health(health: Dict[str, Any]) -> tuple:
    """Reduce a connector health_check() dict to (status, message).

    Connectors vary: some return {"healthy": bool}, some {"status": "healthy"}.
    Treat healthy/ok/connected as success; anything else as an error.
    """
    healthy = health.get("healthy")
    if healthy is None:
        healthy = str(health.get("status", "")).lower() in ("healthy", "ok", "connected", "up")
    status = "success" if healthy else "error"
    default = "Connection test successful" if status == "success" else "Connection test failed"
    return status, health.get("message", default)


def extract_entity_id(record: Dict[str, Any], index: int) -> str:
    """Best-effort stable id for a fetched ERP record."""
    for key in ("id", "Id", "ID", "entity_id", "number", "Number", "key", "Key"):
        if record.get(key) not in (None, ""):
            return str(record[key])
    return f"row-{index}"


async def run_erp_sync(integration_id: str, organization_id: str, entity_types: List[str]) -> Dict[str, Any]:
    """Fetch each entity type via the connector, upsert erp_entities, and record
    per-entity sync status inside the caller's trusted tenant scope."""
    from sqlalchemy import select as _select

    summary: Dict[str, Any] = {}
    connector = None
    try:
        async with tenant_session(organization_id) as db:
            integration = (
                await db.execute(
                    _select(IntegrationConfiguration).where(
                        IntegrationConfiguration.id == integration_id,
                        IntegrationConfiguration.organization_id == organization_id,
                    )
                )
            ).scalar_one_or_none()
            if integration is None:
                return {"error": "integration not found"}

            try:
                connector = ERPConnectorFactory.create(integration)
            except (UnsupportedERPType, ERPConnectorUnavailable) as exc:
                logger.error(
                    "erp_sync_connector_error",
                    integration_id=integration_id,
                    error=str(exc),
                )
                return {"error": str(exc)}

            source_system = str(integration.erp_type or "erp")
            any_success = False
            for etype in entity_types:
                started = datetime.now(timezone.utc)
                synced = failed = 0
                status = "success"
                try:
                    records = await connector.fetch_data(etype) or []
                    for i, record in enumerate(records):
                        eid = extract_entity_id(record, i)
                        existing = (
                            await db.execute(
                                _select(ERPEntity).where(
                                    ERPEntity.integration_id == integration_id,
                                    ERPEntity.organization_id == organization_id,
                                    ERPEntity.entity_type == etype,
                                    ERPEntity.entity_id == eid,
                                )
                            )
                        ).scalar_one_or_none()
                        if existing is None:
                            db.add(ERPEntity(
                                organization_id=organization_id,
                                integration_id=integration_id,
                                entity_type=etype,
                                entity_id=eid,
                                entity_data=record,
                                source_system=source_system,
                            ))
                        else:
                            existing.entity_data = record
                            existing.updated_at = datetime.now(timezone.utc)
                        synced += 1
                    any_success = True
                except Exception as exc:
                    status, failed = "failed", 1
                    logger.error(
                        "erp_sync_entity_failed",
                        entity_type=etype,
                        error=str(exc),
                    )

                duration = (datetime.now(timezone.utc) - started).total_seconds()
                sync_row = (
                    await db.execute(
                        _select(ERPSyncStatus).where(
                            ERPSyncStatus.integration_id == integration_id,
                            ERPSyncStatus.organization_id == organization_id,
                            ERPSyncStatus.entity_type == etype,
                        )
                    )
                ).scalar_one_or_none()
                if sync_row is None:
                    sync_row = ERPSyncStatus(
                        organization_id=organization_id,
                        integration_id=integration_id,
                        entity_type=etype,
                    )
                    db.add(sync_row)
                sync_row.last_sync_at = started
                sync_row.last_sync_status = status
                sync_row.records_synced = synced
                sync_row.records_failed = failed
                sync_row.sync_duration_seconds = int(duration)
                summary[etype] = {
                    "status": status,
                    "records_synced": synced,
                    "records_failed": failed,
                }

            if any_success:
                integration.last_successful_sync = datetime.now(timezone.utc)
            await db.commit()
    finally:
        if connector is not None:
            try:
                await connector.close()
            except Exception:
                pass
    return summary


@router.get("/{integration_id}/sync-status", response_model=List[SyncStatusResponse])
async def get_sync_status(
    integration_id: UUID,
    db: AsyncSession = Depends(get_tenant_db),
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
    db: AsyncSession = Depends(get_tenant_db),
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
    db: AsyncSession = Depends(get_tenant_db),
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
    db: AsyncSession = Depends(get_tenant_db),
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
    
    mapping.updated_at = datetime.now(timezone.utc)
    
    await db.commit()
    
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
    db: AsyncSession = Depends(get_tenant_db),
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


# ==================== ERP data surfaces (ERP hub page) ====================

@router.get("/{integration_id}/entities")
async def list_erp_entities(
    integration_id: UUID,
    entity_type: Optional[str] = None,
    limit: int = 200,
    db: AsyncSession = Depends(get_tenant_db),
    current_user: User = Depends(get_current_active_user),
):
    """Synced ERP business objects (erp_entities) for the hub's Entities tab."""
    from sqlalchemy import select

    query = select(ERPEntity).where(
        ERPEntity.integration_id == integration_id,
        ERPEntity.organization_id == current_user.organization_id,
        ERPEntity.is_active == True,  # noqa: E712
    )
    if entity_type:
        query = query.where(ERPEntity.entity_type == entity_type)
    rows = (await db.execute(query.order_by(ERPEntity.updated_at.desc()).limit(min(limit, 1000)))).scalars().all()
    return [{
        "id": str(e.id),
        "entity_type": e.entity_type,
        "entity_id": e.entity_id,
        "source_system": e.source_system,
        "entity_data": e.entity_data,
        "updated_at": e.updated_at.isoformat() if e.updated_at else None,
    } for e in rows]


@router.get("/{integration_id}/events")
async def list_erp_events(
    integration_id: UUID,
    status: Optional[str] = None,
    limit: int = 100,
    db: AsyncSession = Depends(get_tenant_db),
    current_user: User = Depends(get_current_active_user),
):
    """Webhook/sync event feed (erp_integration_events) for the hub's Events tab."""
    from sqlalchemy import select
    from app.db.models import ERPIntegrationEvent

    query = select(ERPIntegrationEvent).where(
        ERPIntegrationEvent.integration_id == integration_id,
        ERPIntegrationEvent.organization_id == current_user.organization_id,
    )
    if status:
        query = query.where(ERPIntegrationEvent.processing_status == status)
    rows = (await db.execute(query.order_by(ERPIntegrationEvent.created_at.desc()).limit(min(limit, 500)))).scalars().all()
    return [{
        "id": str(ev.id),
        "event_type": ev.event_type,
        "event_id": ev.event_id,
        "source_system": ev.source_system,
        "entity_type": ev.entity_type,
        "entity_id": ev.entity_id,
        "processing_status": ev.processing_status,
        "created_at": ev.created_at.isoformat() if ev.created_at else None,
    } for ev in rows]


@router.get("/correlations/recent")
async def list_erp_correlations(
    limit: int = 100,
    db: AsyncSession = Depends(get_tenant_db),
    current_user: User = Depends(get_current_active_user),
):
    """ERP<->sensor correlations recorded in erp_correlations (AI tab)."""
    from sqlalchemy import select
    from app.db.models import ERPCorrelation

    rows = (await db.execute(
        select(ERPCorrelation)
        .where(ERPCorrelation.organization_id == current_user.organization_id)
        .order_by(ERPCorrelation.created_at.desc()).limit(min(limit, 500))
    )).scalars().all()
    return [{
        "id": str(c.id),
        "correlation_type": c.correlation_type,
        "erp_event_id": str(c.erp_event_id) if c.erp_event_id else None,
        "sensor_event_id": c.sensor_event_id,
        "correlation_score": float(c.correlation_score) if c.correlation_score is not None else None,
        "created_at": c.created_at.isoformat() if c.created_at else None,
    } for c in rows]

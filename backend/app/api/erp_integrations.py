"""ERP integration management API."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_active_user
from app.core.config import settings
from app.db.database import AsyncSessionLocal
from app.db.models import (
    ERPDataMapping,
    ERPEntity,
    ERPSyncStatus,
    IntegrationConfiguration,
    User,
)
from app.middleware.rate_limit import rate_limit
from app.middleware.rbac import require_admin
from app.middleware.tenant_isolation import get_tenant_db, get_tenant_org_id
from app.services.erp_connector_base import AuthType, ERPType
from app.services.erp_connector_factory import create_erp_connector
from app.services.erp_error_handler import ERPErrorHandler

logger = structlog.get_logger()

router = APIRouter()


class ERPIntegrationCreate(BaseModel):
    integration_name: str = Field(..., min_length=1, max_length=255)
    erp_type: ERPType = ERPType.GENERIC
    erp_version: str | None = None
    auth_type: AuthType = AuthType.NONE
    base_url: str = Field(..., min_length=1, max_length=500)
    auth_config: dict[str, Any] = Field(default_factory=dict)
    rate_limit: dict[str, int] = Field(
        default_factory=lambda: {"requests_per_minute": 60, "burst_limit": 10}
    )
    timeout: int = Field(30, ge=1, le=300)
    sync_schedule: str | None = "0 * * * *"
    sync_frequency_minutes: int = Field(60, ge=1)
    health_check_path: str | None = None
    entity_path_template: str | None = "/{entity_type}"
    headers: dict[str, str] = Field(default_factory=dict)


class ERPIntegrationUpdate(BaseModel):
    integration_name: str | None = Field(None, min_length=1, max_length=255)
    erp_version: str | None = None
    auth_config: dict[str, Any] | None = None
    rate_limit: dict[str, int] | None = None
    timeout: int | None = Field(None, ge=1, le=300)
    sync_schedule: str | None = None
    sync_frequency_minutes: int | None = Field(None, ge=1)
    health_check_path: str | None = None
    entity_path_template: str | None = None
    headers: dict[str, str] | None = None
    is_active: bool | None = None


class ERPIntegrationResponse(BaseModel):
    id: UUID
    integration_name: str
    erp_type: str | None
    erp_version: str | None
    auth_type: str
    base_url: str
    is_active: bool
    sync_schedule: str | None
    sync_frequency_minutes: int | None
    last_successful_sync: datetime | None
    health_status: str | None
    last_health_check: datetime | None
    created_at: datetime
    updated_at: datetime


class FieldMappingCreate(BaseModel):
    source_entity: str = Field(..., min_length=1, max_length=100)
    source_field: str = Field(..., min_length=1, max_length=100)
    target_entity: str = Field(..., min_length=1, max_length=100)
    target_field: str = Field(..., min_length=1, max_length=100)
    transformation_rule: str | None = None
    data_type: str | None = None
    is_required: bool = True


class FieldMappingUpdate(BaseModel):
    target_entity: str | None = Field(None, min_length=1, max_length=100)
    target_field: str | None = Field(None, min_length=1, max_length=100)
    transformation_rule: str | None = None
    data_type: str | None = None
    is_required: bool | None = None


class FieldMappingResponse(BaseModel):
    id: UUID
    source_entity: str
    source_field: str
    target_entity: str
    target_field: str
    transformation_rule: str | None
    data_type: str | None
    is_required: bool
    created_at: datetime
    updated_at: datetime


class ERPSyncRequest(BaseModel):
    entity_type: str = Field(..., min_length=1, max_length=100)
    filters: dict[str, Any] = Field(default_factory=dict)
    limit: int | None = Field(None, ge=1, le=10000)


class ERPSyncTriggerResponse(BaseModel):
    integration_id: UUID
    entity_type: str
    status: str
    triggered_at: datetime


class SyncStatusResponse(BaseModel):
    id: UUID
    entity_type: str
    last_sync_at: datetime | None
    last_sync_status: str | None
    records_synced: int
    records_failed: int
    sync_duration_seconds: float | None
    next_sync_at: datetime | None
    updated_at: datetime


def _integration_response(integration: IntegrationConfiguration) -> ERPIntegrationResponse:
    config = integration.configuration or {}
    return ERPIntegrationResponse(
        id=integration.id,
        integration_name=integration.integration_name,
        erp_type=integration.erp_type,
        erp_version=integration.erp_version,
        auth_type=str(config.get("auth_type") or AuthType.NONE.value),
        base_url=str(config.get("base_url") or ""),
        is_active=integration.is_active,
        sync_schedule=integration.sync_schedule,
        sync_frequency_minutes=integration.sync_frequency_minutes,
        last_successful_sync=integration.last_successful_sync,
        health_status=integration.health_status,
        last_health_check=integration.last_health_check,
        created_at=integration.created_at,
        updated_at=integration.updated_at,
    )


def _create_configuration(payload: ERPIntegrationCreate) -> dict[str, Any]:
    return {
        "erp_type": payload.erp_type.value,
        "auth_type": payload.auth_type.value,
        "base_url": payload.base_url,
        "auth_config": payload.auth_config,
        "rate_limit": payload.rate_limit,
        "timeout": payload.timeout,
        "health_check_path": payload.health_check_path,
        "entity_path_template": payload.entity_path_template,
        "headers": payload.headers,
    }


async def _get_erp_integration(
    db: AsyncSession,
    integration_id: UUID,
    org_id: UUID,
) -> IntegrationConfiguration:
    result = await db.execute(
        select(IntegrationConfiguration).where(
            IntegrationConfiguration.id == integration_id,
            IntegrationConfiguration.organization_id == org_id,
            IntegrationConfiguration.integration_type == "erp",
        )
    )
    integration = result.scalar_one_or_none()
    if not integration:
        raise HTTPException(status_code=404, detail="ERP integration not found")
    return integration


@router.post("", response_model=ERPIntegrationResponse, status_code=status.HTTP_201_CREATED)
@rate_limit("20/minute")
@require_admin()
async def create_integration(
    request: Request,
    payload: ERPIntegrationCreate,
    current_user: User = Depends(get_current_active_user),
    org_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    integration = IntegrationConfiguration(
        organization_id=org_id,
        integration_type="erp",
        integration_name=payload.integration_name,
        configuration=_create_configuration(payload),
        authentication=payload.auth_config,
        is_active=True,
        created_by=current_user.id,
        erp_type=payload.erp_type.value,
        erp_version=payload.erp_version,
        sync_schedule=payload.sync_schedule,
        sync_frequency_minutes=payload.sync_frequency_minutes,
    )
    db.add(integration)
    await db.commit()
    await db.refresh(integration)
    return _integration_response(integration)


@router.get("", response_model=list[ERPIntegrationResponse])
@rate_limit("100/minute")
async def list_integrations(
    request: Request,
    org_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    result = await db.execute(
        select(IntegrationConfiguration)
        .where(
            IntegrationConfiguration.organization_id == org_id,
            IntegrationConfiguration.integration_type == "erp",
        )
        .order_by(IntegrationConfiguration.created_at.desc())
    )
    return [_integration_response(integration) for integration in result.scalars().all()]


@router.get("/{integration_id}", response_model=ERPIntegrationResponse)
@rate_limit("100/minute")
async def get_integration(
    request: Request,
    integration_id: UUID,
    org_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    integration = await _get_erp_integration(db, integration_id, org_id)
    return _integration_response(integration)


@router.put("/{integration_id}", response_model=ERPIntegrationResponse)
@rate_limit("30/minute")
@require_admin()
async def update_integration(
    request: Request,
    integration_id: UUID,
    payload: ERPIntegrationUpdate,
    current_user: User = Depends(get_current_active_user),
    org_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    integration = await _get_erp_integration(db, integration_id, org_id)

    if payload.integration_name is not None:
        integration.integration_name = payload.integration_name
    if payload.erp_version is not None:
        integration.erp_version = payload.erp_version
    if payload.sync_schedule is not None:
        integration.sync_schedule = payload.sync_schedule
    if payload.sync_frequency_minutes is not None:
        integration.sync_frequency_minutes = payload.sync_frequency_minutes
    if payload.is_active is not None:
        integration.is_active = payload.is_active

    config = dict(integration.configuration or {})
    for key in (
        "auth_config",
        "rate_limit",
        "timeout",
        "health_check_path",
        "entity_path_template",
        "headers",
    ):
        value = getattr(payload, key)
        if value is not None:
            config[key] = value
    integration.configuration = config
    if payload.auth_config is not None:
        integration.authentication = payload.auth_config
    integration.updated_at = datetime.utcnow()

    await db.commit()
    await db.refresh(integration)
    return _integration_response(integration)


@router.delete("/{integration_id}", status_code=status.HTTP_204_NO_CONTENT)
@rate_limit("20/minute")
@require_admin()
async def delete_integration(
    request: Request,
    integration_id: UUID,
    current_user: User = Depends(get_current_active_user),
    org_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    integration = await _get_erp_integration(db, integration_id, org_id)
    await db.delete(integration)
    await db.commit()


@router.post("/{integration_id}/test")
@rate_limit("20/minute")
@require_admin()
async def test_connection(
    request: Request,
    integration_id: UUID,
    current_user: User = Depends(get_current_active_user),
    org_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    integration = await _get_erp_integration(db, integration_id, org_id)
    connector = create_erp_connector(integration)
    if not connector.validate_config():
        raise HTTPException(status_code=400, detail="ERP integration configuration is invalid")

    result = await connector.health_check()
    integration.last_health_check = datetime.utcnow()
    integration.health_status = result.get("status", "unknown")
    await db.commit()

    return {
        "integration_id": integration_id,
        "status": integration.health_status,
        "checked_at": integration.last_health_check,
        "details": result,
    }


@router.post("/{integration_id}/sync", response_model=ERPSyncTriggerResponse)
@rate_limit("20/minute")
@require_admin()
async def trigger_sync(
    request: Request,
    integration_id: UUID,
    payload: ERPSyncRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_active_user),
    org_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    integration = await _get_erp_integration(db, integration_id, org_id)
    if not integration.is_active:
        raise HTTPException(status_code=400, detail="ERP integration is inactive")

    await _upsert_sync_status(
        db,
        org_id=org_id,
        integration_id=integration_id,
        entity_type=payload.entity_type,
        status="queued",
    )
    await db.commit()

    background_tasks.add_task(
        _run_sync_background,
        integration_id=str(integration_id),
        org_id=str(org_id),
        entity_type=payload.entity_type,
        filters=payload.filters,
        limit=payload.limit or settings.ERP_SYNC_DEFAULT_LIMIT,
    )

    return ERPSyncTriggerResponse(
        integration_id=integration_id,
        entity_type=payload.entity_type,
        status="queued",
        triggered_at=datetime.utcnow(),
    )


@router.get("/{integration_id}/sync-status", response_model=list[SyncStatusResponse])
@rate_limit("100/minute")
async def get_sync_status(
    request: Request,
    integration_id: UUID,
    org_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    await _get_erp_integration(db, integration_id, org_id)
    result = await db.execute(
        select(ERPSyncStatus)
        .where(
            ERPSyncStatus.integration_id == integration_id,
            ERPSyncStatus.organization_id == org_id,
        )
        .order_by(ERPSyncStatus.updated_at.desc())
    )
    return [
        SyncStatusResponse(
            id=status_row.id,
            entity_type=status_row.entity_type,
            last_sync_at=status_row.last_sync_at,
            last_sync_status=status_row.last_sync_status,
            records_synced=status_row.records_synced,
            records_failed=status_row.records_failed,
            sync_duration_seconds=float(status_row.sync_duration_seconds)
            if status_row.sync_duration_seconds is not None
            else None,
            next_sync_at=status_row.next_sync_at,
            updated_at=status_row.updated_at,
        )
        for status_row in result.scalars().all()
    ]


@router.post("/{integration_id}/mappings", response_model=FieldMappingResponse)
@rate_limit("30/minute")
@require_admin()
async def create_field_mapping(
    request: Request,
    integration_id: UUID,
    payload: FieldMappingCreate,
    current_user: User = Depends(get_current_active_user),
    org_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    await _get_erp_integration(db, integration_id, org_id)
    mapping = ERPDataMapping(
        organization_id=org_id,
        integration_id=integration_id,
        source_entity=payload.source_entity,
        source_field=payload.source_field,
        target_entity=payload.target_entity,
        target_field=payload.target_field,
        transformation_rule=payload.transformation_rule,
        data_type=payload.data_type,
        is_required=payload.is_required,
    )
    db.add(mapping)
    await db.commit()
    await db.refresh(mapping)
    return _mapping_response(mapping)


@router.get("/{integration_id}/mappings", response_model=list[FieldMappingResponse])
@rate_limit("100/minute")
async def list_field_mappings(
    request: Request,
    integration_id: UUID,
    org_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    await _get_erp_integration(db, integration_id, org_id)
    result = await db.execute(
        select(ERPDataMapping)
        .where(
            ERPDataMapping.integration_id == integration_id,
            ERPDataMapping.organization_id == org_id,
        )
        .order_by(ERPDataMapping.created_at.desc())
    )
    return [_mapping_response(mapping) for mapping in result.scalars().all()]


@router.put("/{integration_id}/mappings/{mapping_id}", response_model=FieldMappingResponse)
@rate_limit("30/minute")
@require_admin()
async def update_field_mapping(
    request: Request,
    integration_id: UUID,
    mapping_id: UUID,
    payload: FieldMappingUpdate,
    current_user: User = Depends(get_current_active_user),
    org_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    await _get_erp_integration(db, integration_id, org_id)
    result = await db.execute(
        select(ERPDataMapping).where(
            ERPDataMapping.id == mapping_id,
            ERPDataMapping.integration_id == integration_id,
            ERPDataMapping.organization_id == org_id,
        )
    )
    mapping = result.scalar_one_or_none()
    if not mapping:
        raise HTTPException(status_code=404, detail="ERP field mapping not found")

    for key in ("target_entity", "target_field", "transformation_rule", "data_type", "is_required"):
        value = getattr(payload, key)
        if value is not None:
            setattr(mapping, key, value)
    mapping.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(mapping)
    return _mapping_response(mapping)


@router.delete("/{integration_id}/mappings/{mapping_id}", status_code=status.HTTP_204_NO_CONTENT)
@rate_limit("20/minute")
@require_admin()
async def delete_field_mapping(
    request: Request,
    integration_id: UUID,
    mapping_id: UUID,
    current_user: User = Depends(get_current_active_user),
    org_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    await _get_erp_integration(db, integration_id, org_id)
    result = await db.execute(
        select(ERPDataMapping).where(
            ERPDataMapping.id == mapping_id,
            ERPDataMapping.integration_id == integration_id,
            ERPDataMapping.organization_id == org_id,
        )
    )
    mapping = result.scalar_one_or_none()
    if not mapping:
        raise HTTPException(status_code=404, detail="ERP field mapping not found")
    await db.delete(mapping)
    await db.commit()


def _mapping_response(mapping: ERPDataMapping) -> FieldMappingResponse:
    return FieldMappingResponse(
        id=mapping.id,
        source_entity=mapping.source_entity,
        source_field=mapping.source_field,
        target_entity=mapping.target_entity,
        target_field=mapping.target_field,
        transformation_rule=mapping.transformation_rule,
        data_type=mapping.data_type,
        is_required=mapping.is_required,
        created_at=mapping.created_at,
        updated_at=mapping.updated_at,
    )


async def _upsert_sync_status(
    db: AsyncSession,
    *,
    org_id: UUID,
    integration_id: UUID,
    entity_type: str,
    status: str,
    records_synced: int = 0,
    records_failed: int = 0,
    duration_seconds: float | None = None,
) -> ERPSyncStatus:
    result = await db.execute(
        select(ERPSyncStatus).where(
            ERPSyncStatus.organization_id == org_id,
            ERPSyncStatus.integration_id == integration_id,
            ERPSyncStatus.entity_type == entity_type,
        )
    )
    sync_status = result.scalar_one_or_none()
    if not sync_status:
        sync_status = ERPSyncStatus(
            organization_id=org_id,
            integration_id=integration_id,
            entity_type=entity_type,
        )
        db.add(sync_status)

    sync_status.last_sync_status = status
    sync_status.last_sync_at = datetime.utcnow()
    sync_status.records_synced = records_synced
    sync_status.records_failed = records_failed
    sync_status.sync_duration_seconds = duration_seconds
    sync_status.updated_at = datetime.utcnow()
    return sync_status


async def _run_sync_background(
    *,
    integration_id: str,
    org_id: str,
    entity_type: str,
    filters: dict[str, Any],
    limit: int,
) -> None:
    started = datetime.utcnow()
    async with AsyncSessionLocal() as db:
        org_uuid = UUID(org_id)
        integration_uuid = UUID(integration_id)
        try:
            await db.execute(
                text("SELECT set_config('app.current_org_id', :org_id, true)"),
                {"org_id": str(org_uuid)},
            )
            integration = await _get_erp_integration(db, integration_uuid, org_uuid)
            await _upsert_sync_status(
                db,
                org_id=org_uuid,
                integration_id=integration_uuid,
                entity_type=entity_type,
                status="running",
            )
            await db.commit()

            connector = create_erp_connector(integration)
            records = await connector.fetch_data(entity_type, filters=filters, limit=limit)
            await db.execute(
                text("SELECT set_config('app.current_org_id', :org_id, true)"),
                {"org_id": str(org_uuid)},
            )

            for index, record in enumerate(records):
                entity_id = str(
                    record.get("id")
                    or record.get("ID")
                    or record.get("entity_id")
                    or record.get("number")
                    or index
                )
                stmt = pg_insert(ERPEntity.__table__).values(
                    organization_id=org_uuid,
                    integration_id=integration_uuid,
                    entity_type=entity_type,
                    entity_id=entity_id,
                    entity_data=record,
                    source_system=integration.erp_type or "generic",
                    is_active=True,
                    updated_at=datetime.utcnow(),
                )
                await db.execute(
                    stmt.on_conflict_do_update(
                        constraint="uq_erp_entities",
                        set_={
                            "entity_data": record,
                            "source_system": integration.erp_type or "generic",
                            "is_active": True,
                            "valid_to": None,
                            "updated_at": datetime.utcnow(),
                        },
                    )
                )

            duration = (datetime.utcnow() - started).total_seconds()
            await _upsert_sync_status(
                db,
                org_id=org_uuid,
                integration_id=integration_uuid,
                entity_type=entity_type,
                status="success",
                records_synced=len(records),
                records_failed=0,
                duration_seconds=duration,
            )
            integration.last_successful_sync = datetime.utcnow()
            await db.commit()
        except Exception as exc:
            duration = (datetime.utcnow() - started).total_seconds()
            await db.rollback()
            await db.execute(
                text("SELECT set_config('app.current_org_id', :org_id, true)"),
                {"org_id": org_id},
            )
            await _upsert_sync_status(
                db,
                org_id=UUID(org_id),
                integration_id=UUID(integration_id),
                entity_type=entity_type,
                status="failed",
                records_synced=0,
                records_failed=1,
                duration_seconds=duration,
            )
            await db.commit()
            handler = ERPErrorHandler(org_id, integration_id)
            logger.error(
                "erp_sync_failed",
                integration_id=integration_id,
                organization_id=org_id,
                entity_type=entity_type,
                error=str(exc),
            )
            await handler._send_alert(1)
        finally:
            if db.in_transaction():
                await db.rollback()

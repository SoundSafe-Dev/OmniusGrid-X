"""Model artifact OTA releases (Task 2).

Packages a registered model (from the Task 1 registry) as an ``agent_releases``
row with ``artifact_type='model'`` so it rides the SAME OTA machinery as config
bundles: the model's ``.pt`` bytes become the Ed25519-signed release bundle
(via ``agent_release_storage``), and a normal ``agent_rollouts`` rollout drives
delivery — the orchestrator dispatches ``model_update`` for these.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_active_user
from app.core.tenant import get_tenant_db, get_tenant_org_id
from app.db.models import AgentRelease, ModelRegistryEntry, User
from app.middleware.rate_limit import rate_limit
from app.middleware.rbac import require_admin
from app.services.agent_release_storage import (
    issue_release_bundle_url,
    store_config_bundle,
)
from app.services.model_registry_store import load_model_artifact

router = APIRouter()


class ModelReleaseCreate(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    model_id: UUID


class ModelReleaseResponse(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    id: UUID
    organization_id: UUID
    artifact_type: str
    model_name: str | None
    version: str
    channel: str
    checksum_sha256: str
    signature_ed25519: str
    status: str
    created_by: UUID | None
    created_at: datetime | None
    bundle_url: str | None = None


@router.post(
    "/model-releases",
    response_model=ModelReleaseResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_admin)],
)
@rate_limit("30/hour")
async def create_model_release(
    request: Request,
    payload: ModelReleaseCreate,
    current_user: User = Depends(get_current_active_user),
    org_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    entry = (
        await db.execute(
            select(ModelRegistryEntry).where(
                ModelRegistryEntry.id == payload.model_id,
                ModelRegistryEntry.organization_id == org_id,
            )
        )
    ).scalar_one_or_none()
    if entry is None:
        raise HTTPException(status_code=404, detail="Model not found")

    # One model release per (org, version) family — channel carries the family.
    existing = (
        await db.execute(
            select(AgentRelease.id).where(
                AgentRelease.organization_id == org_id,
                AgentRelease.artifact_type == "model",
                AgentRelease.version == entry.version,
                AgentRelease.channel == entry.name,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(
            status_code=409, detail="Model release already exists for this version"
        )

    # Reuse the OTA storage + Ed25519 signing: the .pt bytes are the release bundle.
    artifact = load_model_artifact(entry.artifact_storage_key)
    release_id = uuid.uuid4()
    stored = store_config_bundle(org_id, release_id, artifact)

    release = AgentRelease(
        id=release_id,
        organization_id=org_id,
        artifact_type="model",
        model_name=entry.name,
        artifact_format="pytorch",
        artifact_filename=f"{entry.name}-{entry.version}.pt",
        artifact_size_bytes=stored.size_bytes,
        version=entry.version,
        channel=entry.name,
        image_tag=None,
        bundle_storage_key=stored.storage_key,
        checksum_sha256=stored.checksum_sha256,
        signature_ed25519=stored.signature_ed25519,
        signing_key_id=stored.signing_key_id,
        status="draft",
        created_by=current_user.id,
    )
    db.add(release)
    await db.commit()

    bundle_url, _ = issue_release_bundle_url(release.id, org_id)
    return ModelReleaseResponse(
        id=release.id,
        organization_id=release.organization_id,
        artifact_type=release.artifact_type,
        model_name=release.model_name,
        version=release.version,
        channel=release.channel,
        checksum_sha256=release.checksum_sha256,
        signature_ed25519=release.signature_ed25519,
        status=release.status,
        created_by=release.created_by,
        created_at=release.created_at,
        bundle_url=bundle_url,
    )

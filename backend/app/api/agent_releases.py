"""Fleet OTA release registry API."""

from __future__ import annotations

import base64
import uuid
from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_active_user
from app.core.tenant import get_tenant_db, get_tenant_org_id
from app.db.database import AsyncSessionLocal
from app.db.models import AgentRelease, User
from app.middleware.rate_limit import rate_limit
from app.middleware.rbac import require_admin
from app.services.agent_release_storage import (
    absolute_bundle_path,
    issue_release_bundle_url,
    store_config_bundle,
)
from app.utils.signed_urls import (
    PURPOSE_AGENT_RELEASE,
    SignedTokenError,
    verify_signed_download_token,
)

router = APIRouter()
public_router = APIRouter()


class AgentReleaseCreate(BaseModel):
    version: str = Field(..., min_length=1, max_length=100)
    channel: str = Field(default="stable", min_length=1, max_length=50)
    image_tag: str = Field(..., min_length=1, max_length=255)
    config_bundle: str = Field(..., min_length=1)
    bundle_encoding: Literal["text", "base64"] = "text"
    release_notes: str | None = None


class AgentReleaseResponse(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    id: UUID
    organization_id: UUID
    version: str
    channel: str
    image_tag: str | None
    artifact_type: str = "config"
    model_name: str | None = None
    checksum_sha256: str
    signature_ed25519: str
    signing_key_id: str
    release_notes: str | None
    status: str
    created_by: UUID | None
    created_at: datetime | None
    updated_at: datetime | None
    bundle_url: str | None = None


def _decode_bundle(payload: AgentReleaseCreate) -> bytes:
    if payload.bundle_encoding == "base64":
        try:
            return base64.b64decode(payload.config_bundle, validate=True)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid base64 config bundle") from exc
    return payload.config_bundle.encode("utf-8")


def _release_response(
    release: AgentRelease,
    include_url: bool = False,
) -> AgentReleaseResponse:
    bundle_url = None
    if include_url:
        bundle_url, _ = issue_release_bundle_url(release.id, release.organization_id)
    return AgentReleaseResponse(
        id=release.id,
        organization_id=release.organization_id,
        version=release.version,
        channel=release.channel,
        image_tag=release.image_tag,
        artifact_type=release.artifact_type,
        model_name=release.model_name,
        checksum_sha256=release.checksum_sha256,
        signature_ed25519=release.signature_ed25519,
        signing_key_id=release.signing_key_id,
        release_notes=release.release_notes,
        status=release.status,
        created_by=release.created_by,
        created_at=release.created_at,
        updated_at=release.updated_at,
        bundle_url=bundle_url,
    )


async def _get_release(
    release_id: UUID,
    org_id: UUID,
    db: AsyncSession,
) -> AgentRelease:
    release = (
        await db.execute(
            select(AgentRelease).where(
                AgentRelease.id == release_id,
                AgentRelease.organization_id == org_id,
            )
        )
    ).scalar_one_or_none()
    if release is None:
        raise HTTPException(status_code=404, detail="Agent release not found")
    return release


@router.post(
    "/releases",
    response_model=AgentReleaseResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_admin)],
)
@rate_limit("30/hour")
async def create_release(
    request: Request,
    payload: AgentReleaseCreate,
    current_user: User = Depends(get_current_active_user),
    org_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    existing = (
        await db.execute(
            select(AgentRelease.id).where(
                AgentRelease.organization_id == org_id,
                AgentRelease.version == payload.version,
                AgentRelease.channel == payload.channel,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail="Release version already exists for this channel",
        )

    release_id = uuid.uuid4()
    stored = store_config_bundle(org_id, release_id, _decode_bundle(payload))
    release = AgentRelease(
        id=release_id,
        organization_id=org_id,
        version=payload.version,
        channel=payload.channel,
        image_tag=payload.image_tag,
        bundle_storage_key=stored.storage_key,
        checksum_sha256=stored.checksum_sha256,
        signature_ed25519=stored.signature_ed25519,
        signing_key_id=stored.signing_key_id,
        release_notes=payload.release_notes,
        status="draft",
        created_by=current_user.id,
    )
    db.add(release)
    try:
        await db.commit()
    except IntegrityError as exc:
        raise HTTPException(
            status_code=409,
            detail="Release version already exists for this channel",
        ) from exc
    await db.refresh(release)
    return _release_response(release, include_url=True)


@router.get("/releases", response_model=list[AgentReleaseResponse])
@rate_limit("100/minute")
async def list_releases(
    request: Request,
    status_filter: str | None = Query(None, alias="status"),
    org_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    query = select(AgentRelease).where(AgentRelease.organization_id == org_id)
    if status_filter:
        query = query.where(AgentRelease.status == status_filter)
    query = query.order_by(AgentRelease.created_at.desc())
    releases = (await db.execute(query)).scalars().all()
    return [_release_response(release) for release in releases]


@router.get("/releases/{release_id}", response_model=AgentReleaseResponse)
@rate_limit("100/minute")
async def get_release(
    request: Request,
    release_id: UUID,
    org_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    release = await _get_release(release_id, org_id, db)
    return _release_response(release, include_url=True)


@router.post("/releases/{release_id}/publish", response_model=AgentReleaseResponse, dependencies=[Depends(require_admin)])
@rate_limit("30/hour")
async def publish_release(
    request: Request,
    release_id: UUID,
    current_user: User = Depends(get_current_active_user),
    org_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    release = await _get_release(release_id, org_id, db)
    if release.status == "yanked":
        raise HTTPException(status_code=400, detail="Yanked releases cannot be published")
    release.status = "published"
    await db.commit()
    await db.refresh(release)
    return _release_response(release, include_url=True)


@router.post("/releases/{release_id}/yank", response_model=AgentReleaseResponse, dependencies=[Depends(require_admin)])
@rate_limit("30/hour")
async def yank_release(
    request: Request,
    release_id: UUID,
    current_user: User = Depends(get_current_active_user),
    org_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    release = await _get_release(release_id, org_id, db)
    release.status = "yanked"
    await db.commit()
    await db.refresh(release)
    return _release_response(release)


@public_router.get("/releases/{release_id}/bundle")
@rate_limit("30/minute")
async def download_release_bundle(request: Request, release_id: UUID, token: str):
    try:
        verified = verify_signed_download_token(
            token,
            PURPOSE_AGENT_RELEASE,
            release_id,
        )
    except SignedTokenError:
        raise HTTPException(status_code=403, detail="Invalid or expired download link")

    async with AsyncSessionLocal() as db:
        await db.execute(
            text("SELECT set_config('app.current_org_id', :org_id, true)"),
            {"org_id": str(verified.organization_id)},
        )
        release = (
            await db.execute(
                select(AgentRelease).where(
                    AgentRelease.id == release_id,
                    AgentRelease.organization_id == verified.organization_id,
                )
            )
        ).scalar_one_or_none()
        if release is None:
            raise HTTPException(status_code=404, detail="Agent release not found")
        path = absolute_bundle_path(release.bundle_storage_key)
        if not path.exists():
            raise HTTPException(status_code=410, detail="Release bundle is unavailable")
        response = FileResponse(
            path,
            media_type="application/octet-stream",
            filename=f"{release.version}.bundle",
        )
        response.headers["Cache-Control"] = "private, no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Checksum-SHA256"] = release.checksum_sha256
        response.headers["X-Signature-Ed25519"] = release.signature_ed25519
        return response

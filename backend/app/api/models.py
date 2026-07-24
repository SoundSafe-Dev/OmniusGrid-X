"""Cloud model registry API (MLOps producer side).

Mirrors the fleet release registry (``api/agent_releases.py``): tenant-scoped
reads, admin-dependent mutations, and a public signed-URL artifact download.
``GET /models/{name}/latest`` returns the exact ``{version, download_url,
sha256_hash}`` shape the edge MLOps client (``services/mlops_pipeline.py``)
polls.
"""


from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_active_user
from app.core.tenant import get_tenant_db, get_tenant_org_id
from app.db.database import AsyncSessionLocal
from app.db.models import ModelRegistryEntry, ModelTrainingRun, User
from app.middleware.rate_limit import rate_limit
from app.middleware.rbac import require_admin
from app.services.model_registry_store import (
    absolute_artifact_path,
    issue_model_artifact_url,
)
from app.services.model_training_pipeline import TRAINABLE_MODELS, train_and_register
from app.utils.signed_urls import (
    PURPOSE_MODEL_ARTIFACT,
    SignedTokenError,
    verify_signed_download_token,
)

router = APIRouter()
public_router = APIRouter()


class ModelResponse(BaseModel):
    id: UUID
    organization_id: UUID
    name: str
    version: str
    framework: str
    checksum_sha256: str
    status: str
    metrics: dict[str, Any]
    feature_contract: dict[str, Any]
    training_run_id: UUID | None
    created_by: UUID | None
    created_at: datetime | None
    updated_at: datetime | None


class LatestModelResponse(BaseModel):
    """The exact contract mlops_pipeline.check_for_updates consumes."""

    version: str
    download_url: str
    sha256_hash: str


class TrainingRunResponse(BaseModel):
    id: UUID
    model_name: str
    status: str
    sample_count: int | None
    metrics: dict[str, Any]
    error: str | None
    produced_model_id: UUID | None
    created_at: datetime | None
    completed_at: datetime | None


class TrainRequest(BaseModel):
    bucket_seconds: int = Field(default=3600, ge=60, le=86400)
    window_days: int = Field(default=7, ge=1, le=90)
    seed: int = 0


def _model_response(entry: ModelRegistryEntry) -> ModelResponse:
    return ModelResponse(
        id=entry.id,
        organization_id=entry.organization_id,
        name=entry.name,
        version=entry.version,
        framework=entry.framework,
        checksum_sha256=entry.checksum_sha256,
        status=entry.status,
        metrics=entry.metrics or {},
        feature_contract=entry.feature_contract or {},
        training_run_id=entry.training_run_id,
        created_by=entry.created_by,
        created_at=entry.created_at,
        updated_at=entry.updated_at,
    )


def _run_response(run: ModelTrainingRun) -> TrainingRunResponse:
    return TrainingRunResponse(
        id=run.id,
        model_name=run.model_name,
        status=run.status,
        sample_count=run.sample_count,
        metrics=run.metrics or {},
        error=run.error,
        produced_model_id=run.produced_model_id,
        created_at=run.created_at,
        completed_at=run.completed_at,
    )


async def _get_model(model_id: UUID, org_id: UUID, db: AsyncSession) -> ModelRegistryEntry:
    entry = (
        await db.execute(
            select(ModelRegistryEntry).where(
                ModelRegistryEntry.id == model_id,
                ModelRegistryEntry.organization_id == org_id,
            )
        )
    ).scalar_one_or_none()
    if entry is None:
        raise HTTPException(status_code=404, detail="Model not found")
    return entry


@router.get("/models", response_model=list[ModelResponse])
@rate_limit("100/minute")
async def list_models(
    request: Request,
    name: str | None = Query(None),
    status_filter: str | None = Query(None, alias="status"),
    org_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    query = select(ModelRegistryEntry).where(ModelRegistryEntry.organization_id == org_id)
    if name:
        query = query.where(ModelRegistryEntry.name == name)
    if status_filter:
        query = query.where(ModelRegistryEntry.status == status_filter)
    query = query.order_by(ModelRegistryEntry.created_at.desc())
    entries = (await db.execute(query)).scalars().all()
    return [_model_response(e) for e in entries]


@router.get("/models/{name}/latest", response_model=LatestModelResponse)
@rate_limit("100/minute")
async def get_latest_model(
    request: Request,
    name: str,
    org_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    entry = (
        await db.execute(
            select(ModelRegistryEntry)
            .where(
                ModelRegistryEntry.organization_id == org_id,
                ModelRegistryEntry.name == name,
                ModelRegistryEntry.status == "published",
            )
            .order_by(ModelRegistryEntry.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if entry is None:
        raise HTTPException(status_code=404, detail="No published model for this name")
    download_url, _ = issue_model_artifact_url(entry.id, org_id)
    return LatestModelResponse(
        version=entry.version,
        download_url=download_url,
        sha256_hash=entry.checksum_sha256,
    )


@router.get("/models/{model_id}", response_model=ModelResponse)
@rate_limit("100/minute")
async def get_model(
    request: Request,
    model_id: UUID,
    org_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    return _model_response(await _get_model(model_id, org_id, db))


@router.post(
    "/models/{name}/train",
    response_model=TrainingRunResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_admin)],
)
@rate_limit("10/hour")
async def train_model(
    request: Request,
    name: str,
    payload: TrainRequest,
    current_user: User = Depends(get_current_active_user),
    org_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    if name not in TRAINABLE_MODELS:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown model '{name}'; trainable: {list(TRAINABLE_MODELS)}",
        )
    from datetime import timedelta, timezone

    window_end = datetime.now(timezone.utc)
    window_start = window_end - timedelta(days=payload.window_days)
    run = await train_and_register(
        db,
        org_id,
        name,
        created_by=current_user.id,
        window_start=window_start,
        window_end=window_end,
        bucket_seconds=payload.bucket_seconds,
        seed=payload.seed,
    )
    await db.commit()
    if run.status == "failed":
        raise HTTPException(status_code=422, detail=run.error or "Training failed")
    return _run_response(run)


@router.post("/models/{model_id}/publish", response_model=ModelResponse, dependencies=[Depends(require_admin)])
@rate_limit("30/hour")
async def publish_model(
    request: Request,
    model_id: UUID,
    current_user: User = Depends(get_current_active_user),
    org_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    entry = await _get_model(model_id, org_id, db)
    if entry.status == "yanked":
        raise HTTPException(status_code=400, detail="Yanked models cannot be published")
    entry.status = "published"
    await db.commit()
    return _model_response(entry)


@router.post("/models/{model_id}/yank", response_model=ModelResponse, dependencies=[Depends(require_admin)])
@rate_limit("30/hour")
async def yank_model(
    request: Request,
    model_id: UUID,
    current_user: User = Depends(get_current_active_user),
    org_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    entry = await _get_model(model_id, org_id, db)
    entry.status = "yanked"
    await db.commit()
    return _model_response(entry)


@public_router.get("/models/{model_id}/download")
@rate_limit("60/minute")
async def download_model_artifact(request: Request, model_id: UUID, token: str):
    try:
        verified = verify_signed_download_token(token, PURPOSE_MODEL_ARTIFACT, model_id)
    except SignedTokenError:
        raise HTTPException(status_code=403, detail="Invalid or expired download link")

    async with AsyncSessionLocal() as db:
        await db.execute(
            text("SELECT set_config('app.current_org_id', :org_id, true)"),
            {"org_id": str(verified.organization_id)},
        )
        entry = (
            await db.execute(
                select(ModelRegistryEntry).where(
                    ModelRegistryEntry.id == model_id,
                    ModelRegistryEntry.organization_id == verified.organization_id,
                )
            )
        ).scalar_one_or_none()
        if entry is None:
            raise HTTPException(status_code=404, detail="Model not found")
        path = absolute_artifact_path(entry.artifact_storage_key)
        if not path.exists():
            raise HTTPException(status_code=410, detail="Model artifact is unavailable")
        response = FileResponse(
            path,
            media_type="application/octet-stream",
            filename=f"{entry.name}_{entry.version}.pt",
        )
        response.headers["Cache-Control"] = "private, no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Checksum-SHA256"] = entry.checksum_sha256
        return response

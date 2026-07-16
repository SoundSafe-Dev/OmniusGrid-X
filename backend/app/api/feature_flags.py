"""Feature flag API routes (Task 1).

Admin-protected CRUD for managing flags plus an authenticated evaluation
endpoint that the frontend useFeatureFlags hook consumes. Admin protection uses
the dependency approach (get_current_active_user + role check) per the Task 1
decision.
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.api.auth import get_current_active_user
from app.db.models import User
from app.middleware.rbac import require_admin
from app.services.feature_flags import (
    FeatureFlagError,
    FeatureFlagNotFound,
    feature_flag_service,
)

router = APIRouter()


class FeatureFlagCreate(BaseModel):
    key: str = Field(..., min_length=1, description="Unique flag identifier, e.g. 'new-dashboard'")
    description: str = ""
    enabled: bool = False
    rollout_percentage: int = Field(0, ge=0, le=100)


class FeatureFlagUpdate(BaseModel):
    description: Optional[str] = None
    enabled: Optional[bool] = None
    rollout_percentage: Optional[int] = Field(None, ge=0, le=100)


def _actor_org(user: User) -> Optional[str]:
    org_id = getattr(user, "organization_id", None)
    return str(org_id) if org_id else None


@router.get("/", summary="List all feature flags")
async def list_feature_flags(_: User = Depends(require_admin)):
    try:
        flags = await feature_flag_service.list_flags()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Feature flag store unavailable: {exc}")
    return {"flags": flags, "count": len(flags)}


@router.get("/evaluate", summary="Evaluate all flags for the current user")
async def evaluate_feature_flags(current_user: User = Depends(get_current_active_user)):
    """Resolve every flag for the caller's organization (bucketed on organization_id)."""
    org_id = _actor_org(current_user)
    if not org_id:
        return {"flags": {}}
    flags = await feature_flag_service.evaluate_all(identity=org_id)
    return {"flags": flags}


@router.get("/{key}", summary="Get a single feature flag")
async def get_feature_flag(key: str, _: User = Depends(require_admin)):
    flag = await feature_flag_service.get_flag(key)
    if flag is None:
        raise HTTPException(status_code=404, detail=f"Feature flag '{key}' not found")
    return flag


@router.post("/", status_code=status.HTTP_201_CREATED, summary="Create a feature flag")
async def create_feature_flag(
    payload: FeatureFlagCreate,
    current_user: User = Depends(require_admin),
):
    try:
        return await feature_flag_service.create_flag(
            key=payload.key,
            description=payload.description,
            enabled=payload.enabled,
            rollout_percentage=payload.rollout_percentage,
            actor_id=str(current_user.id),
            organization_id=_actor_org(current_user),
        )
    except FeatureFlagError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.put("/{key}", summary="Update a feature flag")
async def update_feature_flag(
    key: str,
    payload: FeatureFlagUpdate,
    current_user: User = Depends(require_admin),
):
    try:
        return await feature_flag_service.update_flag(
            key=key,
            description=payload.description,
            enabled=payload.enabled,
            rollout_percentage=payload.rollout_percentage,
            actor_id=str(current_user.id),
            organization_id=_actor_org(current_user),
        )
    except FeatureFlagNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except FeatureFlagError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.delete("/{key}", summary="Delete a feature flag")
async def delete_feature_flag(key: str, current_user: User = Depends(require_admin)):
    try:
        await feature_flag_service.delete_flag(
            key=key,
            actor_id=str(current_user.id),
            organization_id=_actor_org(current_user),
        )
    except FeatureFlagNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"deleted": key}

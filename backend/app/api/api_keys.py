"""API Key Management for External Integrations"""

import secrets
import hashlib
from datetime import datetime, timedelta, timezone
from typing import Optional, List
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status, Header, Request
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.db.models import User, APIKey
from app.api.auth import get_current_active_user
from app.middleware.rate_limit import rate_limit
from app.middleware.rbac import require_admin
from pydantic import BaseModel
import structlog

logger = structlog.get_logger()

router = APIRouter()


class GeneratedAPIKey(BaseModel):
    """`POST /generate`.

    `key` IS THE SECRET, and it is here because this is the only response that carries it —
    only the hash is stored, so a model that dropped this field would make the endpoint
    incapable of doing its job while still answering 200. `warning` is sent for the same
    reason and is part of the contract, not decoration.
    """

    id: str
    key: str
    key_prefix: str
    name: str
    scopes: List[str]
    expires_at: Optional[str] = None
    warning: str


class APIKeyListItem(BaseModel):
    """The stored key, minus the secret — `key_hash` and `key_prefix` are all that survive
    generation, and only the prefix is safe to show."""

    id: str
    key_prefix: Optional[str] = None
    name: Optional[str] = None
    #: `api_keys.scopes` is a JSON column; a row written before scopes existed holds NULL.
    scopes: Optional[List[str]] = None
    expires_at: Optional[str] = None
    last_used_at: Optional[str] = None
    created_at: Optional[str] = None


class APIKeyList(BaseModel):
    items: List[APIKeyListItem]
    total: int


class APIKeyRevoked(BaseModel):
    message: str


def generate_api_key() -> str:
    """Generate a secure API key"""
    return secrets.token_urlsafe(32)


def hash_api_key(api_key: str) -> str:
    """Hash API key for storage"""
    return hashlib.sha256(api_key.encode()).hexdigest()


def get_key_prefix(api_key: str) -> str:
    """Get first 8 characters for identification"""
    return api_key[:8]


async def verify_api_key(
    api_key: Optional[str] = Header(None, alias="X-API-Key"),
    db: AsyncSession = Depends(get_db)
) -> Optional[APIKey]:
    """Verify API key and return key info"""
    if not api_key:
        return None
    
    key_hash = hash_api_key(api_key)
    
    result = await db.execute(
        select(APIKey).where(
            and_(
                APIKey.key_hash == key_hash,
                APIKey.is_active == True
            )
        )
    )
    api_key_obj = result.scalar_one_or_none()
    
    if api_key_obj:
        # Check expiration
        if api_key_obj.expires_at and api_key_obj.expires_at < datetime.now(timezone.utc):
            return None
        
        # Update last used
        api_key_obj.last_used_at = datetime.now(timezone.utc)
        await db.commit()
    
    return api_key_obj


@router.post("/generate", response_model=GeneratedAPIKey, summary="Generate API key", description="Generate a new API key for external integrations. Returns the full key (only shown once).", dependencies=[Depends(require_admin)])
@rate_limit("10/hour")
async def generate_api_key_endpoint(
    request: Request,
    name: str,
    scopes: List[str] = ["read"],
    expires_in_days: Optional[int] = None,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """Generate a new API key"""
    # Validate scopes
    valid_scopes = ["read", "write", "admin"]
    for scope in scopes:
        if scope not in valid_scopes:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid scope: {scope}. Valid scopes: {valid_scopes}"
            )
    if "admin" in scopes and current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin scope requires admin role"
        )
    
    # Generate API key
    api_key = generate_api_key()
    key_hash = hash_api_key(api_key)
    key_prefix = get_key_prefix(api_key)
    
    # Calculate expiration
    expires_at = None
    if expires_in_days:
        expires_at = datetime.now(timezone.utc) + timedelta(days=expires_in_days)
    
    # Create API key record
    api_key_obj = APIKey(
        key_hash=key_hash,
        key_prefix=key_prefix,
        name=name,
        organization_id=current_user.organization_id,
        scopes=scopes,
        expires_at=expires_at,
        created_by=current_user.id
    )
    
    db.add(api_key_obj)
    await db.commit()
    await db.refresh(api_key_obj)
    
    logger.info(
        "api_key_generated",
        key_id=str(api_key_obj.id),
        key_prefix=key_prefix,
        user_id=str(current_user.id),
        organization_id=str(current_user.organization_id)
    )
    
    return {
        "id": str(api_key_obj.id),
        "key": api_key,  # Only shown once
        "key_prefix": key_prefix,
        "name": name,
        "scopes": scopes,
        "expires_at": expires_at.isoformat() if expires_at else None,
        "warning": "Store this key securely. It will not be shown again."
    }


@router.get("/", response_model=APIKeyList, summary="List API keys", description="List all API keys for the current organization.")
@rate_limit("100/minute")
async def list_api_keys(
    request: Request,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """List API keys"""
    if not current_user.organization_id:
        return {"items": [], "total": 0}
    
    result = await db.execute(
        select(APIKey).where(
            and_(
                APIKey.organization_id == current_user.organization_id,
                APIKey.is_active == True
            )
        )
    )
    api_keys = result.scalars().all()
    
    key_list = [
        {
            "id": str(key.id),
            "key_prefix": key.key_prefix,
            "name": key.name,
            "scopes": key.scopes,
            "expires_at": key.expires_at.isoformat() if key.expires_at else None,
            "last_used_at": key.last_used_at.isoformat() if key.last_used_at else None,
            "created_at": key.created_at.isoformat() if key.created_at else None
        }
        for key in api_keys
    ]
    
    return {"items": key_list, "total": len(key_list)}


@router.delete("/{key_id}", response_model=APIKeyRevoked, summary="Revoke API key", description="Revoke an API key by ID.", dependencies=[Depends(require_admin)])
@rate_limit("10/minute")
async def revoke_api_key(
    request: Request,
    key_id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """Revoke API key"""
    result = await db.execute(
        select(APIKey).where(
            and_(
                APIKey.id == key_id,
                APIKey.organization_id == current_user.organization_id
            )
        )
    )
    api_key_obj = result.scalar_one_or_none()
    
    if not api_key_obj:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="API key not found"
        )
    
    api_key_obj.is_active = False
    api_key_obj.revoked_at = datetime.now(timezone.utc)
    api_key_obj.revoked_by = current_user.id
    
    await db.commit()
    
    logger.info(
        "api_key_revoked",
        key_id=key_id,
        revoked_by=str(current_user.id)
    )
    
    return {"message": "API key revoked successfully"}

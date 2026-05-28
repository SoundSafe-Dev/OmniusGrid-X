"""Keycloak Authentication API Routes"""

from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr

try:
    from app.services.keycloak_service import keycloak_service
except ImportError:
    keycloak_service = None
from app.core.config import settings

router = APIRouter()


class KeycloakLoginRequest(BaseModel):
    username: str
    password: str


class KeycloakTokenRefreshRequest(BaseModel):
    refresh_token: str


class KeycloakLogoutRequest(BaseModel):
    refresh_token: str


class KeycloakUserCreate(BaseModel):
    username: str
    email: EmailStr
    first_name: str
    last_name: str
    password: str
    organization_id: str
    roles: Optional[list[str]] = None


class KeycloakUserUpdate(BaseModel):
    email: Optional[EmailStr] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    enabled: Optional[bool] = None


class KeycloakMFARequest(BaseModel):
    user_id: str
    enable: bool


@router.post("/login")
async def keycloak_login(request: KeycloakLoginRequest):
    """
    Authenticate user via Keycloak and return JWT token.
    
    This endpoint authenticates with Keycloak and returns the JWT token
    that can be used for subsequent API calls.
    """
    if not settings.KEYCLOAK_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Keycloak authentication is not enabled"
        )
    
    try:
        token_info = await keycloak_service.get_token(
            username=request.username,
            password=request.password
        )
        
        return {
            "access_token": token_info.get("access_token"),
            "refresh_token": token_info.get("refresh_token"),
            "expires_in": token_info.get("expires_in"),
            "refresh_expires_in": token_info.get("refresh_expires_in"),
            "token_type": "Bearer"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Authentication failed: {str(e)}"
        )


@router.post("/refresh")
async def keycloak_refresh_token(request: KeycloakTokenRefreshRequest):
    """
    Refresh access token using refresh token.
    """
    if not settings.KEYCLOAK_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Keycloak authentication is not enabled"
        )
    
    try:
        token_info = await keycloak_service.refresh_token(
            refresh_token=request.refresh_token
        )
        
        return {
            "access_token": token_info.get("access_token"),
            "refresh_token": token_info.get("refresh_token"),
            "expires_in": token_info.get("expires_in"),
            "token_type": "Bearer"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Token refresh failed: {str(e)}"
        )


@router.post("/logout")
async def keycloak_logout(request: KeycloakLogoutRequest):
    """
    Logout user by invalidating refresh token.
    """
    if not settings.KEYCLOAK_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Keycloak authentication is not enabled"
        )
    
    try:
        await keycloak_service.logout(refresh_token=request.refresh_token)
        return {"message": "Logged out successfully"}
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Logout failed: {str(e)}"
        )


@router.get("/userinfo")
async def keycloak_userinfo(access_token: str):
    """
    Get user information from Keycloak using access token.
    """
    if not settings.KEYCLOAK_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Keycloak authentication is not enabled"
        )
    
    try:
        user_info = await keycloak_service.get_user_info(access_token=access_token)
        return user_info
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve user information: {str(e)}"
        )


@router.post("/users")
async def keycloak_create_user(request: KeycloakUserCreate):
    """
    Create a new user in Keycloak (JIT provisioning).
    
    This endpoint is typically called by the application when a new user
    is created, to provision the user in Keycloak.
    """
    if not settings.KEYCLOAK_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Keycloak authentication is not enabled"
        )
    
    try:
        user_id = await keycloak_service.create_user(
            username=request.username,
            email=request.email,
            first_name=request.first_name,
            last_name=request.last_name,
            password=request.password,
            organization_id=request.organization_id,
            roles=request.roles
        )
        
        return {
            "user_id": user_id,
            "message": "User created successfully in Keycloak"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create user: {str(e)}"
        )


@router.put("/users/{user_id}")
async def keycloak_update_user(user_id: str, request: KeycloakUserUpdate):
    """
    Update user information in Keycloak.
    """
    if not settings.KEYCLOAK_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Keycloak authentication is not enabled"
        )
    
    try:
        await keycloak_service.update_user(
            user_id=user_id,
            email=request.email,
            first_name=request.first_name,
            last_name=request.last_name,
            enabled=request.enabled
        )
        
        return {"message": "User updated successfully"}
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update user: {str(e)}"
        )


@router.delete("/users/{user_id}")
async def keycloak_delete_user(user_id: str):
    """
    Delete user from Keycloak.
    """
    if not settings.KEYCLOAK_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Keycloak authentication is not enabled"
        )
    
    try:
        await keycloak_service.delete_user(user_id=user_id)
        return {"message": "User deleted successfully"}
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete user: {str(e)}"
        )


@router.get("/users/{user_id}/roles")
async def keycloak_get_user_roles(user_id: str):
    """
    Get roles assigned to a user.
    """
    if not settings.KEYCLOAK_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Keycloak authentication is not enabled"
        )
    
    try:
        roles = await keycloak_service.get_user_roles(user_id=user_id)
        return {"user_id": user_id, "roles": roles}
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve user roles: {str(e)}"
        )


@router.post("/users/{user_id}/roles")
async def keycloak_assign_roles(user_id: str, roles: list[str]):
    """
    Assign roles to a user.
    """
    if not settings.KEYCLOAK_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Keycloak authentication is not enabled"
        )
    
    try:
        await keycloak_service.assign_roles(user_id=user_id, roles=roles)
        return {"message": "Roles assigned successfully"}
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to assign roles: {str(e)}"
        )


@router.post("/users/{user_id}/mfa")
async def keycloak_manage_mfa(request: KeycloakMFARequest):
    """
    Enable or disable MFA for a user.
    """
    if not settings.KEYCLOAK_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Keycloak authentication is not enabled"
        )
    
    try:
        if request.enable:
            await keycloak_service.enable_mfa(user_id=request.user_id)
            return {"message": "MFA enabled successfully"}
        else:
            await keycloak_service.disable_mfa(user_id=request.user_id)
            return {"message": "MFA disabled successfully"}
            
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to manage MFA: {str(e)}"
        )


@router.get("/organizations/{organization_id}/users")
async def keycloak_get_org_users(organization_id: str):
    """
    Get all users belonging to an organization.
    """
    if not settings.KEYCLOAK_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Keycloak authentication is not enabled"
        )
    
    try:
        users = await keycloak_service.get_users_by_organization(
            organization_id=organization_id
        )
        return {
            "organization_id": organization_id,
            "users": users,
            "count": len(users)
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve organization users: {str(e)}"
        )


@router.post("/sync/{keycloak_user_id}")
async def keycloak_sync_user(keycloak_user_id: str):
    """
    Sync user from Keycloak to local database (SCIM-like).
    
    This endpoint retrieves user data from Keycloak and returns it
    for synchronization with the local database.
    """
    if not settings.KEYCLOAK_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Keycloak authentication is not enabled"
        )
    
    try:
        user_data = await keycloak_service.sync_user_from_keycloak(
            keycloak_user_id=keycloak_user_id
        )
        return user_data
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to sync user: {str(e)}"
        )

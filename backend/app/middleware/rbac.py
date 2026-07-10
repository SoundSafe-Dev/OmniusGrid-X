"""RBAC Enforcement Middleware"""

from functools import wraps
from typing import Callable, List, Optional
from fastapi import HTTPException, status, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.db.models import User, Permission, RolePermission
from app.api.auth import get_current_active_user
import structlog

logger = structlog.get_logger()


class RBACMiddleware:
    """Role-Based Access Control middleware"""
    
    @staticmethod
    async def get_user_permissions(user_id: str, db: AsyncSession) -> List[str]:
        """Get all permissions for a user based on their role"""
        # Get user's role
        result = await db.execute(
            select(User).where(User.id == user_id)
        )
        user = result.scalar_one_or_none()
        
        if not user:
            return []
        
        # Get permissions for the user's role
        result = await db.execute(
            select(Permission.name).join(
                RolePermission,
                Permission.id == RolePermission.permission_id
            ).where(RolePermission.role == user.role)
        )
        permissions = result.scalars().all()
        
        return list(permissions)
    
    @staticmethod
    async def check_permission(
        user: User,
        required_permission: str,
        db: AsyncSession
    ) -> bool:
        """Check if user has a specific permission"""
        user_permissions = await RBACMiddleware.get_user_permissions(str(user.id), db)
        return required_permission in user_permissions
    
    @staticmethod
    async def check_any_permission(
        user: User,
        required_permissions: List[str],
        db: AsyncSession
    ) -> bool:
        """Check if user has any of the required permissions"""
        user_permissions = await RBACMiddleware.get_user_permissions(str(user.id), db)
        return any(perm in user_permissions for perm in required_permissions)
    
    @staticmethod
    async def check_all_permissions(
        user: User,
        required_permissions: List[str],
        db: AsyncSession
    ) -> bool:
        """Check if user has all of the required permissions"""
        user_permissions = await RBACMiddleware.get_user_permissions(str(user.id), db)
        return all(perm in user_permissions for perm in required_permissions)


def require_permission(permission: str):
    """Decorator to require a specific permission"""
    def decorator(func: Callable):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # Get user from kwargs or inject it
            user = kwargs.get('current_user')
            if not user:
                # Try to get it from the first positional argument (self for class methods)
                if args and hasattr(args[0], 'current_user'):
                    user = args[0].current_user
                else:
                    raise HTTPException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        detail="Authentication required"
                    )
            
            # Get database session
            db = kwargs.get('db')
            if not db:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Database session not available"
                )
            
            # Check permission
            has_permission = await RBACMiddleware.check_permission(user, permission, db)
            
            if not has_permission:
                logger.warning(
                    "permission_denied",
                    user_id=str(user.id),
                    user_role=user.role,
                    required_permission=permission
                )
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Permission '{permission}' required"
                )
            
            return await func(*args, **kwargs)
        return wrapper
    return decorator


def require_any_permission(*permissions: str):
    """Decorator to require any of the specified permissions"""
    def decorator(func: Callable):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            user = kwargs.get('current_user')
            if not user:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Authentication required"
                )
            
            db = kwargs.get('db')
            if not db:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Database session not available"
                )
            
            has_permission = await RBACMiddleware.check_any_permission(
                user, list(permissions), db
            )
            
            if not has_permission:
                logger.warning(
                    "permission_denied",
                    user_id=str(user.id),
                    user_role=user.role,
                    required_permissions=list(permissions)
                )
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"One of permissions {list(permissions)} required"
                )
            
            return await func(*args, **kwargs)
        return wrapper
    return decorator


def require_admin():
    """Decorator to require admin role"""
    def decorator(func: Callable):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            user = kwargs.get('current_user')
            if not user:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Authentication required"
                )
            
            if user.role != 'admin':
                logger.warning(
                    "admin_access_denied",
                    user_id=str(user.id),
                    user_role=user.role
                )
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Admin role required"
                )
            
            return await func(*args, **kwargs)
        return wrapper
    return decorator


def require_roles(*allowed_roles: str):
    """Decorator to require one of the explicitly allowed application roles."""
    allowed = frozenset(allowed_roles)
    if not allowed:
        raise ValueError("At least one allowed role is required")

    def decorator(func: Callable):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            user = kwargs.get('current_user')
            if not user:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Authentication required"
                )

            if user.role not in allowed:
                logger.warning(
                    "role_access_denied",
                    user_id=str(user.id),
                    user_role=user.role,
                    allowed_roles=sorted(allowed),
                )
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"One of roles {sorted(allowed)} required"
                )

            return await func(*args, **kwargs)
        return wrapper
    return decorator


def require_operator_or_admin():
    """Decorator to require operator or admin role"""
    def decorator(func: Callable):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            user = kwargs.get('current_user')
            if not user:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Authentication required"
                )
            
            if user.role not in ['admin', 'operator']:
                logger.warning(
                    "operator_access_denied",
                    user_id=str(user.id),
                    user_role=user.role
                )
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Operator or admin role required"
                )
            
            return await func(*args, **kwargs)
        return wrapper
    return decorator

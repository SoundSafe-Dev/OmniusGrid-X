"""Security utilities for authentication and authorization"""

from datetime import datetime, timedelta
from typing import Optional
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import AsyncSessionLocal
from app.db.models import User
from app.core.config import settings


async def get_current_user_ws(token: str) -> Optional[User]:
    """
    Validate JWT token from WebSocket connection and return user.
    Used for WebSocket authentication where OAuth2 scheme isn't available.
    """
    if not token:
        return None
    
    try:
        # Decode JWT
        payload = jwt.decode(
            token, 
            settings.JWT_SECRET_KEY, 
            algorithms=[settings.JWT_ALGORITHM]
        )
        user_id: str = payload.get("sub")
        
        if user_id is None:
            return None
        
        # Check token expiration
        exp = payload.get("exp")
        if exp and datetime.utcnow().timestamp() > exp:
            return None
        
        # Fetch user from database
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(User).where(User.id == user_id)
            )
            user = result.scalar_one_or_none()
            
            if user and user.is_active:
                return user
            
            return None
    
    except JWTError:
        return None
    except Exception:
        return None


async def verify_token(token: str) -> Optional[dict]:
    """
    Verify a JWT token and return the payload without fetching user.
    Useful for quick validation.
    """
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM]
        )
        
        # Check expiration
        exp = payload.get("exp")
        if exp and datetime.utcnow().timestamp() > exp:
            return None
        
        return payload
    
    except JWTError:
        return None

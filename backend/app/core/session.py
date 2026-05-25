"""Session Management"""

import hashlib
from datetime import datetime, timedelta
from typing import Optional, List
from uuid import UUID
from sqlalchemy import select, and_, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User, UserSession
import structlog

logger = structlog.get_logger()

# Session configuration
SESSION_TIMEOUT_MINUTES = 30
MAX_CONCURRENT_SESSIONS = 3


class SessionManager:
    """Session management for user authentication"""
    
    @staticmethod
    def hash_token(token: str) -> str:
        """Hash session token for storage"""
        return hashlib.sha256(token.encode()).hexdigest()
    
    @staticmethod
    async def create_session(
        user_id: str,
        token: str,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        db: AsyncSession = None
    ) -> UserSession:
        """Create a new user session"""
        # Check concurrent session limit
        result = await db.execute(
            select(UserSession).where(
                and_(
                    UserSession.user_id == user_id,
                    UserSession.is_active == True,
                    UserSession.expires_at > datetime.utcnow()
                )
            )
        )
        active_sessions = result.scalars().all()
        
        # Revoke oldest sessions if limit exceeded
        if len(active_sessions) >= MAX_CONCURRENT_SESSIONS:
            sessions_to_revoke = sorted(
                active_sessions,
                key=lambda s: s.created_at
            )[:len(active_sessions) - MAX_CONCURRENT_SESSIONS + 1]
            
            for session in sessions_to_revoke:
                session.is_active = False
                session.revoked_at = datetime.utcnow()
            
            logger.info(
                "sessions_revoked_limit",
                user_id=user_id,
                count=len(sessions_to_revoke)
            )
        
        # Create new session
        token_hash = SessionManager.hash_token(token)
        expires_at = datetime.utcnow() + timedelta(minutes=SESSION_TIMEOUT_MINUTES)
        
        session = UserSession(
            user_id=user_id,
            token_hash=token_hash,
            ip_address=ip_address,
            user_agent=user_agent,
            expires_at=expires_at,
            is_active=True
        )
        
        db.add(session)
        await db.commit()
        await db.refresh(session)
        
        logger.info(
            "session_created",
            session_id=str(session.id),
            user_id=user_id,
            ip_address=ip_address
        )
        
        return session
    
    @staticmethod
    async def validate_session(
        token: str,
        db: AsyncSession
    ) -> Optional[UserSession]:
        """Validate a session token"""
        token_hash = SessionManager.hash_token(token)
        
        result = await db.execute(
            select(UserSession).where(
                and_(
                    UserSession.token_hash == token_hash,
                    UserSession.is_active == True,
                    UserSession.expires_at > datetime.utcnow()
                )
            )
        )
        session = result.scalar_one_or_none()
        
        if session:
            # Update last activity
            session.last_activity_at = datetime.utcnow()
            await db.commit()
        
        return session
    
    @staticmethod
    async def revoke_session(
        session_id: str,
        db: AsyncSession
    ) -> bool:
        """Revoke a specific session"""
        result = await db.execute(
            select(UserSession).where(UserSession.id == session_id)
        )
        session = result.scalar_one_or_none()
        
        if not session:
            return False
        
        session.is_active = False
        session.revoked_at = datetime.utcnow()
        await db.commit()
        
        logger.info(
            "session_revoked",
            session_id=session_id
        )
        
        return True
    
    @staticmethod
    async def revoke_all_user_sessions(
        user_id: str,
        db: AsyncSession
    ) -> int:
        """Revoke all sessions for a user"""
        result = await db.execute(
            select(UserSession).where(
                and_(
                    UserSession.user_id == user_id,
                    UserSession.is_active == True
                )
            )
        )
        sessions = result.scalars().all()
        
        count = 0
        for session in sessions:
            session.is_active = False
            session.revoked_at = datetime.utcnow()
            count += 1
        
        await db.commit()
        
        logger.info(
            "all_sessions_revoked",
            user_id=user_id,
            count=count
        )
        
        return count
    
    @staticmethod
    async def cleanup_expired_sessions(db: AsyncSession) -> int:
        """Clean up expired sessions"""
        cutoff_date = datetime.utcnow() - timedelta(days=7)
        
        result = await db.execute(
            delete(UserSession).where(
                and_(
                    UserSession.is_active == False,
                    UserSession.revoked_at < cutoff_date
                )
            )
        )
        count = result.rowcount
        await db.commit()
        
        if count > 0:
            logger.info(
                "expired_sessions_cleaned",
                count=count
            )
        
        return count
    
    @staticmethod
    async def get_user_sessions(
        user_id: str,
        db: AsyncSession,
        active_only: bool = True
    ) -> List[UserSession]:
        """Get all sessions for a user"""
        query = select(UserSession).where(UserSession.user_id == user_id)
        
        if active_only:
            query = query.where(
                and_(
                    UserSession.is_active == True,
                    UserSession.expires_at > datetime.utcnow()
                )
            )
        
        result = await db.execute(query.order_by(UserSession.created_at.desc()))
        return result.scalars().all()

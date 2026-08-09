"""Durable refresh-session and local-token revocation management."""

import hashlib
from datetime import datetime, timezone
from typing import List, Optional
from uuid import UUID, uuid4

import structlog
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import RevokedToken, UserSession

logger = structlog.get_logger()

MAX_CONCURRENT_SESSIONS = 3


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _uuid(value: UUID | str) -> UUID:
    return value if isinstance(value, UUID) else UUID(str(value))


class SessionManager:
    """Manage refresh sessions without owning the caller's transaction."""

    @staticmethod
    def hash_token(token: str) -> str:
        """Return the one-way value persisted for a refresh token."""
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    @staticmethod
    async def create_session(
        user_id: UUID | str,
        token: str,
        jti: UUID | str,
        expires_at: datetime,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        metadata: Optional[dict] = None,
        db: AsyncSession = None,
    ) -> UserSession:
        """Create one refresh session and enforce the concurrent-session cap."""
        if db is None:
            raise ValueError("db is required")

        user_uuid = _uuid(user_id)
        now = _utcnow()
        result = await db.execute(
            select(UserSession)
            .where(
                UserSession.user_id == user_uuid,
                UserSession.is_active.is_(True),
                UserSession.expires_at > now,
            )
            .order_by(UserSession.created_at.asc())
            .with_for_update()
        )
        active_sessions = list(result.scalars().all())

        overflow = len(active_sessions) - MAX_CONCURRENT_SESSIONS + 1
        for old_session in active_sessions[: max(overflow, 0)]:
            await SessionManager._mark_session_revoked(
                old_session,
                db,
                reason="concurrent_session_limit",
                now=now,
            )

        session = UserSession(
            user_id=user_uuid,
            token_hash=SessionManager.hash_token(token),
            jti=_uuid(jti),
            token_type="refresh",
            ip_address=ip_address,
            user_agent=user_agent,
            expires_at=expires_at,
            is_active=True,
            meta_data=metadata or {},
        )
        db.add(session)
        await db.flush()

        logger.info(
            "session_created",
            session_id=str(session.id),
            user_id=str(user_uuid),
            ip_address=ip_address,
        )
        return session

    @staticmethod
    async def validate_session(
        token: str,
        jti: UUID | str,
        user_id: UUID | str,
        db: AsyncSession,
        *,
        for_update: bool = False,
    ) -> Optional[UserSession]:
        """Resolve an active refresh session by hash, JTI, and owner."""
        query = select(UserSession).where(
            UserSession.token_hash == SessionManager.hash_token(token),
            UserSession.jti == _uuid(jti),
            UserSession.user_id == _uuid(user_id),
            UserSession.token_type == "refresh",
            UserSession.is_active.is_(True),
            UserSession.expires_at > _utcnow(),
        )
        if for_update:
            query = query.with_for_update()

        result = await db.execute(query)
        session = result.scalar_one_or_none()
        if session is not None:
            session.last_activity_at = _utcnow()
        return session

    @staticmethod
    async def rotate_session(
        *,
        old_token: str,
        old_jti: UUID | str,
        user_id: UUID | str,
        new_token: str,
        new_jti: UUID | str,
        new_expires_at: datetime,
        ip_address: Optional[str],
        user_agent: Optional[str],
        db: AsyncSession,
    ) -> Optional[UserSession]:
        """Atomically consume one refresh session and create its replacement."""
        old_session = await SessionManager.validate_session(
            old_token,
            old_jti,
            user_id,
            db,
            for_update=True,
        )
        if old_session is None:
            return None

        replacement_jti = _uuid(new_jti)
        now = _utcnow()
        old_session.replaced_by_jti = replacement_jti
        await SessionManager._mark_session_revoked(
            old_session,
            db,
            reason="rotated",
            now=now,
        )

        replacement = UserSession(
            user_id=_uuid(user_id),
            token_hash=SessionManager.hash_token(new_token),
            jti=replacement_jti,
            token_type="refresh",
            ip_address=ip_address,
            user_agent=user_agent,
            expires_at=new_expires_at,
            is_active=True,
            meta_data={"rotated_from_jti": str(old_session.jti)},
        )
        db.add(replacement)
        await db.flush()

        logger.info(
            "session_rotated",
            old_session_id=str(old_session.id),
            new_session_id=str(replacement.id),
            user_id=str(user_id),
        )
        return replacement

    @staticmethod
    async def revoke_refresh_token(
        *,
        token: str,
        jti: UUID | str,
        user_id: UUID | str,
        db: AsyncSession,
        reason: str = "logout",
    ) -> bool:
        """Revoke a supplied refresh token without persisting the token itself."""
        result = await db.execute(
            select(UserSession)
            .where(
                UserSession.token_hash == SessionManager.hash_token(token),
                UserSession.jti == _uuid(jti),
                UserSession.user_id == _uuid(user_id),
            )
            .with_for_update()
        )
        session = result.scalar_one_or_none()
        if session is None:
            return False
        await SessionManager._mark_session_revoked(session, db, reason=reason)
        return True

    @staticmethod
    async def revoke_session_by_jti(
        *,
        jti: UUID | str,
        user_id: UUID | str,
        db: AsyncSession,
        reason: str = "logout",
    ) -> bool:
        """Revoke the current refresh session linked from an access token."""
        result = await db.execute(
            select(UserSession)
            .where(
                UserSession.jti == _uuid(jti),
                UserSession.user_id == _uuid(user_id),
            )
            .with_for_update()
        )
        session = result.scalar_one_or_none()
        if session is None:
            return False
        await SessionManager._mark_session_revoked(session, db, reason=reason)
        return True

    @staticmethod
    async def revoke_session(
        session_id: UUID | str,
        db: AsyncSession,
        reason: str = "revoked",
    ) -> bool:
        """Revoke a refresh session by database ID."""
        result = await db.execute(
            select(UserSession)
            .where(UserSession.id == _uuid(session_id))
            .with_for_update()
        )
        session = result.scalar_one_or_none()
        if session is None:
            return False
        await SessionManager._mark_session_revoked(session, db, reason=reason)
        return True

    @staticmethod
    async def revoke_all_user_sessions(
        user_id: UUID | str,
        db: AsyncSession,
        reason: str = "revoke_all",
    ) -> int:
        """Revoke every active refresh session for a user."""
        result = await db.execute(
            select(UserSession)
            .where(
                UserSession.user_id == _uuid(user_id),
                UserSession.is_active.is_(True),
            )
            .with_for_update()
        )
        sessions = list(result.scalars().all())
        for session in sessions:
            await SessionManager._mark_session_revoked(
                session,
                db,
                reason=reason,
            )
        return len(sessions)

    @staticmethod
    async def revoke_token_jti(
        *,
        jti: UUID | str,
        user_id: UUID | str,
        token_type: str,
        expires_at: datetime,
        db: AsyncSession,
        reason: str,
        session_id: Optional[UUID | str] = None,
    ) -> bool:
        """Insert a durable denylist row, ignoring an existing identical JTI."""
        values = {
            "id": uuid4(),
            "jti": _uuid(jti),
            "user_id": _uuid(user_id),
            "session_id": _uuid(session_id) if session_id else None,
            "token_type": token_type,
            "expires_at": expires_at,
            "revoked_at": _utcnow(),
            "reason": reason,
        }
        dialect = db.get_bind().dialect.name
        if dialect == "postgresql":
            from sqlalchemy.dialects.postgresql import insert

            statement = insert(RevokedToken).values(**values).on_conflict_do_nothing(
                index_elements=["jti"]
            )
            result = await db.execute(statement)
            return bool(result.rowcount)
        if dialect == "sqlite":
            from sqlalchemy.dialects.sqlite import insert

            statement = insert(RevokedToken).values(**values).on_conflict_do_nothing(
                index_elements=["jti"]
            )
            result = await db.execute(statement)
            return bool(result.rowcount)

        existing = await db.execute(
            select(RevokedToken.id).where(RevokedToken.jti == values["jti"])
        )
        if existing.scalar_one_or_none() is not None:
            return False
        db.add(RevokedToken(**values))
        await db.flush()
        return True

    @staticmethod
    async def is_token_revoked(jti: UUID | str, db: AsyncSession) -> bool:
        """Return whether a JTI is present in the durable denylist."""
        result = await db.execute(
            select(RevokedToken.id).where(RevokedToken.jti == _uuid(jti))
        )
        return result.scalar_one_or_none() is not None

    @staticmethod
    async def is_refresh_session_active(
        jti: UUID | str,
        user_id: UUID | str,
        db: AsyncSession,
    ) -> bool:
        """Return whether an access token's linked refresh session is live.

        Locally issued access tokens carry the refresh-session JTI in ``sid``.
        Requiring that durable session to remain active makes role changes and
        account deactivation effective across every API replica immediately,
        and prevents credentials issued before deactivation from becoming
        usable again after an administrator reactivates the account.
        """

        result = await db.execute(
            select(UserSession.id).where(
                UserSession.jti == _uuid(jti),
                UserSession.user_id == _uuid(user_id),
                UserSession.token_type == "refresh",
                UserSession.is_active.is_(True),
                UserSession.expires_at > _utcnow(),
            )
        )
        return result.scalar_one_or_none() is not None

    @staticmethod
    async def cleanup_expired_sessions(db: AsyncSession) -> int:
        """Delete expired refresh sessions and denylist entries."""
        now = _utcnow()
        revoked_result = await db.execute(
            delete(RevokedToken).where(RevokedToken.expires_at <= now)
        )
        session_result = await db.execute(
            delete(UserSession).where(UserSession.expires_at <= now)
        )
        count = (revoked_result.rowcount or 0) + (session_result.rowcount or 0)
        if count:
            logger.info("expired_auth_records_cleaned", count=count)
        return count

    @staticmethod
    async def get_user_sessions(
        user_id: UUID | str,
        db: AsyncSession,
        active_only: bool = True,
    ) -> List[UserSession]:
        """Return a user's refresh sessions newest first."""
        query = select(UserSession).where(UserSession.user_id == _uuid(user_id))
        if active_only:
            query = query.where(
                UserSession.is_active.is_(True),
                UserSession.expires_at > _utcnow(),
            )
        result = await db.execute(query.order_by(UserSession.created_at.desc()))
        return list(result.scalars().all())

    @staticmethod
    async def _mark_session_revoked(
        session: UserSession,
        db: AsyncSession,
        *,
        reason: str,
        now: Optional[datetime] = None,
    ) -> None:
        revoked_at = now or _utcnow()
        if session.revoked_at is None:
            session.revoked_at = revoked_at
        session.is_active = False
        session.revoked_reason = reason
        await SessionManager.revoke_token_jti(
            jti=session.jti,
            user_id=session.user_id,
            token_type="refresh",
            expires_at=session.expires_at,
            db=db,
            reason=reason,
            session_id=session.id,
        )

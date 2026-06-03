"""Feature flag service (Task 1).

Redis-backed feature flags with support for boolean on/off and deterministic
percentage-based rollouts. Every mutation (create/update/delete) is recorded in
the existing ``audit_logs`` table (migration 009), whose BEFORE INSERT trigger
computes the tamper-evident hash chain.

Storage layout in Redis:
  * ``feature_flag:<key>``  -> JSON document for one flag.
  * ``feature_flags:index`` -> SET of all known flag keys (for listing).

Rollout bucketing is deterministic on ``organization_id`` (per Hamad) so every
user in an org sees the same flag state for partial rollouts.
"""

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Optional

import redis.asyncio as redis
import structlog
from sqlalchemy import text

from app.core.config import settings
from app.db.database import AsyncSessionLocal

logger = structlog.get_logger()

FLAG_KEY_PREFIX = "feature_flag:"
FLAG_INDEX_KEY = "feature_flags:index"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class FeatureFlagError(Exception):
    """Raised for flag operations that fail validation (e.g. duplicate key)."""


class FeatureFlagNotFound(FeatureFlagError):
    """Raised when a referenced flag does not exist."""


class FeatureFlagService:
    """Redis-backed feature flag store with audit logging."""

    def __init__(self) -> None:
        self._client: Optional[redis.Redis] = None

    def _redis(self) -> redis.Redis:
        """Lazily create a shared async Redis client (decoded strings)."""
        if self._client is None:
            self._client = redis.from_url(
                settings.REDIS_URL,
                decode_responses=True,
            )
        return self._client

    # --- CRUD -----------------------------------------------------------------
    async def list_flags(self) -> list[dict[str, Any]]:
        client = self._redis()
        keys = await client.smembers(FLAG_INDEX_KEY)
        if not keys:
            return []
        flags: list[dict[str, Any]] = []
        for key in sorted(keys):
            raw = await client.get(f"{FLAG_KEY_PREFIX}{key}")
            if raw:
                flags.append(json.loads(raw))
        return flags

    async def get_flag(self, key: str) -> Optional[dict[str, Any]]:
        client = self._redis()
        raw = await client.get(f"{FLAG_KEY_PREFIX}{key}")
        return json.loads(raw) if raw else None

    async def create_flag(
        self,
        key: str,
        description: str = "",
        enabled: bool = False,
        rollout_percentage: int = 0,
        actor_id: Optional[str] = None,
        organization_id: Optional[str] = None,
    ) -> dict[str, Any]:
        key = self._validate_key(key)
        rollout_percentage = self._validate_percentage(rollout_percentage)
        client = self._redis()

        if await client.exists(f"{FLAG_KEY_PREFIX}{key}"):
            raise FeatureFlagError(f"Feature flag '{key}' already exists")

        now = _utc_now_iso()
        flag = {
            "key": key,
            "description": description,
            "enabled": bool(enabled),
            "rollout_percentage": rollout_percentage,
            "created_at": now,
            "updated_at": now,
            "updated_by": actor_id,
        }
        await client.set(f"{FLAG_KEY_PREFIX}{key}", json.dumps(flag))
        await client.sadd(FLAG_INDEX_KEY, key)

        await self._audit("feature_flag_created", key, None, flag, actor_id, organization_id)
        return flag

    async def update_flag(
        self,
        key: str,
        description: Optional[str] = None,
        enabled: Optional[bool] = None,
        rollout_percentage: Optional[int] = None,
        actor_id: Optional[str] = None,
        organization_id: Optional[str] = None,
    ) -> dict[str, Any]:
        client = self._redis()
        existing = await self.get_flag(key)
        if existing is None:
            raise FeatureFlagNotFound(f"Feature flag '{key}' not found")

        updated = dict(existing)
        if description is not None:
            updated["description"] = description
        if enabled is not None:
            updated["enabled"] = bool(enabled)
        if rollout_percentage is not None:
            updated["rollout_percentage"] = self._validate_percentage(rollout_percentage)
        updated["updated_at"] = _utc_now_iso()
        updated["updated_by"] = actor_id

        await client.set(f"{FLAG_KEY_PREFIX}{key}", json.dumps(updated))

        await self._audit("feature_flag_updated", key, existing, updated, actor_id, organization_id)
        return updated

    async def delete_flag(
        self,
        key: str,
        actor_id: Optional[str] = None,
        organization_id: Optional[str] = None,
    ) -> None:
        client = self._redis()
        existing = await self.get_flag(key)
        if existing is None:
            raise FeatureFlagNotFound(f"Feature flag '{key}' not found")

        await client.delete(f"{FLAG_KEY_PREFIX}{key}")
        await client.srem(FLAG_INDEX_KEY, key)

        await self._audit("feature_flag_deleted", key, existing, None, actor_id, organization_id)

    # --- Evaluation -----------------------------------------------------------
    async def is_enabled(self, key: str, identity: Optional[str] = None) -> bool:
        """Resolve a flag for a caller identity (default off for unknown flags)."""
        flag = await self.get_flag(key)
        if flag is None or not flag.get("enabled", False):
            return False
        return self._in_rollout(key, flag.get("rollout_percentage", 0), identity)

    async def evaluate_all(self, identity: Optional[str] = None) -> dict[str, bool]:
        """Return {flag_key: resolved_bool} for the given identity.

        Read path is fail-safe: if Redis is unreachable, returns an empty map so
        callers (and the frontend hook) treat every flag as off rather than error.
        """
        try:
            flags = await self.list_flags()
        except Exception as exc:
            logger.warning("feature_flag_evaluate_failed", error=str(exc))
            return {}
        return {
            flag["key"]: (
                bool(flag.get("enabled", False))
                and self._in_rollout(
                    flag["key"], flag.get("rollout_percentage", 0), identity
                )
            )
            for flag in flags
        }

    def _in_rollout(self, key: str, rollout_percentage: int, identity: Optional[str]) -> bool:
        if rollout_percentage >= 100:
            return True
        if rollout_percentage <= 0:
            return False
        # A partial rollout needs a stable identity to bucket on; without one we
        # fail closed so anonymous callers don't flip in and out per request.
        if not identity:
            return False
        return self._bucket(key, identity) < rollout_percentage

    @staticmethod
    def _bucket(key: str, identity: str) -> int:
        """Deterministic 0-99 bucket from (flag key, identity)."""
        digest = hashlib.sha256(f"{key}:{identity}".encode()).hexdigest()
        return int(digest[:8], 16) % 100

    # --- Validation -----------------------------------------------------------
    @staticmethod
    def _validate_key(key: str) -> str:
        key = (key or "").strip()
        if not key:
            raise FeatureFlagError("Feature flag key must not be empty")
        return key

    @staticmethod
    def _validate_percentage(value: int) -> int:
        try:
            value = int(value)
        except (TypeError, ValueError):
            raise FeatureFlagError("rollout_percentage must be an integer")
        if not 0 <= value <= 100:
            raise FeatureFlagError("rollout_percentage must be between 0 and 100")
        return value

    # --- Audit ----------------------------------------------------------------
    async def _audit(
        self,
        action: str,
        flag_key: str,
        before: Optional[dict[str, Any]],
        after: Optional[dict[str, Any]],
        actor_id: Optional[str],
        organization_id: Optional[str],
    ) -> None:
        """Write a flag-change entry to audit_logs (non-fatal on failure).

        hash_chain is filled by the audit_log_hash_chain_trigger (migration 009).
        The flag key lives in details because audit_logs.resource_id is UUID-typed.
        """
        details = {"flag_key": flag_key, "before": before, "after": after}
        try:
            async with AsyncSessionLocal() as session:
                await session.execute(
                    text(
                        """
                        INSERT INTO audit_logs
                            (user_id, organization_id, action, resource_type, details)
                        VALUES
                            (:user_id, :organization_id, :action, 'feature_flag',
                             CAST(:details AS JSONB))
                        """
                    ),
                    {
                        "user_id": actor_id,
                        "organization_id": organization_id,
                        "action": action,
                        "details": json.dumps(details),
                    },
                )
                await session.commit()
        except Exception as exc:
            logger.error("feature_flag_audit_failed", action=action, flag_key=flag_key, error=str(exc))

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None


feature_flag_service = FeatureFlagService()

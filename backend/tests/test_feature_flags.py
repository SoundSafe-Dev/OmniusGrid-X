"""Focused unit tests for the Task 1 feature-flag service.

Runs against an in-memory fakeredis (no Docker), so it exercises the real
WATCH/MULTI transaction paths without a live Redis or Postgres. The audit write
(which would touch Postgres) is stubbed — it is best-effort and out of scope here.
"""

import json

import fakeredis.aioredis as fakeredis
import pytest
import pytest_asyncio

from app.services.feature_flags import (
    FLAG_INDEX_KEY,
    FLAG_KEY_PREFIX,
    FeatureFlagError,
    FeatureFlagNotFound,
    FeatureFlagService,
)


@pytest_asyncio.fixture
async def svc():
    service = FeatureFlagService()
    service._client = fakeredis.FakeRedis(decode_responses=True)

    async def _noaudit(*args, **kwargs):
        return None

    service._audit = _noaudit  # type: ignore[assignment]
    yield service
    await service._client.aclose()


async def test_create_persists_doc_and_index(svc):
    flag = await svc.create_flag("beta", description="d", enabled=True, rollout_percentage=50)
    assert flag["enabled"] is True and flag["rollout_percentage"] == 50
    # both the document and the index entry are written (atomic create)
    assert await svc._client.get(f"{FLAG_KEY_PREFIX}beta") is not None
    assert await svc._client.sismember(FLAG_INDEX_KEY, "beta")


async def test_duplicate_create_raises(svc):
    await svc.create_flag("beta")
    with pytest.raises(FeatureFlagError):
        await svc.create_flag("beta")


async def test_update_partial_merge_preserves_untouched_fields(svc):
    await svc.create_flag("beta", description="d", enabled=True, rollout_percentage=50)
    updated = await svc.update_flag("beta", enabled=False, actor_id="u2")
    assert updated["enabled"] is False
    assert updated["rollout_percentage"] == 50  # preserved
    assert updated["description"] == "d"  # preserved
    assert updated["updated_by"] == "u2"


async def test_update_missing_raises(svc):
    with pytest.raises(FeatureFlagNotFound):
        await svc.update_flag("ghost", enabled=True)


async def test_invalid_percentage_rejected(svc):
    with pytest.raises(FeatureFlagError):
        await svc.create_flag("x", rollout_percentage=150)
    await svc.create_flag("y", rollout_percentage=10)
    with pytest.raises(FeatureFlagError):
        await svc.update_flag("y", rollout_percentage=-1)


async def test_delete_removes_doc_and_index(svc):
    await svc.create_flag("beta")
    await svc.delete_flag("beta")
    assert await svc._client.get(f"{FLAG_KEY_PREFIX}beta") is None
    assert not await svc._client.sismember(FLAG_INDEX_KEY, "beta")  # no orphaned index entry
    assert await svc.list_flags() == []


async def test_delete_missing_raises(svc):
    with pytest.raises(FeatureFlagNotFound):
        await svc.delete_flag("beta")


async def test_watch_abort_retries_without_losing_concurrent_change(svc):
    """Force a WatchError mid-update and confirm the retry preserves the other
    writer's change (the lost-update protection the atomic fix exists for)."""
    await svc.create_flag("x", description="orig", enabled=True, rollout_percentage=10)
    base = svc._client

    class OneShotContender:
        def __init__(self, real):
            self.real, self.fired = real, False

        def pipeline(self, *a, **k):
            pipe = self.real.pipeline(*a, **k)
            real_exec, outer = pipe.execute, self

            async def execute(*ea, **ek):
                if not outer.fired:
                    outer.fired = True
                    doc = {
                        "key": "x", "enabled": True, "rollout_percentage": 99,
                        "description": "concurrent", "created_at": "t",
                        "updated_at": "t", "updated_by": "other",
                    }
                    await outer.real.set(f"{FLAG_KEY_PREFIX}x", json.dumps(doc))
                return await real_exec(*ea, **ek)

            pipe.execute = execute
            return pipe

        def __getattr__(self, n):
            return getattr(self.real, n)

    svc._client = OneShotContender(base)
    result = await svc.update_flag("x", enabled=False, actor_id="writer")
    assert svc._client.fired is True  # a WatchError really was triggered
    assert result["enabled"] is False  # our change applied
    assert result["rollout_percentage"] == 99  # concurrent writer's change preserved


async def test_is_enabled_rollout_bounds_and_determinism(svc):
    await svc.create_flag("off", enabled=True, rollout_percentage=0)
    await svc.create_flag("on", enabled=True, rollout_percentage=100)
    await svc.create_flag("disabled", enabled=False, rollout_percentage=100)
    assert await svc.is_enabled("off", "user-1") is False
    assert await svc.is_enabled("on", "user-1") is True
    assert await svc.is_enabled("disabled", "user-1") is False
    assert await svc.is_enabled("unknown-flag", "user-1") is False  # default off
    # 100% is on regardless of identity; 0% off regardless
    assert await svc.is_enabled("on", None) is True


async def test_evaluate_all_failsafe_returns_empty_on_error(svc):
    async def _boom():
        raise RuntimeError("redis down")

    svc.list_flags = _boom  # type: ignore[assignment]
    assert await svc.evaluate_all("user-1") == {}

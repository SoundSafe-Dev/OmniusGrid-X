"""RedisIdempotencyStore: shared across processes + degrades on Redis failure.

The middleware defaulted to a per-process in-memory store, so with >1 worker a
retried Idempotency-Key on a different worker re-executed. The Redis store shares
one cache across processes; these tests simulate two "workers" as two store
instances over the same Redis.
"""

import asyncio

import fakeredis.aioredis

from app.middleware.idempotency import RedisIdempotencyStore, InMemoryIdempotencyStore


def run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def test_put_on_one_worker_is_visible_to_another():
    async def scenario():
        shared = fakeredis.aioredis.FakeRedis()  # one Redis, two store instances
        worker_a = RedisIdempotencyStore("redis://x", client=shared)
        worker_b = RedisIdempotencyStore("redis://x", client=shared)

        assert await worker_b.get("idem:k1") is None  # nothing yet
        await worker_a.put("idem:k1", 201, b'{"id":"abc"}')

        # The retry lands on worker B — it must see A's cached response, not
        # re-execute. This is exactly what the in-memory store could not do.
        cached = await worker_b.get("idem:k1")
        assert cached == (201, b'{"id":"abc"}')

    run(scenario())


def test_body_with_newlines_roundtrips():
    async def scenario():
        store = RedisIdempotencyStore("redis://x", client=fakeredis.aioredis.FakeRedis())
        body = b'{"a":1}\n{"b":2}'  # body may contain newlines; status split is on the first only
        await store.put("idem:k", 200, body)
        assert await store.get("idem:k") == (200, body)

    run(scenario())


def test_degrades_to_no_dedup_when_redis_is_down():
    """A Redis outage must not fail the mutation — get returns None, put no-ops."""
    class BrokenRedis:
        async def get(self, *a, **k):
            raise ConnectionError("redis down")

        async def set(self, *a, **k):
            raise ConnectionError("redis down")

    async def scenario():
        store = RedisIdempotencyStore("redis://x", client=BrokenRedis())
        # get swallows the error -> treated as a first request (no dedup)
        assert await store.get("idem:k") is None
        # put swallows the error -> no exception bubbles to the request
        await store.put("idem:k", 200, b"body")

    run(scenario())


def test_factory_returns_redis_store_when_url_set(monkeypatch):
    from app.middleware import idempotency
    from app.core import config

    monkeypatch.setattr(config.settings, "REDIS_URL", "redis://localhost:6379/0")
    store = idempotency.make_idempotency_store()
    assert isinstance(store, RedisIdempotencyStore)

    monkeypatch.setattr(config.settings, "REDIS_URL", "")
    assert isinstance(idempotency.make_idempotency_store(), InMemoryIdempotencyStore)

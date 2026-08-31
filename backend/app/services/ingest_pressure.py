"""What the cloud tells edge agents about its own load (FS-865/866).

THE PROBLEM THIS SOLVES, AND WHY IT IS NOT THE ONE THE PLAN DESCRIBED. FS-865 asked for
"load-shedding admission control" on the ingest endpoint. That endpoint exists and
**nothing calls it** — `api/edge_ingest.py` says so in its own header — because the agent
publishes straight to Redpanda. Admission control on a door nobody uses is theatre.

The real shape is this: the agent drains its store-and-forward buffer into Redpanda as
fast as the link allows, and the ingestion worker consumes at whatever rate it can. When
the worker falls behind, nothing tells the agent. Kafka gives a producer no view of
consumer lag, so the producer keeps pushing and the queue keeps growing until the worker
starts SHEDDING — at which point readings are destroyed that were, moments earlier,
sitting safely in a durable buffer on the device.

That is the loss worth preventing. The edge holds data well: an encrypted SQLite buffer,
priority tiers of its own, days of capacity. The cloud holds it badly under pressure,
because its only tool is to drop it. So the right answer is to slow the producer down and
leave the data where it is safe, rather than to accept it and destroy it.

HOW THE SIGNAL TRAVELS. The ingestion worker knows its own pressure — it is the thing
doing the shedding — and writes a level to Redis. The heartbeat endpoint, which every
agent already polls, reads that level and returns it in the ack. The agent slows its
drain. No new connection, no new protocol, no new failure mode.

DEGRADES TO TODAY'S BEHAVIOUR. If Redis is unreachable the level reads `normal`, agents
drain at full rate, and the platform behaves exactly as it did before this existed —
which is the correct failure direction for a mechanism whose job is to be conservative.
"""
from __future__ import annotations

from typing import Literal

import structlog
from redis.exceptions import RedisError

from app.core import redis_client
from app.core.circuit_breaker import CircuitOpen

logger = structlog.get_logger()

#: The levels an agent understands. Deliberately three, not a percentage: an agent has to
#: DO something different for each, and there are only three useful behaviours — carry on,
#: slow down, send only what cannot be reconstructed.
PressureLevel = Literal["normal", "elevated", "critical"]

_KEY = "opsgrid:ingest:pressure"

#: Slightly longer than the worker's publish interval, so a single missed write does not
#: flap agents back to full rate — and short enough that a dead worker's stale "critical"
#: expires rather than throttling the fleet forever. THE EXPIRY IS THE SAFETY PROPERTY: a
#: backpressure signal with no TTL is a fleet-wide outage waiting for the process that
#: wrote it to die.
TTL_SECONDS = 90


async def publish(level: PressureLevel) -> None:
    """Record the current ingest pressure. Called by the ingestion worker."""
    try:
        await redis_client.breaker.call(
            lambda: redis_client.get_redis().set(_KEY, level, ex=TTL_SECONDS)
        )
    except (CircuitOpen, RedisError, OSError) as exc:
        # Never fatal: failing to publish pressure must not stop the worker that is
        # already under pressure from doing its actual job.
        logger.debug("ingest_pressure_publish_failed", error=str(exc)[:120])


async def current() -> PressureLevel:
    """The level to tell agents about. `normal` whenever we cannot say otherwise."""
    try:
        raw = await redis_client.breaker.call(
            lambda: redis_client.get_redis().get(_KEY)
        )
    except (CircuitOpen, RedisError, OSError):
        return "normal"
    if raw in ("elevated", "critical"):
        return raw  # type: ignore[return-value]
    return "normal"


def level_for(shed_rate_per_sec: float, lag_messages: int) -> PressureLevel:
    """Map observed pressure onto a level.

    ANY SHEDDING IS AT LEAST ELEVATED, because shedding is already data loss — by the time
    the worker is dropping readings, asking agents to slow down is overdue rather than
    premature.

    Lag alone is not enough to be critical: a backlog that is draining is a queue doing its
    job. It is lag WITH shedding that says the pipeline cannot catch up, and that is the
    only state where telling agents to hold their data is better than taking it.
    """
    if shed_rate_per_sec > 0 and lag_messages > 10_000:
        return "critical"
    if shed_rate_per_sec > 0 or lag_messages > 10_000:
        return "elevated"
    return "normal"

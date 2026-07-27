"""Cloud ingest-gateway hardening (tasks 11-15).

The landing point for edge telemetry batches. Before a reading reaches the
downstream stream/store it passes five guards:

  11. validation      — structural check of each reading in the batch
  12. dedup           — idempotency keys drop at-least-once retransmissions
  13. sequence        — per-source monotonic sequence tracking (gaps/reorder)
  14. backpressure    — per-agent token-bucket rate limiting
  15. quarantine      — malformed readings retained for inspection and replay

State (dedup cache, sequence table, rate buckets) is in-memory here with an
injectable clock; a multi-replica deployment would back dedup/sequence with
Redis, but the guard logic and its tests are storage-agnostic. ``now`` is always
injected so behaviour is deterministic under test.
"""

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

import structlog

from app.api.edge_enroll import require_agent  # re-exported for callers' convenience  # noqa: F401
from app.services.edge_ca import AgentPrincipal  # noqa: F401  (type re-export)

logger = structlog.get_logger()


# --- task 11: validation ------------------------------------------------------

def validate_reading(reading: Any) -> Optional[str]:
    """Return an error string if the reading is malformed, else ``None``."""
    if not isinstance(reading, dict):
        return "reading is not an object"
    if not reading.get("asset_id"):
        return "missing asset_id"
    ts = reading.get("timestamp_edge")
    if not isinstance(ts, str) or not ts:
        return "missing/invalid timestamp_edge"
    try:
        datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return "unparseable timestamp_edge"
    if not isinstance(reading.get("payload"), dict):
        return "payload is not an object"
    seq = reading.get("sequence_num", 0)
    if not isinstance(seq, int) or isinstance(seq, bool):
        return "sequence_num is not an integer"
    return None


# --- task 12: dedup -----------------------------------------------------------

def idempotency_key(agent_id: str, reading: Dict[str, Any]) -> str:
    """Stable key for a reading.

    Prefers (agent, asset, sequence_num) when a real sequence is present;
    otherwise hashes the identifying envelope so replays still dedup.
    """
    asset = reading.get("asset_id", "")
    seq = reading.get("sequence_num", 0)
    if isinstance(seq, int) and not isinstance(seq, bool) and seq > 0:
        return f"{agent_id}:{asset}:{seq}"
    raw = f"{agent_id}:{asset}:{reading.get('timestamp_edge','')}:{reading.get('topic','')}"
    return f"{agent_id}:{asset}:h:{hashlib.sha256(raw.encode()).hexdigest()[:16]}"


class DedupCache:
    """TTL set of idempotency keys (in-memory; Redis-backable in prod)."""

    def __init__(self, ttl_seconds: float = 3600.0):
        self.ttl = ttl_seconds
        self._seen: Dict[str, float] = {}

    def seen(self, key: str, now: float) -> bool:
        self._evict(now)
        if key in self._seen:
            return True
        self._seen[key] = now
        return False

    def _evict(self, now: float) -> None:
        cutoff = now - self.ttl
        if len(self._seen) > 10000:  # bounded scan cadence
            self._seen = {k: t for k, t in self._seen.items() if t >= cutoff}


# --- task 13: sequence tracking ----------------------------------------------

class SequenceTracker:
    """Per (agent, asset) highest sequence seen, to spot gaps and reordering."""

    def __init__(self) -> None:
        self._last: Dict[Tuple[str, str], int] = {}

    def observe(self, agent_id: str, asset_id: str, seq: int) -> str:
        """Classify a sequence number: 'ok' | 'gap' | 'reorder'."""
        key = (agent_id, asset_id)
        last = self._last.get(key)
        if last is None or seq == last + 1:
            self._last[key] = max(seq, last or 0)
            return "ok"
        if seq <= last:
            return "reorder"
        # seq > last + 1 -> missed messages between them
        self._last[key] = seq
        return "gap"


# --- task 14: backpressure ----------------------------------------------------

class TokenBucket:
    """Per-agent token bucket rate limiter."""

    def __init__(self, rate_per_sec: float, burst: float):
        self.rate = rate_per_sec
        self.burst = burst
        self._tokens: Dict[str, float] = {}
        self._last: Dict[str, float] = {}

    def allow(self, agent_id: str, cost: float, now: float) -> bool:
        tokens = self._tokens.get(agent_id, self.burst)
        last = self._last.get(agent_id, now)
        tokens = min(self.burst, tokens + (now - last) * self.rate)
        self._last[agent_id] = now
        if tokens >= cost:
            self._tokens[agent_id] = tokens - cost
            return True
        self._tokens[agent_id] = tokens
        return False


# --- orchestration ------------------------------------------------------------

@dataclass
class IngestResult:
    accepted: List[Dict[str, Any]] = field(default_factory=list)
    deduped: int = 0
    #: The quarantined readings THEMSELVES, not a count of them — mirroring
    #: ``accepted``, and for the same reason: the caller has to be able to do
    #: something with them. This was an ``int``, and the reading was passed to a
    #: sink that defaulted to logging ``agent_id`` and ``reason`` while discarding
    #: the payload. So the endpoint answered ``quarantined: 47`` — a word that
    #: means "set aside for inspection" — for 47 readings that no longer existed
    #: anywhere. ``summary`` still reports the count, so the API contract is
    #: unchanged.
    quarantined: List[Dict[str, Any]] = field(default_factory=list)
    out_of_order: int = 0
    gaps: int = 0

    @property
    def summary(self) -> Dict[str, int]:
        return {
            "accepted": len(self.accepted),
            "deduped": self.deduped,
            "quarantined": len(self.quarantined),
            "out_of_order": self.out_of_order,
            "gaps": self.gaps,
        }


class RateLimited(Exception):
    """Raised when an agent exceeds its ingest rate; endpoint maps to HTTP 429."""


class EdgeIngestGateway:
    """Applies the five ingest guards to an authenticated agent's batch."""

    def __init__(
        self,
        rate_per_sec: float = 500.0,
        burst: float = 2000.0,
        dedup_ttl_seconds: float = 3600.0,
        quarantine_sink: Optional[Callable[[str, Dict[str, Any], str], None]] = None,
    ):
        self._bucket = TokenBucket(rate_per_sec, burst)
        self._dedup = DedupCache(dedup_ttl_seconds)
        self._seq = SequenceTracker()
        self._quarantine_sink = quarantine_sink or self._default_quarantine

    def _default_quarantine(self, agent_id: str, reading: Dict[str, Any], reason: str) -> None:
        """Log the rejection. It does NOT retain the reading — ``ingest`` does.

        This used to be the whole of quarantine, which is why the reading was
        lost: it records that something was rejected and why, never what. That is
        the right amount for a log line and the wrong amount for a dead-letter
        sink, so retention now lives in ``IngestResult.quarantined`` where every
        caller gets it, whether or not a sink is injected.
        """
        logger.warning("edge_ingest_quarantined", agent_id=agent_id, reason=reason)

    def ingest(
        self, agent_id: str, readings: List[Any], now: Optional[datetime] = None
    ) -> IngestResult:
        now = now or datetime.now(timezone.utc)
        ts = now.timestamp()

        # Backpressure (task 14): charge one token per reading; refuse the whole
        # batch if the agent is over budget so it retries with backoff.
        if not self._bucket.allow(agent_id, float(len(readings)), ts):
            raise RateLimited(f"agent {agent_id} exceeded ingest rate")

        result = IngestResult()
        for reading in readings:
            # 11: validation -> 15: quarantine on failure
            err = validate_reading(reading)
            if err is not None:
                payload = reading if isinstance(reading, dict) else {"_raw": repr(reading)}
                self._quarantine_sink(agent_id, payload, err)
                # Retain the reading, not just the fact that there was one. A
                # non-dict reading is kept as its repr rather than dropped for
                # being the wrong shape — "it was not even a dict" is exactly the
                # kind of thing an investigation needs to see.
                result.quarantined.append({
                    "agent_id": agent_id,
                    "reason": err,
                    "reading": payload,
                    "quarantined_at": now.isoformat(),
                })
                continue

            # 12: dedup
            key = idempotency_key(agent_id, reading)
            if self._dedup.seen(key, ts):
                result.deduped += 1
                continue

            # 13: sequence classification (informational; still accepted)
            cls = self._seq.observe(agent_id, reading["asset_id"], int(reading.get("sequence_num", 0)))
            if cls == "reorder":
                result.out_of_order += 1
            elif cls == "gap":
                result.gaps += 1

            result.accepted.append(reading)

        return result


# --- Redpanda handoff (audit FIX #2) -------------------------------------------
# Accepted readings are published to `telemetry.{org}.{asset}` — the exact topic
# pattern app/workers/ingestion.py consumes — completing the edge->cloud chain
# that previously dropped readings after the guards.

import asyncio as _asyncio
import json as _json


class RedpandaForwarder:
    """Fire-and-forget publisher with a failure circuit.

    The producer is created lazily on first use; if the broker is unreachable
    (local dev, smoke tests) the forwarder trips open for ``retry_seconds`` and
    counts drops instead of stalling requests. ``producer_factory`` is injectable
    for tests.
    """

    def __init__(self, bootstrap_servers: Optional[str] = None,
                 retry_seconds: float = 60.0, producer_factory=None):
        self._bootstrap = bootstrap_servers
        self._retry_seconds = retry_seconds
        self._producer = None
        self._producer_factory = producer_factory
        self._unavailable_until = 0.0
        self._lock = _asyncio.Lock()
        self.forwarded = 0
        self.dropped = 0

    def _now(self) -> float:
        return _asyncio.get_event_loop().time()

    async def _get_producer(self):
        if self._producer is not None:
            return self._producer
        if self._now() < self._unavailable_until:
            return None
        async with self._lock:
            if self._producer is not None:
                return self._producer
            try:
                if self._producer_factory is not None:
                    producer = self._producer_factory()
                else:
                    from aiokafka import AIOKafkaProducer
                    from app.core.config import settings
                    producer = AIOKafkaProducer(
                        bootstrap_servers=self._bootstrap or settings.REDPANDA_URL,
                        request_timeout_ms=3000,
                        value_serializer=lambda v: _json.dumps(v).encode(),
                    )
                await producer.start()
                self._producer = producer
                logger.info("edge_ingest_forwarder_connected")
            except Exception as exc:
                self._unavailable_until = self._now() + self._retry_seconds
                logger.warning("edge_ingest_forwarder_unavailable", error=str(exc))
                return None
        return self._producer

    async def forward(self, organization_id: str, readings: List[Dict[str, Any]]) -> int:
        """Publish accepted readings; returns how many were sent."""
        producer = await self._get_producer()
        if producer is None:
            self.dropped += len(readings)
            return 0
        sent = 0
        for reading in readings:
            topic = f"telemetry.{organization_id}.{reading.get('asset_id')}"
            try:
                await producer.send_and_wait(topic, reading)
                sent += 1
            except Exception as exc:
                self.dropped += 1
                # Trip the circuit; the edge agent's store-and-forward retains
                # the data and will re-deliver, so dropping here is safe.
                self._unavailable_until = self._now() + self._retry_seconds
                self._producer = None
                logger.warning("edge_ingest_forward_failed", error=str(exc))
                break
        self.forwarded += sent
        return sent

    async def forward_quarantined(self, agent_id: str, records: List[Dict[str, Any]]) -> int:
        """Publish quarantined readings to the dead-letter topic. Returns how many.

        KEYED ON agent_id, NOT asset_id, and that is the point. These readings
        failed validation, so nothing inside them can be trusted for routing — the
        missing or malformed field may well be `asset_id` itself. ``agent_id``
        comes from the verified client certificate, so it is always present and
        always right, and "which agent is emitting garbage" is the question an
        operator actually opens this topic to answer.

        Shares the forwarder's circuit with ``forward``: on broker outage this
        trips too, and the edge agent's store-and-forward re-delivers the batch.
        """
        producer = await self._get_producer()
        if producer is None:
            self.dropped += len(records)
            return 0
        sent = 0
        for record in records:
            try:
                await producer.send_and_wait(f"telemetry.dlq.{agent_id}", record)
                sent += 1
            except Exception as exc:
                self.dropped += 1
                self._unavailable_until = self._now() + self._retry_seconds
                self._producer = None
                logger.warning("edge_ingest_dlq_forward_failed", error=str(exc))
                break
        self.forwarded += sent
        return sent

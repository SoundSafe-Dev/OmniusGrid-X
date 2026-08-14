"""Server-side alarm rule evaluation against incoming telemetry (FS-219).

WHAT WAS MISSING. Alarms only existed as discrete events the edge agent chose to
emit, and their severity was whatever the edge sent
(``severity=data.get('severity', 'medium')`` in app/workers/ingestion.py).
Nothing on the server looked at telemetry values, so an operator could not
express "alert when temperature exceeds 80 for 5 minutes". This module is that
evaluation; app/api/alarm_rules.py is where the thresholds are defined.

WHY THIS NEEDS STATE. A rule with ``duration_seconds > 0`` is not a function of a
single reading — it is a statement about a *window*. Deciding whether to fire
requires knowing when the breach started, and deciding whether to fire *again*
requires knowing whether we already did. Both facts have to outlive the message
being processed, and with more than one ingestion replica they have to be shared
across processes, or two workers each hold half the picture and the same rule
fires twice.

So the breach window lives in Redis, keyed by (rule, asset), mirroring
``RedisIdempotencyStore`` in app/middleware/idempotency.py — including its failure
posture:

    A Redis outage degrades behaviour, it does not fail ingestion.

That trade is deliberate and worth being explicit about, because it is not
free. Without the shared store, ``duration_seconds`` rules cannot be evaluated
correctly (there is nowhere to record when the breach began), so on the fallback
path they are evaluated per-process. The consequence is under-firing or
duplicate firing during an outage — never a dropped telemetry write. Losing
telemetry to protect an alarm would be the wrong way round.

HYSTERESIS. Clearing uses ``threshold ± hysteresis`` rather than ``threshold``,
so a metric sitting exactly on the boundary does not alternate between firing
and clearing on sensor noise. Without it, a sensor reading 80.0, 79.9, 80.1
against "> 80" would raise and clear an alarm on every sample.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence

import asyncio

import structlog
from redis import exceptions as redis_exceptions
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Alarm, AlarmRule, Asset

logger = structlog.get_logger()

# Breach state is worthless once it is older than any plausible duration window,
# and leaving it forever would leak a key per (rule, asset) that ever breached.
# 24h comfortably exceeds any sane duration_seconds while bounding the keyspace.
_STATE_TTL_SECONDS = 86_400


def _compare(value: float, comparator: str, threshold: float) -> bool:
    if comparator == "gt":
        return value > threshold
    if comparator == "gte":
        return value >= threshold
    if comparator == "lt":
        return value < threshold
    if comparator == "lte":
        return value <= threshold
    if comparator == "eq":
        return value == threshold
    if comparator == "ne":
        return value != threshold
    # Unreachable while the CHECK constraint in migration 047 holds. Do not guess
    # a default: a rule whose comparator we cannot evaluate must not silently
    # behave as "never breaching", which would be a rule that looks configured
    # and does nothing.
    raise ValueError(f"unknown comparator {comparator!r}")


def _has_cleared(value: float, comparator: str, threshold: float, hysteresis: float) -> bool:
    """Has the value returned past the threshold by the full hysteresis band?

    For an upper bound (gt/gte) the value must fall to ``threshold - hysteresis``;
    for a lower bound (lt/lte) it must rise to ``threshold + hysteresis``.
    Equality comparators have no direction, so hysteresis does not apply and
    "not breaching" is enough.
    """
    if hysteresis <= 0 or comparator in ("eq", "ne"):
        return not _compare(value, comparator, threshold)
    if comparator in ("gt", "gte"):
        return value <= threshold - hysteresis
    return value >= threshold + hysteresis


class InMemoryBreachStore:
    """Per-process breach state. Correct for a single worker; see module docstring.

    Keyed the same way as the Redis store so the two are interchangeable.
    """

    def __init__(self) -> None:
        self._data: Dict[str, tuple[float, float]] = {}

    async def get(self, key: str, now: Optional[float] = None) -> Optional[tuple[float, float]]:
        """Read breach state, evicting it if older than the TTL.

        ``now`` is the CALLER's clock, not ``time.time()``. Evaluation may be
        driven by an injected clock (tests, replay), and mixing an injected
        timestamp with wall-clock here made every window look expired — the
        window start would be discarded on the very next sample and a duration
        rule could never elapse. The store must measure age on the same clock
        that recorded the start.
        """
        entry = self._data.get(key)
        if entry is None:
            return None
        started_at, fired_at = entry
        reference = time.time() if now is None else now
        if reference - started_at > _STATE_TTL_SECONDS:
            self._data.pop(key, None)
            return None
        return entry

    async def start(self, key: str, started_at: float) -> None:
        # setdefault semantics: the FIRST breaching sample defines the window
        # start. Overwriting on every sample would keep pushing the start
        # forward and a duration rule would never elapse.
        self._data.setdefault(key, (started_at, 0.0))

    async def mark_fired(self, key: str, fired_at: float) -> None:
        started_at, _ = self._data.get(key, (fired_at, 0.0))
        self._data[key] = (started_at, fired_at)

    async def clear(self, key: str) -> None:
        self._data.pop(key, None)


class RedisBreachStore:
    """Breach state shared across ingestion replicas.

    Same contract as InMemoryBreachStore. Every operation degrades to a no-op on
    a Redis error and logs, so ingestion keeps writing telemetry during an
    outage — see the module docstring for what that costs.
    """

    def __init__(self, redis_url: str, client=None):
        self._url = redis_url
        self._client = client  # injectable for tests (e.g. fakeredis)

    def _redis(self):
        if self._client is None:
            import redis.asyncio as redis

            self._client = redis.from_url(self._url, decode_responses=True)
        return self._client

    async def get(self, key: str, now: Optional[float] = None) -> Optional[tuple[float, float]]:
        # `now` is part of the shared contract with InMemoryBreachStore but unused
        # here: expiry is enforced by Redis EXPIRE, not by comparing timestamps.
        try:
            raw = await self._redis().hgetall(key)
        except (redis_exceptions.RedisError, OSError, asyncio.TimeoutError) as exc:
            # What the redis client actually raises when the store is unreachable —
            # degrade, never fail ingestion. The broad catch also hid programming
            # errors in these methods as "store unavailable" (FS-704's ratchet payment).
            logger.warning("alarm_rule_state_get_failed", error=str(exc))
            return None
        if not raw:
            return None
        try:
            return float(raw["started_at"]), float(raw.get("fired_at", 0.0))
        except (KeyError, TypeError, ValueError):
            return None

    async def start(self, key: str, started_at: float) -> None:
        try:
            r = self._redis()
            # HSETNX so only the first breaching sample sets the window start.
            created = await r.hsetnx(key, "started_at", started_at)
            if created:
                await r.hsetnx(key, "fired_at", 0.0)
            await r.expire(key, _STATE_TTL_SECONDS)
        except (redis_exceptions.RedisError, OSError, asyncio.TimeoutError) as exc:
            logger.warning("alarm_rule_state_start_failed", error=str(exc))

    async def mark_fired(self, key: str, fired_at: float) -> None:
        try:
            r = self._redis()
            await r.hset(key, "fired_at", fired_at)
            await r.expire(key, _STATE_TTL_SECONDS)
        except (redis_exceptions.RedisError, OSError, asyncio.TimeoutError) as exc:
            logger.warning("alarm_rule_state_fired_failed", error=str(exc))

    async def clear(self, key: str) -> None:
        try:
            await self._redis().delete(key)
        except (redis_exceptions.RedisError, OSError, asyncio.TimeoutError) as exc:
            logger.warning("alarm_rule_state_clear_failed", error=str(exc))


def make_breach_store():
    """Redis-backed when REDIS_URL is set, else per-process.

    Mirrors make_idempotency_store(). The in-memory fallback keeps local dev and
    the offline demo path working without Redis.
    """
    from app.core.config import settings

    redis_url = getattr(settings, "REDIS_URL", None)
    if redis_url:
        return RedisBreachStore(redis_url)
    return InMemoryBreachStore()


def _state_key(rule_id: Any, asset_id: Any) -> str:
    return f"alarmrule:{rule_id}:{asset_id}"


@dataclass
class RuleOutcome:
    """What evaluation decided for one rule, for logging and tests."""

    rule_id: str
    breaching: bool
    fired: bool
    reason: str


def _render_message(rule: AlarmRule, asset_id: str, metric_name: str, value: float) -> str:
    if rule.message_template:
        try:
            return rule.message_template.format(
                asset_id=asset_id,
                metric_name=metric_name,
                value=value,
                threshold=rule.threshold,
            )
        except (KeyError, IndexError, ValueError):
            # A malformed template must not stop the alarm from being raised —
            # the alarm is the point, the wording is cosmetic.
            logger.warning(
                "alarm_rule_message_template_invalid",
                rule_id=str(rule.id),
                template=rule.message_template,
            )
    symbol = {"gt": ">", "gte": ">=", "lt": "<", "lte": "<=", "eq": "==", "ne": "!="}[
        rule.comparator
    ]
    return f"{metric_name} {value} {symbol} {rule.threshold} ({rule.name})"


async def load_rules_for_metrics(
    session: AsyncSession,
    organization_id: Any,
    metric_names: Iterable[str],
) -> List[AlarmRule]:
    """Enabled rules in this org watching any of these metrics.

    Batched deliberately. This runs on the ingestion hot path, once per telemetry
    message rather than once per metric in it, and hits the
    (organization_id, metric_name, is_enabled) index from migration 047. Asset
    targeting is applied afterwards in Python by ``applies_to_asset`` so the
    common case — an organization with no rules at all — costs ONE indexed query
    and no asset fetch.
    """
    names = list(metric_names)
    if not names:
        return []
    stmt = select(AlarmRule).where(
        AlarmRule.organization_id == organization_id,
        AlarmRule.metric_name.in_(names),
        AlarmRule.is_enabled.is_(True),
    )
    return list((await session.execute(stmt)).scalars().all())


def applies_to_asset(rule: AlarmRule, asset: Asset) -> bool:
    """Does this rule target this asset?

    A rule with no asset/asset_type/workcell set applies to every asset in the
    organization. Otherwise ANY matching dimension is enough — an operator who
    sets both a workcell and an asset type means "either", not "both", because
    the narrower field would make the broader one unreachable.
    """
    if rule.asset_id is None and rule.asset_type_id is None and rule.workcell_id is None:
        return True
    # str() both sides: UUIDString reads back as a canonical dashed str on every
    # dialect, but a rule loaded in the same session can still hold a UUID object.
    if rule.asset_id is not None and str(rule.asset_id) == str(asset.id):
        return True
    if rule.asset_type_id is not None and str(rule.asset_type_id) == str(asset.asset_type_id):
        return True
    if rule.workcell_id is not None and str(rule.workcell_id) == str(asset.workcell_id):
        return True
    return False


async def load_rules_for_metric(
    session: AsyncSession,
    organization_id: Any,
    asset: Asset,
    metric_name: str,
) -> Sequence[AlarmRule]:
    """Single-metric convenience wrapper around the batch loader."""
    rules = await load_rules_for_metrics(session, organization_id, [metric_name])
    return [r for r in rules if applies_to_asset(r, asset)]


async def evaluate_metric(
    session: AsyncSession,
    store,
    *,
    organization_id: Any,
    asset: Asset,
    metric_name: str,
    value: float,
    now: Optional[float] = None,
    rules: Optional[Sequence[AlarmRule]] = None,
) -> List[RuleOutcome]:
    """Evaluate every applicable rule for one telemetry reading.

    Adds Alarm rows to ``session`` but does NOT commit — the caller owns the
    transaction so a raised alarm and the telemetry that caused it land together
    or not at all.

    Pass ``rules`` to reuse a batch already loaded for the whole message (what the
    ingestion worker does); omit it and the rules for this one metric are fetched.
    """
    now = time.time() if now is None else now
    outcomes: List[RuleOutcome] = []

    if rules is None:
        rules = await load_rules_for_metric(session, organization_id, asset, metric_name)
    else:
        rules = [
            r
            for r in rules
            if r.metric_name == metric_name and applies_to_asset(r, asset)
        ]
    for rule in rules:
        key = _state_key(rule.id, asset.id)
        try:
            breaching = _compare(value, rule.comparator, rule.threshold)
        except ValueError:
            logger.error(
                "alarm_rule_unknown_comparator",
                rule_id=str(rule.id),
                comparator=rule.comparator,
            )
            outcomes.append(RuleOutcome(str(rule.id), False, False, "bad_comparator"))
            continue

        state = await store.get(key, now)

        if not breaching:
            # Only tear the window down once the value has cleared the hysteresis
            # band. Between threshold and threshold±hysteresis we are in neither
            # state: keep the window so a brief dip does not restart a long
            # duration countdown from zero.
            if state is not None and _has_cleared(
                value, rule.comparator, rule.threshold, rule.hysteresis
            ):
                await store.clear(key)
                outcomes.append(RuleOutcome(str(rule.id), False, False, "cleared"))
            else:
                outcomes.append(RuleOutcome(str(rule.id), False, False, "not_breaching"))
            continue

        if state is None:
            await store.start(key, now)
            state = (now, 0.0)

        started_at, fired_at = state

        if fired_at:
            # Already raised for this breach window. Re-raising per message would
            # produce one alarm per telemetry sample for as long as the condition
            # holds — thousands of rows for one real event.
            outcomes.append(RuleOutcome(str(rule.id), True, False, "already_fired"))
            continue

        if now - started_at < rule.duration_seconds:
            outcomes.append(
                RuleOutcome(str(rule.id), True, False, "within_duration_window")
            )
            continue

        session.add(
            Alarm(
                asset_id=asset.id,
                organization_id=organization_id,
                alarm_code=rule.alarm_code,
                severity=rule.severity,
                message=_render_message(rule, str(asset.id), metric_name, value),
                description=rule.description,
                is_active=True,
                is_acknowledged=False,
                occurred_at=_utcnow(),
                meta_data={
                    # Provenance: distinguishes a server-evaluated alarm from an
                    # edge-emitted one, and records what actually tripped.
                    "source": "alarm_rule",
                    "rule_id": str(rule.id),
                    "rule_name": rule.name,
                    "metric_name": metric_name,
                    "value": value,
                    "threshold": rule.threshold,
                    "comparator": rule.comparator,
                    "duration_seconds": rule.duration_seconds,
                },
            )
        )
        await store.mark_fired(key, now)
        logger.warning(
            "alarm_rule_fired",
            rule_id=str(rule.id),
            rule_name=rule.name,
            asset_id=str(asset.id),
            metric_name=metric_name,
            value=value,
            threshold=rule.threshold,
            severity=rule.severity,
        )
        outcomes.append(RuleOutcome(str(rule.id), True, True, "fired"))

    return outcomes


def _utcnow():
    from datetime import datetime, timezone

    return datetime.now(timezone.utc)

"""Alarm rule evaluation semantics (FS-219).

These tests are about the parts that are easy to get subtly wrong and impossible
to notice in production until someone is paged a thousand times:

* a breach shorter than ``duration_seconds`` must NOT fire
* a breach longer than it must fire exactly ONCE, not once per telemetry sample
* hysteresis must stop a value sitting on the threshold from flapping
* a new breach after a genuine clear must be able to fire again

They use a fake clock rather than sleeping, so the duration logic is asserted
directly instead of approximately. No database or Redis is required: the store
contract is small and the in-memory implementation is the one the offline demo
path actually uses.
"""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.services.alarm_rules import (
    InMemoryBreachStore,
    _compare,
    _has_cleared,
    applies_to_asset,
    evaluate_metric,
)


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------

class _FakeSession:
    """Captures added rows. Evaluation never commits — the caller owns that."""

    def __init__(self):
        self.added = []

    def add(self, obj):
        self.added.append(obj)


def _rule(**over):
    """An AlarmRule-shaped object.

    A SimpleNamespace rather than the ORM model: evaluation only reads attributes,
    and constructing real ORM instances would drag in a session and a live schema
    for logic that has nothing to do with either.
    """
    base = dict(
        id=uuid4(),
        name="Hot spindle",
        description=None,
        metric_name="temperature",
        comparator="gt",
        threshold=80.0,
        duration_seconds=0,
        hysteresis=0.0,
        severity="critical",
        alarm_code="TEMP_HIGH",
        message_template=None,
        asset_id=None,
        asset_type_id=None,
        workcell_id=None,
        is_enabled=True,
    )
    base.update(over)
    return SimpleNamespace(**base)


def _asset(**over):
    base = dict(id=uuid4(), asset_type_id=uuid4(), workcell_id=uuid4())
    base.update(over)
    return SimpleNamespace(**base)


async def _evaluate(session, store, rule, asset, value, now, org=None):
    return await evaluate_metric(
        session,
        store,
        organization_id=org or uuid4(),
        asset=asset,
        metric_name=rule.metric_name,
        value=value,
        now=now,
        rules=[rule],
    )


# ---------------------------------------------------------------------------
# Comparators
# ---------------------------------------------------------------------------

class TestComparators:
    @pytest.mark.parametrize(
        "comparator,value,expected",
        [
            ("gt", 81, True), ("gt", 80, False),
            ("gte", 80, True), ("gte", 79, False),
            ("lt", 79, True), ("lt", 80, False),
            ("lte", 80, True), ("lte", 81, False),
            ("eq", 80, True), ("eq", 80.5, False),
            ("ne", 81, True), ("ne", 80, False),
        ],
    )
    def test_every_comparator(self, comparator, value, expected):
        assert _compare(value, comparator, 80.0) is expected

    def test_unknown_comparator_raises_rather_than_defaulting(self):
        """A rule we cannot evaluate must be loud.

        Returning False would make it a rule that looks configured in the UI and
        silently never fires — the failure mode this codebase keeps producing.
        """
        with pytest.raises(ValueError):
            _compare(1.0, "GREATER_THAN", 0.0)


# ---------------------------------------------------------------------------
# Duration windows
# ---------------------------------------------------------------------------

class TestDurationWindow:
    async def test_zero_duration_fires_on_first_breaching_sample(self):
        session, store = _FakeSession(), InMemoryBreachStore()
        rule, asset = _rule(duration_seconds=0), _asset()

        out = await _evaluate(session, store, rule, asset, 81.0, now=1000.0)

        assert [o.reason for o in out] == ["fired"]
        assert len(session.added) == 1

    async def test_breach_shorter_than_duration_does_not_fire(self):
        """The whole point of duration_seconds: a 4-minute spike on a 5-minute
        rule is not an alarm."""
        session, store = _FakeSession(), InMemoryBreachStore()
        rule, asset = _rule(duration_seconds=300), _asset()

        first = await _evaluate(session, store, rule, asset, 81.0, now=1000.0)
        assert [o.reason for o in first] == ["within_duration_window"]

        # 240s later — still inside the window.
        later = await _evaluate(session, store, rule, asset, 81.0, now=1240.0)
        assert [o.reason for o in later] == ["within_duration_window"]

        assert session.added == [], "fired before the duration elapsed"

    async def test_breach_longer_than_duration_fires_once_only(self):
        """Fires when the window elapses, then stays quiet however many samples
        arrive. Without the fired marker this produces one alarm row per telemetry
        message for as long as the condition holds."""
        session, store = _FakeSession(), InMemoryBreachStore()
        rule, asset = _rule(duration_seconds=300), _asset()

        await _evaluate(session, store, rule, asset, 81.0, now=1000.0)
        fired = await _evaluate(session, store, rule, asset, 81.0, now=1301.0)
        assert [o.reason for o in fired] == ["fired"]
        assert len(session.added) == 1

        for t in (1302.0, 1400.0, 5000.0):
            again = await _evaluate(session, store, rule, asset, 81.0, now=t)
            assert [o.reason for o in again] == ["already_fired"]

        assert len(session.added) == 1, "re-fired within the same breach window"

    async def test_window_start_is_not_pushed_forward_by_later_samples(self):
        """If each breaching sample reset the start, a duration rule would never
        elapse under a steady stream of readings."""
        session, store = _FakeSession(), InMemoryBreachStore()
        rule, asset = _rule(duration_seconds=100), _asset()

        for t in (1000.0, 1020.0, 1040.0, 1060.0, 1080.0):
            await _evaluate(session, store, rule, asset, 81.0, now=t)
        assert session.added == []

        fired = await _evaluate(session, store, rule, asset, 81.0, now=1101.0)
        assert [o.reason for o in fired] == ["fired"], (
            "window start drifted with each sample"
        )


# ---------------------------------------------------------------------------
# Clearing and hysteresis
# ---------------------------------------------------------------------------

class TestClearingAndHysteresis:
    async def test_clears_when_value_returns_below_threshold(self):
        session, store = _FakeSession(), InMemoryBreachStore()
        rule, asset = _rule(duration_seconds=0), _asset()

        await _evaluate(session, store, rule, asset, 81.0, now=1000.0)
        cleared = await _evaluate(session, store, rule, asset, 70.0, now=1010.0)
        assert [o.reason for o in cleared] == ["cleared"]

    async def test_can_fire_again_after_a_genuine_clear(self):
        """A second real event must alarm. If clearing did not reset the fired
        marker, the first alarm would be the only one a rule ever raised."""
        session, store = _FakeSession(), InMemoryBreachStore()
        rule, asset = _rule(duration_seconds=0), _asset()

        await _evaluate(session, store, rule, asset, 81.0, now=1000.0)
        await _evaluate(session, store, rule, asset, 70.0, now=1010.0)
        again = await _evaluate(session, store, rule, asset, 82.0, now=1020.0)

        assert [o.reason for o in again] == ["fired"]
        assert len(session.added) == 2

    async def test_hysteresis_prevents_flapping_on_the_threshold(self):
        """A sensor reading 81, 79.5, 81 against "> 80" with a 2.0 clear band is
        ONE event, not two. Without hysteresis the 79.5 clears the breach and the
        next 81 raises a second alarm."""
        session, store = _FakeSession(), InMemoryBreachStore()
        rule, asset = _rule(duration_seconds=0, hysteresis=2.0), _asset()

        await _evaluate(session, store, rule, asset, 81.0, now=1000.0)
        assert len(session.added) == 1

        # 79.5 is below the threshold but inside the clear band (needs <= 78.0).
        middling = await _evaluate(session, store, rule, asset, 79.5, now=1010.0)
        assert [o.reason for o in middling] == ["not_breaching"]

        back_up = await _evaluate(session, store, rule, asset, 81.0, now=1020.0)
        assert [o.reason for o in back_up] == ["already_fired"]
        assert len(session.added) == 1, "flapped: raised a second alarm on noise"

        # Falling all the way through the band is a real clear.
        real_clear = await _evaluate(session, store, rule, asset, 77.0, now=1030.0)
        assert [o.reason for o in real_clear] == ["cleared"]
        assert len(
            (await _evaluate(session, store, rule, asset, 81.0, now=1040.0))
        ) == 1
        assert len(session.added) == 2

    @pytest.mark.parametrize(
        "comparator,threshold,hysteresis,value,cleared",
        [
            # Upper bound: must fall to threshold - hysteresis.
            ("gt", 80.0, 2.0, 79.0, False),
            ("gt", 80.0, 2.0, 78.0, True),
            # Lower bound: must RISE to threshold + hysteresis. Getting this
            # direction wrong makes a low-pressure rule unclearable.
            ("lt", 20.0, 2.0, 21.0, False),
            ("lt", 20.0, 2.0, 22.0, True),
            # Equality has no direction, so hysteresis does not apply.
            ("eq", 80.0, 5.0, 80.5, True),
        ],
    )
    def test_hysteresis_direction_per_comparator(
        self, comparator, threshold, hysteresis, value, cleared
    ):
        assert _has_cleared(value, comparator, threshold, hysteresis) is cleared


# ---------------------------------------------------------------------------
# Targeting
# ---------------------------------------------------------------------------

class TestTargeting:
    def test_untargeted_rule_applies_to_every_asset(self):
        assert applies_to_asset(_rule(), _asset()) is True

    def test_asset_targeted_rule_matches_only_that_asset(self):
        asset = _asset()
        assert applies_to_asset(_rule(asset_id=asset.id), asset) is True
        assert applies_to_asset(_rule(asset_id=uuid4()), asset) is False

    def test_asset_type_and_workcell_targeting(self):
        asset = _asset()
        assert applies_to_asset(_rule(asset_type_id=asset.asset_type_id), asset) is True
        assert applies_to_asset(_rule(workcell_id=asset.workcell_id), asset) is True
        assert applies_to_asset(_rule(workcell_id=uuid4()), asset) is False

    def test_targeting_compares_across_uuid_and_str(self):
        """UUIDString reads back a dashed str on every dialect, but a rule created
        in the same session still holds a UUID object. A naive == would then miss
        and the rule would silently never match its own target."""
        asset = _asset()
        as_str = _rule(asset_id=str(asset.id))
        assert applies_to_asset(as_str, asset) is True

    async def test_evaluate_skips_rules_for_other_metrics(self):
        session, store = _FakeSession(), InMemoryBreachStore()
        asset = _asset()
        pressure_rule = _rule(metric_name="pressure", threshold=1.0)

        out = await evaluate_metric(
            session,
            store,
            organization_id=uuid4(),
            asset=asset,
            metric_name="temperature",
            value=999.0,
            now=1000.0,
            rules=[pressure_rule],
        )
        assert out == []
        assert session.added == []


# ---------------------------------------------------------------------------
# Raised alarm shape
# ---------------------------------------------------------------------------

class TestRaisedAlarm:
    async def test_alarm_carries_provenance_and_tenant(self):
        session, store = _FakeSession(), InMemoryBreachStore()
        rule, asset = _rule(), _asset()
        org = uuid4()

        await _evaluate(session, store, rule, asset, 81.5, now=1000.0, org=org)

        alarm = session.added[0]
        assert alarm.organization_id == org, "raised alarm must be tenant-scoped"
        assert alarm.asset_id == asset.id
        assert alarm.severity == "critical"
        assert alarm.alarm_code == "TEMP_HIGH"
        assert alarm.is_active is True
        assert alarm.is_acknowledged is False
        # Provenance distinguishes a server-evaluated alarm from an edge-emitted
        # one, and records what actually tripped.
        assert alarm.meta_data["source"] == "alarm_rule"
        assert alarm.meta_data["rule_id"] == str(rule.id)
        assert alarm.meta_data["value"] == 81.5
        assert alarm.meta_data["threshold"] == 80.0
        assert alarm.occurred_at.tzinfo is not None, "occurred_at must be aware"

    async def test_message_template_is_rendered(self):
        session, store = _FakeSession(), InMemoryBreachStore()
        rule = _rule(message_template="{metric_name} hit {value} (limit {threshold})")
        await _evaluate(session, store, rule, _asset(), 81.5, now=1000.0)
        assert session.added[0].message == "temperature hit 81.5 (limit 80.0)"

    async def test_malformed_template_still_raises_the_alarm(self):
        """A typo in the wording must not swallow the alarm."""
        session, store = _FakeSession(), InMemoryBreachStore()
        rule = _rule(message_template="{nonexistent_field}")
        await _evaluate(session, store, rule, _asset(), 81.5, now=1000.0)
        assert len(session.added) == 1
        assert "temperature" in session.added[0].message

    async def test_bad_comparator_is_reported_not_raised(self):
        """Evaluation must survive one broken rule — the other rules for this
        reading still need to run."""
        session, store = _FakeSession(), InMemoryBreachStore()
        out = await _evaluate(
            session, store, _rule(comparator="nope"), _asset(), 81.0, now=1000.0
        )
        assert [o.reason for o in out] == ["bad_comparator"]
        assert session.added == []


# ---------------------------------------------------------------------------
# Store contract
# ---------------------------------------------------------------------------

class TestBreachStore:
    async def test_start_is_setdefault_not_overwrite(self):
        store = InMemoryBreachStore()
        await store.start("k", 100.0)
        await store.start("k", 500.0)
        # `now` on the same clock as the recorded start — omitting it would compare
        # a fake timestamp against wall-clock and evict as stale.
        started_at, _ = await store.get("k", 600.0)
        assert started_at == 100.0, "later samples overwrote the window start"

    async def test_mark_fired_preserves_the_window_start(self):
        store = InMemoryBreachStore()
        await store.start("k", 100.0)
        await store.mark_fired("k", 400.0)
        assert await store.get("k", 500.0) == (100.0, 400.0)

    async def test_clear_removes_state(self):
        store = InMemoryBreachStore()
        await store.start("k", 100.0)
        await store.clear("k")
        assert await store.get("k", 200.0) is None

    async def test_state_older_than_the_ttl_is_evicted(self):
        """A window nobody revisited must not linger and cause an instant fire
        weeks later."""
        store = InMemoryBreachStore()
        await store.start("k", 100.0)
        assert await store.get("k", 100.0 + 86_401) is None

    async def test_redis_store_degrades_instead_of_raising(self):
        """A Redis outage must not fail ingestion. Every operation is exercised
        against a client that raises, and none may propagate."""
        from app.services.alarm_rules import RedisBreachStore

        class _Broken:
            async def hgetall(self, *a, **k):
                raise ConnectionError("redis down")

            async def hsetnx(self, *a, **k):
                raise ConnectionError("redis down")

            async def hset(self, *a, **k):
                raise ConnectionError("redis down")

            async def expire(self, *a, **k):
                raise ConnectionError("redis down")

            async def delete(self, *a, **k):
                raise ConnectionError("redis down")

        store = RedisBreachStore("redis://unused", client=_Broken())
        assert await store.get("k") is None
        await store.start("k", 1.0)
        await store.mark_fired("k", 2.0)
        await store.clear("k")

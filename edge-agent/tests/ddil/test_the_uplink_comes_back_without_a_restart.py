"""S4 — an agent that boots into an outage must still recover (FS-756).

THE DEFECT. `_init_kafka_producer` is called once, from `start()`. If the broker is
unreachable at that instant it logs `kafka_producer_failed`, sets `self.kafka_producer =
None`, and returns False. Nothing calls it again, ever. `_backfill_worker` spends the rest
of the process's life evaluating `if self.kafka_producer:` — permanently false — so the
buffer fills correctly, retains correctly, and drains nothing, for hours or days after the
link has come back. Only a restart fixes it.

That is the DDIL case turned inside out. A gateway powering up during an outage is the
ORDINARY way to hit this: a site restoring after a power cut, a vehicle that left coverage
before it came back, a cluster that restarted the agent pod while the broker was rolling.
Every one of those ends with an agent that has been collecting perfectly and can never
deliver.

Graded here rather than by inspection, because "it reconnects" is exactly the kind of claim
that reads as true in the source and is false in the process.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pytest

from opsgrid_agent.main import EdgeAgent
from opsgrid_agent.resilience import ReconnectPolicy
from opsgrid_agent.timesync import ClockSkewEstimator

pytestmark = pytest.mark.ddil


class _Agent:
    """The two attributes and the one method `_uplink_supervisor` actually touches.

    Deliberately not a real `EdgeAgent`: constructing one reads the environment, opens a
    buffer, builds collectors and enrols with a cloud. The supervisor's contract is small
    and this makes the scenario about the contract rather than about the constructor.
    """

    def __init__(self, *, connects_after: int, config=None):
        from opsgrid_agent.main import EdgeAgent

        self._running = True
        self.kafka_producer = None
        self.config = config or {}
        self.attempts = 0
        #: FS-757 gave the supervisor a buffer call — clearing the retry counts a dead link
        #: left behind — so the stand-in grows a buffer. Recorded rather than silently
        #: patched: a stand-in that drifts from the object it stands in for turns a real
        #: change into a test failure that looks like a regression.
        self.retry_resets = 0
        self.buffer = self
        self._connects_after = connects_after
        # The method under test, bound to this stand-in.
        self._uplink_supervisor = EdgeAgent._uplink_supervisor.__get__(self)

    async def reset_retry_counts(self) -> int:
        self.retry_resets += 1
        return 0

    async def _init_kafka_producer(self) -> bool:
        self.attempts += 1
        if self.attempts >= self._connects_after:
            self.kafka_producer = object()
            return True
        return False


async def _run(agent, *, stop_after_sleeps: int):
    """Drive the supervisor with time compressed, then stop it."""
    slept = []
    real_sleep = asyncio.sleep

    async def fake_sleep(delay):
        slept.append(delay)
        if len(slept) >= stop_after_sleeps:
            agent._running = False
        await real_sleep(0)

    with patch("opsgrid_agent.main.asyncio.sleep", fake_sleep):
        await agent._uplink_supervisor()
    return slept


class TestABrokerThatIsDownAtBoot:
    def test_the_uplink_is_retried_rather_than_abandoned(self):
        agent = _Agent(connects_after=4)
        asyncio.run(_run(agent, stop_after_sleeps=20))
        assert agent.attempts >= 4, agent.attempts
        assert agent.kafka_producer is not None, (
            "the supervisor gave up. Before FS-756 the single boot attempt was the only "
            "one there was, and a buffer that never drains is the result."
        )
        assert agent.retry_resets == 1, (
            "the reconnect did not clear the retry counts (FS-757). The rows that failed "
            "against the dead producer stay hidden from the first drain the new one does."
        )

    def test_the_retries_back_off_instead_of_hammering(self):
        """THE BREAKER MUST BE HELD OUT OF THIS (FS-756).

        Written first without the high `failure_threshold`, and it passed while
        `backoff.next_delay()` was replaced by a constant — because after five failures the
        breaker opens and the loop sleeps its 30s cooldown, so `slept` contained growing
        values that the BACKOFF had nothing to do with. A mutation caught it.

        Two instruments producing delays into one list means an assertion about growth
        cannot say which one grew. The threshold is raised so the breaker never opens and
        every delay in the list comes from the backoff.
        """
        agent = _Agent(
            connects_after=1_000,  # never succeeds
            config={'uplink': {'reconnect': {'failure_threshold': 10_000}}},
        )
        slept = asyncio.run(_run(agent, stop_after_sleeps=12))

        policy = ReconnectPolicy()
        assert all(d <= policy.max_delay for d in slept), (
            f"a delay exceeded the backoff cap ({slept}); the breaker is contributing "
            "and this assertion is no longer about the backoff"
        )
        growing = [b for a, b in zip(slept, slept[1:]) if b > a]
        assert len(growing) >= 3, f"the delays barely increase: {slept}"
        assert max(slept) > 4 * min(slept), (
            f"the delays are not doubling ({slept}); this is a fixed sleep wearing a "
            "backoff's name"
        )

    def test_the_breaker_holds_once_the_attempts_keep_failing(self):
        """Not merely that delays grow — that the circuit opens, which is what stops a
        permanently dead broker being dialled at the backoff cap forever."""
        agent = _Agent(connects_after=1_000)
        slept = asyncio.run(_run(agent, stop_after_sleeps=30))

        policy = ReconnectPolicy()
        assert agent.attempts < 30, (
            f"{agent.attempts} attempts across 30 waits — the breaker never opened, so "
            "every wait was followed by another connect"
        )
        assert max(slept) >= policy.initial_cooldown * 0.9, (
            f"the longest wait was {max(slept)}s; the breaker's cooldown is "
            f"{policy.initial_cooldown}s and nothing ever waited for it"
        )

    def test_a_connected_uplink_is_not_reconnected(self):
        """The control case. A supervisor that rebuilt the producer every cycle would pass
        every assertion above and churn the connection in production."""
        agent = _Agent(connects_after=1)
        asyncio.run(_run(agent, stop_after_sleeps=10))
        assert agent.attempts == 1, (
            f"{agent.attempts} connect attempts for a link that came up on the first — the "
            "supervisor is rebuilding a healthy producer"
        )


class TestTheFailureModesTheSupervisorMustSurvive:
    def test_a_raising_init_is_counted_rather_than_killing_the_task(self):
        """`_init_kafka_producer` re-raises when EDGE_REQUIRE_TLS is set and TLS is
        unavailable — deliberate at boot, so a required-TLS agent refuses to start. Letting
        it kill the supervisor post-boot would silently restore the never-reconnects
        behaviour this whole item removes, on the deployments that care most."""
        agent = _Agent(connects_after=1_000)

        async def always_raises():
            agent.attempts += 1
            raise RuntimeError("mTLS material not ready")

        agent._init_kafka_producer = always_raises
        slept = asyncio.run(_run(agent, stop_after_sleeps=8))

        assert agent.attempts >= 3, (
            "the supervisor died on the first exception; the agent is then buffering into "
            "a link that will never be retried"
        )
        assert slept, "no backoff was applied to the raising path"

    def test_it_stops_when_the_agent_stops(self):
        agent = _Agent(connects_after=1_000)
        agent._running = False
        slept = asyncio.run(_run(agent, stop_after_sleeps=5))
        assert agent.attempts == 0 and slept == []


class TestTheTuningIsConfigurable:
    def test_a_site_override_reaches_the_supervisor(self):
        agent = _Agent(
            connects_after=1_000,
            config={'uplink': {'reconnect': {'max_delay': 4.0, 'initial_delay': 2.0}}},
        )
        slept = asyncio.run(_run(agent, stop_after_sleeps=10))
        assert max(d for d in slept if d < 10) <= 4.0, (
            f"delays exceeded the configured max_delay of 4.0: {slept}"
        )

    def test_a_misspelled_setting_is_refused_rather_than_ignored(self):
        from opsgrid_agent.main import _uplink_reconnect_settings

        with patch.dict('os.environ', {'UPLINK_RECONNECT': '{"max_delayy": 4.0}'}):
            settings = _uplink_reconnect_settings()
        with pytest.raises(ValueError, match="unknown reconnect settings"):
            ReconnectPolicy.from_config({'reconnect': settings})

    def test_malformed_json_fails_loudly_at_load(self):
        from opsgrid_agent.main import _uplink_reconnect_settings

        with patch.dict('os.environ', {'UPLINK_RECONNECT': 'not json'}):
            with pytest.raises(ValueError, match="not valid JSON"):
                _uplink_reconnect_settings()

    def test_unset_means_the_shared_defaults(self):
        from opsgrid_agent.main import _uplink_reconnect_settings

        with patch.dict('os.environ', {}, clear=False):
            import os
            os.environ.pop('UPLINK_RECONNECT', None)
            assert _uplink_reconnect_settings() is None
        assert ReconnectPolicy.from_config({'reconnect': None}) == ReconnectPolicy()


class TestAProducerThatExistsAndDeliversNothing:
    """The half a supervisor alone does not cover (FS-756).

    The supervisor rebuilds a producer that is `None`. Nothing sets it to `None` once it
    exists, so a broker that dies AFTER a successful boot leaves an object behind that fails
    every send, while `if self.kafka_producer:` in the backfill loop stays true forever.
    Same outcome as the original defect — a buffer that never drains — reached by a
    different route, and invisible to every assertion above.
    """

    class _BackfillAgent:
        def __init__(self):
            from opsgrid_agent.main import EdgeAgent

            self.kafka_producer = object()
            self.coordinator = type("C", (), {"kafka_producer": None})()
            self._uplink_failure_streak = 0
            self.stopped = 0
            self._recycle_uplink = EdgeAgent._recycle_uplink.__get__(self)

        async def _stop_kafka_producer(self):
            self.stopped += 1

    def test_the_producer_is_discarded_so_the_supervisor_can_rebuild_it(self):
        agent = self._BackfillAgent()
        agent._uplink_failure_streak = 3
        asyncio.run(agent._recycle_uplink())

        assert agent.kafka_producer is None, (
            "the dead producer is still installed; the backfill loop will keep handing it "
            "messages and the supervisor will never see anything to rebuild"
        )
        assert agent.coordinator.kafka_producer is None, (
            "the coordinator kept its own reference to the dead producer"
        )
        assert agent._uplink_failure_streak == 0

    def test_a_stop_that_throws_does_not_prevent_the_discard(self):
        """`stop()` talks to the broker, and the reason we are recycling is that the broker
        is unreachable. If its exception escaped, the one step that matters would be
        skipped and the recycle would silently do nothing."""
        agent = self._BackfillAgent()

        async def stop_raises():
            raise OSError("broker unreachable")

        agent._stop_kafka_producer = stop_raises
        asyncio.run(agent._recycle_uplink())
        assert agent.kafka_producer is None

    def test_the_threshold_is_more_than_one_batch(self):
        """One failed batch is a leader election, not a dead link. Rebuilding on every
        transient would churn the connection exactly when the broker is under stress."""
        from opsgrid_agent.main import UPLINK_DEAD_AFTER_BATCHES

        assert UPLINK_DEAD_AFTER_BATCHES >= 2, UPLINK_DEAD_AFTER_BATCHES

    def test_the_streak_survives_partial_success_but_resets_on_any(self):
        """Driven through the real `_backfill_worker`, not read out of the source.

        The source-grep version of this passed while the reset was disabled, because the
        same statement appears in `__init__` and in `_recycle_uplink`. Grepping for a line
        that exists three times cannot tell you the one that matters still runs.
        """
        agent = _BackfillHarness(fail_batches=2, then_succeed=True)
        asyncio.run(agent.run(cycles=4))

        assert agent.recycled == 0, (
            "the uplink was recycled after two failed batches and one success; the streak "
            "did not reset, so a link that is merely flaky gets its producer torn down"
        )

    def test_three_consecutive_dead_batches_recycle_the_uplink(self):
        agent = _BackfillHarness(fail_batches=99, then_succeed=False)
        asyncio.run(agent.run(cycles=4))
        assert agent.recycled == 1, (
            f"recycled {agent.recycled} times after three fully-failed batches; a producer "
            "that delivers nothing must be handed back to the supervisor"
        )


class _BackfillHarness:
    """Drives the real `_backfill_worker` with the minimum around it (FS-756).

    Everything here is a stand-in EXCEPT the method under test, which is bound from
    `EdgeAgent`. The alternative — grepping `main.py` for the streak statements — passed
    while the reset was disabled, because the same assignment appears in three places.
    """

    def __init__(self, *, fail_batches: int, then_succeed: bool):
        from opsgrid_agent.main import EdgeAgent

        self._running = True
        self.kafka_producer = self
        self.config = {'organization_id': 'org-1'}
        self._uplink_failure_streak = 0
        #: Mirrors the real agent (FS-757). Without it the harness raises AttributeError
        #: inside `_backfill_worker`'s catch-all, which made an S5 mutation "fail" here for
        #: a reason that had nothing to do with what it was testing.
        self._draining = False
        self._backfill_batch = 100
        #: FS-760 gave the backfill loop a clock-quality stamp, which reads `self._skew` and
        #: `self._time_fields`. Bound from the real class rather than stubbed: a stand-in
        #: that diverges from the object it stands in for turns the NEXT real change into a
        #: failure that looks like a regression — which is what happened here, twice.
        self._skew = ClockSkewEstimator()
        self._time_fields = EdgeAgent._time_fields.__get__(self)
        self.recycled = 0
        self._batch = 0
        self._fail_batches = fail_batches
        self._then_succeed = then_succeed
        self.buffer = self
        self._backfill_worker = EdgeAgent._backfill_worker.__get__(self)

    # --- buffer stand-in ---
    async def get_pending_messages(self, batch_size=100):
        from opsgrid_agent.buffer.store_forward import BufferedMessage

        self._batch += 1
        return [
            BufferedMessage(id=self._batch, timestamp_edge="2026-08-18T00:00:00",
                            asset_id="press-01", topic="telemetry",
                            payload='{"vibration": 1.0}', sequence_num=0)
        ]

    async def mark_sent(self, ids):
        return None

    async def increment_retry(self, ids):
        return None

    # --- producer stand-in ---
    async def send(self, topic, value=None, key=None):
        if self._batch <= self._fail_batches:
            raise OSError("broker unreachable")
        if not self._then_succeed:
            raise OSError("broker unreachable")
        return None

    async def _recycle_uplink(self):
        self.recycled += 1
        self._uplink_failure_streak = 0

    async def run(self, *, cycles: int):
        real_sleep = asyncio.sleep
        waits = []

        async def fake_sleep(delay):
            waits.append(delay)
            if len(waits) >= cycles:
                self._running = False
            await real_sleep(0)

        with patch("opsgrid_agent.main.asyncio.sleep", fake_sleep):
            await self._backfill_worker()

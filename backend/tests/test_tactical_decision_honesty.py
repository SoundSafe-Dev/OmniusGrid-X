"""`execute_decision` must not report success for a command that reached no asset.

THE DEFECT. `LocalTacticalEngine.execute_decision` checks maintenance mode, checks the 0.7
confidence floor, then called `_send_command` — whose whole body assembled a dict and
logged `command_queued` at DEBUG, publishing nothing — and unconditionally logged
`tactical_decision_executed` and returned **True**. Its docstring reads "Returns True
if executed, False if blocked."

So the one caller that exists, the inference loop, recorded an executed control action
for an industrial asset that was never actuated, and the training feedback event went
to the cloud describing that decision with no indication it had no effect.

WHY IT IS THE WORST INSTANCE OF THIS CLASS HERE. The two safety gates above it are
real and carefully written — the maintenance check even fails SAFE, under a comment
reading "a broken control command is worse than a skipped one." Everything around the
dispatch is trustworthy, which is exactly what made the dispatch look trustworthy.

It is currently unreachable: `execute_decision` is only called from `_inference_loop`,
and `start()` is absent from `main.py`'s startup list. That is the only reason it has
never mattered, and it is one line from mattering.

These tests pin the honest behaviour so that wiring a real sink is a deliberate change
that must update them, rather than something a silent `return True` already claims.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

from app.services.tactical_engine import LocalTacticalEngine, TacticalDecision


def _decision(confidence: float = 0.95) -> TacticalDecision:
    return TacticalDecision(
        asset_id="asset-1",
        action_type="set_speed",
        parameters={"speed_percent": 80},
        confidence=confidence,
        reasoning="test",
        model_version="v1",
        latency_ms=3.0,
        timestamp=datetime.now(timezone.utc),
    )


async def _execute(decision: TacticalDecision, *, maintenance: bool = False):
    """Run execute_decision with the DB check and the cloud gateway stubbed.

    Returns (result, the payload queued for training).
    """
    engine = LocalTacticalEngine()
    queued = {}

    async def _capture(event_type, payload):
        queued["event_type"] = event_type
        queued["payload"] = payload

    with patch.object(engine, "_is_maintenance_mode", AsyncMock(return_value=maintenance)), \
         patch("app.services.tactical_engine.cloud_gateway.queue_discrete_event", _capture):
        result = await engine.execute_decision(decision)
    return result, queued


class TestAnUndispatchedDecisionIsNotReportedAsExecuted:
    async def test_execute_decision_returns_false_when_nothing_was_sent(self):
        """THE ASSERTION THIS FILE EXISTS FOR. There is no command sink, so no asset
        received anything; True would assert an actuation that did not happen."""
        result, _queued = await _execute(_decision())
        assert result is False, (
            "execute_decision reported success for a command that was never dispatched"
        )

    async def test_the_dispatcher_itself_reports_failure(self):
        engine = LocalTacticalEngine()
        assert await engine._dispatch_command(_decision()) is False

    def test_the_old_lying_name_is_gone(self):
        """`_send_command` sent nothing. If it comes back, so does the claim — and a
        caller awaiting it gets no signal, because it returned None."""
        assert not hasattr(LocalTacticalEngine, "_send_command"), (
            "_send_command is back; it returns no dispatch status, so execute_decision "
            "cannot tell whether the command reached the asset"
        )


class TestTheTrainingFeedbackIsHonest:
    async def test_the_queued_event_records_that_it_was_not_dispatched(self):
        """This event is training feedback. A decision that never reached the asset
        produced no outcome to learn from, and feeding it in as though it actuated
        teaches the model from something that never happened."""
        _result, queued = await _execute(_decision())
        assert queued["event_type"] == "tactical_decision"
        assert queued["payload"]["dispatched"] is False, (
            "the training event does not distinguish a dispatched decision from one "
            "that was computed and dropped"
        )

    async def test_the_decision_is_still_reported_rather_than_swallowed(self):
        """Refusing to dispatch must not make the decision disappear — the model's
        output is still worth recording, it just must not be labelled as actuated."""
        _result, queued = await _execute(_decision())
        assert queued["payload"]["asset_id"] == "asset-1"
        assert queued["payload"]["action_type"] == "set_speed"
        assert queued["payload"]["confidence"] == 0.95


class TestTheSafetyGatesStillShortCircuit:
    """The gates were already correct. The fix must not have moved them, and it must
    not have made a blocked decision look like an undispatched one — they are
    different facts."""

    async def test_maintenance_mode_blocks_before_any_dispatch(self):
        engine = LocalTacticalEngine()
        dispatch = AsyncMock(return_value=True)
        with patch.object(engine, "_is_maintenance_mode", AsyncMock(return_value=True)), \
             patch.object(engine, "_dispatch_command", dispatch):
            assert await engine.execute_decision(_decision()) is False
        dispatch.assert_not_awaited()

    async def test_low_confidence_blocks_before_any_dispatch(self):
        engine = LocalTacticalEngine()
        dispatch = AsyncMock(return_value=True)
        with patch.object(engine, "_is_maintenance_mode", AsyncMock(return_value=False)), \
             patch.object(engine, "_dispatch_command", dispatch):
            assert await engine.execute_decision(_decision(confidence=0.5)) is False
        dispatch.assert_not_awaited()

    async def test_a_real_sink_would_make_it_return_true(self):
        """Guards against the opposite error: hardcoding False would satisfy every
        assertion above while making a genuine dispatch unreportable. When a sink is
        wired, this is the test that says the plumbing works."""
        engine = LocalTacticalEngine()
        with patch.object(engine, "_is_maintenance_mode", AsyncMock(return_value=False)), \
             patch.object(engine, "_dispatch_command", AsyncMock(return_value=True)), \
             patch("app.services.tactical_engine.cloud_gateway.queue_discrete_event",
                   AsyncMock()):
            assert await engine.execute_decision(_decision()) is True

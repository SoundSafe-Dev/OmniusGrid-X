"""A command that expired while the agent was offline must not run (FS-752).

THE SCENARIO, and it is the reason this is ranked above every other DDIL item. The command
consumer runs with `auto_offset_reset="earliest"` on a per-agent consumer group. An agent
that has been offline — a denied link, a flat battery, a site on generator power — reconnects
and replays its whole backlog.

Before this, `_decode_and_validate` checked that `timeout_seconds` was a positive integer and
then **never used it**. Nothing anywhere compared the command's age to anything. So a
`set_speed`, a `pause_job` or an `emergency_stop` issued days earlier, which the backend had
long since marked TIMEOUT and an operator had moved on from, was executed verbatim on
reconnect — and its `completed` ack arrived against a row already in a terminal state.

For a compressor, a valve or a conveyor that is not a stale-data problem. It is a machine
moving because of an instruction nobody currently intends.

THE CLOCK IS PART OF THE CHECK, NOT AN ASSUMPTION BEHIND IT. Freshness is a comparison
against local time, and the gateway that has been offline for a week is precisely the one
whose clock is least trustworthy: no NTP on many of these devices, and `timesync` only
calibrates from cloud responses — never while it matters. So an uncalibrated clock tightens
the limit rather than being ignored. For actuation, the safe reading of "I cannot tell how
old this is" is "do not run it".

WHAT IS ASSERTED, in order of what would hurt:

  1. a stale command does NOT reach the handler — the actuator is never invoked;
  2. the backend is TOLD (an explicit `rejected` ack), because a command that silently
     vanishes is indistinguishable from one still in flight;
  3. a fresh command still runs — otherwise (1) is satisfied by refusing everything;
  4. a future-dated command is refused;
  5. an uncalibrated clock tightens the window;
  6. a command with no timestamp still runs, so a mixed fleet mid-upgrade does not go deaf.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from opsgrid_agent.commands.consumer import CommandConsumer

AGENT_ID = "11111111-1111-1111-1111-111111111111"
ASSET_ID = "22222222-2222-2222-2222-222222222222"
ORGANIZATION_ID = "33333333-3333-3333-3333-333333333333"
COMMAND_ID = "44444444-4444-4444-4444-444444444444"


class _Clock:
    """Stands in for `ClockSkewEstimator`."""

    def __init__(self, calibrated: bool = True, offset_seconds: float = 0.0):
        self.calibrated = calibrated
        self.offset_seconds = offset_seconds


def _consumer(clock=None, **kwargs) -> CommandConsumer:
    consumer = CommandConsumer(
        agent_id=AGENT_ID,
        organization_id=ORGANIZATION_ID,
        asset_ids=[ASSET_ID],
        redpanda_url="localhost:9092",
        clock=clock if clock is not None else _Clock(),
        **kwargs,
    )
    consumer._emit_ack = _record_ack.__get__(consumer)  # type: ignore[attr-defined]
    consumer.emitted = []  # type: ignore[attr-defined]
    return consumer


async def _record_ack(self, ack):
    self.emitted.append(ack)


def _command(age_seconds: float = 0.0, **overrides):
    issued = datetime.now(timezone.utc) - timedelta(seconds=age_seconds)
    payload = {
        "schema_version": 1,
        "message_type": "command",
        "command_id": COMMAND_ID,
        "asset_id": ASSET_ID,
        "organization_id": ORGANIZATION_ID,
        "action_id": "set_speed",
        "parameters": {"speed": 42},
        "timeout_seconds": 30,
        "timestamp": issued.isoformat(),
    }
    payload.update(overrides)
    return payload


def _actuator(calls):
    async def handler(command):
        calls.append(command)
        return {"applied": True}

    return handler


class TestAStaleCommandNeverReachesTheActuator:
    @pytest.mark.asyncio
    async def test_a_day_old_command_is_refused(self):
        """THE ASSERTION THIS FILE EXISTS FOR."""
        calls = []
        consumer = _consumer()
        consumer.register_handler("set_speed", _actuator(calls))

        ack = await consumer.handle_message(_command(age_seconds=86_400))

        assert calls == [], (
            "a command issued 24 hours ago reached the handler — on a physical asset that "
            "is a machine moving because of an instruction nobody currently intends"
        )
        assert ack["status"] == "rejected"
        assert ack["error"] == "command_expired"

    @pytest.mark.asyncio
    async def test_the_backend_is_told(self):
        """A stale command that silently disappears looks exactly like one still in
        flight. The ack is how the backend learns which."""
        consumer = _consumer()
        consumer.register_handler("set_speed", _actuator([]))
        await consumer.handle_message(_command(age_seconds=86_400))
        assert consumer.emitted, "nothing was acked; the backend is left guessing"
        assert consumer.emitted[0]["error"] == "command_expired"
        assert "reason" in consumer.emitted[0]["result"]

    @pytest.mark.asyncio
    async def test_a_stale_command_is_not_dead_lettered(self):
        """It is a well-formed command that simply arrived too late. Dead-lettering it
        would mix a routine timing outcome into the queue reserved for malformed input."""
        consumer = _consumer()
        consumer.register_handler("set_speed", _actuator([]))
        ack = await consumer.handle_message(_command(age_seconds=86_400))
        assert ack is not None and ack["status"] == "rejected"


class TestAFreshCommandStillRuns:
    """Every assertion above is satisfied by a consumer that refuses everything. This is
    the denominator (rule 165)."""

    @pytest.mark.asyncio
    async def test_a_current_command_reaches_the_actuator(self):
        calls = []
        consumer = _consumer()
        consumer.register_handler("set_speed", _actuator(calls))
        ack = await consumer.handle_message(_command(age_seconds=1))
        assert len(calls) == 1, "a fresh command was refused"
        assert ack["status"] == "completed"

    @pytest.mark.asyncio
    async def test_a_command_inside_its_own_timeout_runs(self):
        calls = []
        consumer = _consumer()
        consumer.register_handler("set_speed", _actuator(calls))
        await consumer.handle_message(_command(age_seconds=20, timeout_seconds=30))
        assert len(calls) == 1

    @pytest.mark.asyncio
    async def test_the_senders_timeout_is_what_bounds_it(self):
        """`timeout_seconds` was validated and discarded before FS-752. It is the sender's
        statement of how long the instruction stays meaningful, and now it is honoured."""
        calls = []
        consumer = _consumer()
        consumer.register_handler("set_speed", _actuator(calls))
        await consumer.handle_message(_command(age_seconds=45, timeout_seconds=30))
        assert calls == [], "a command past its own declared timeout was executed"


class TestTheClockIsPartOfTheCheck:
    @pytest.mark.asyncio
    async def test_a_future_dated_command_is_refused(self):
        """Either a clock fault or a forged message. Neither is something to actuate on."""
        calls = []
        consumer = _consumer()
        consumer.register_handler("set_speed", _actuator(calls))
        ack = await consumer.handle_message(_command(age_seconds=-3600))
        assert calls == []
        assert ack["result"]["reason"] == "issued_in_the_future"

    @pytest.mark.asyncio
    async def test_an_uncalibrated_clock_tightens_the_window(self):
        """The gateway offline for a week is exactly the one whose clock is least
        trustworthy — `timesync` only calibrates from cloud responses, so it is never
        calibrated when it matters most. `timeout_seconds` cannot be trusted to bound a
        comparison against a clock we do not trust."""
        calls = []
        consumer = _consumer(
            clock=_Clock(calibrated=False), uncalibrated_clock_ttl_seconds=60
        )
        consumer.register_handler("set_speed", _actuator(calls))
        ack = await consumer.handle_message(
            _command(age_seconds=600, timeout_seconds=86_400)
        )
        assert calls == [], (
            "a 10-minute-old command with a generous sender timeout ran against a clock "
            "that has never been calibrated"
        )
        assert "uncalibrated_clock" in ack["result"]["reason"]

    @pytest.mark.asyncio
    async def test_a_calibrated_clock_honours_the_sender(self):
        calls = []
        consumer = _consumer(
            clock=_Clock(calibrated=True), uncalibrated_clock_ttl_seconds=60
        )
        consumer.register_handler("set_speed", _actuator(calls))
        await consumer.handle_message(_command(age_seconds=600, timeout_seconds=86_400))
        assert len(calls) == 1


class TestAMixedFleetDoesNotGoDeaf:
    @pytest.mark.asyncio
    async def test_a_command_with_no_timestamp_still_runs(self):
        """Every backend at or after the dispatch code stamps one unconditionally, so an
        absent timestamp means a much older sender. Turning a version mismatch into a fleet
        that ignores all commands is a worse failure than the one being fixed."""
        calls = []
        consumer = _consumer()
        consumer.register_handler("set_speed", _actuator(calls))
        payload = _command()
        payload.pop("timestamp")
        await consumer.handle_message(payload)
        assert len(calls) == 1

    @pytest.mark.asyncio
    async def test_strict_deployments_can_require_one(self):
        calls = []
        consumer = _consumer(require_freshness=True)
        consumer.register_handler("set_speed", _actuator(calls))
        payload = _command()
        payload.pop("timestamp")
        ack = await consumer.handle_message(payload)
        assert calls == []
        assert ack["result"]["reason"] == "no_timestamp_and_freshness_required"

    @pytest.mark.asyncio
    async def test_an_unparseable_timestamp_is_refused(self):
        calls = []
        consumer = _consumer()
        consumer.register_handler("set_speed", _actuator(calls))
        ack = await consumer.handle_message(_command(timestamp="not-a-date"))
        assert calls == []
        assert ack["result"]["reason"] == "unparseable_timestamp"


class TestTheOffsetStillCommits:
    @pytest.mark.asyncio
    async def test_a_rejected_command_is_acked_and_remembered(self):
        """A stale command must not poison the partition: it is acked and cached like any
        other outcome, so a redelivery re-emits the same ack instead of re-deciding."""
        consumer = _consumer()
        consumer.register_handler("set_speed", _actuator([]))
        first = await consumer.handle_message(_command(age_seconds=86_400))
        second = await consumer.handle_message(_command(age_seconds=86_400))
        assert first["error"] == "command_expired"
        assert second == first, "the redelivery was re-decided rather than re-acked"

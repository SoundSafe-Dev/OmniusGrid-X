"""S9 — the cloud is up, reachable, and asking the device to send less (FS-878).

EVERY OTHER DDIL SCENARIO DENIES THE LINK. Deny it, flap it, lose packets, throttle its
bandwidth — and the agent's answer is always the same one: hold the data and drain later.
That is the DDIL case, and it was the only case.

FS-866 introduced a different one, and nothing exercised it. The link is **perfect**. The
backend is up and answering heartbeats. It is the PIPELINE BEHIND the backend that cannot
keep up — the ingestion worker is shedding — so the cloud asks the agent to slow down via
`ingest_pressure` on the heartbeat ack.

WHY THAT IS THE INTERESTING CASE. When a link is denied, holding data is obviously right
and the agent has no alternative. When the link is healthy, sending is the *default*, and
every instinct in the drain loop is to keep going. The data the agent would push in that
window is data the cloud has told it it will drop — so pushing is not merely wasteful, it
converts readings that are safe in an encrypted local buffer into readings that are gone.

**The buffer is the better place to keep data the cloud cannot take.** These scenarios
assert that the conservation law still holds while the agent honours that, and — the half
that actually protects the fleet — that every way the signal can be wrong resolves to
sending.
"""
from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from opsgrid_agent.buffer.store_forward import StoreForwardBuffer
from opsgrid_agent.heartbeat import HeartbeatReporter

from .link import FakeUplink, LinkController, conservation, drain

pytestmark = pytest.mark.ddil


def _buffer(directory: str, **kwargs) -> StoreForwardBuffer:
    return StoreForwardBuffer(buffer_path=str(Path(directory) / "buffer.db"), **kwargs)


def _reporter(level: str = "normal") -> HeartbeatReporter:
    reporter = HeartbeatReporter.__new__(HeartbeatReporter)
    reporter.ingest_pressure = level
    return reporter


async def _produce(buffer, count: int, *, asset: str = "press-01") -> int:
    for i in range(count):
        await buffer.store_message({
            "asset_id": asset,
            "topic": f"telemetry.{asset}",
            "metric_name": "spindle_vibration_rms",
            "value": 1.0 + i,
            "sequence_num": i,
        })
    return count


class TestTheSignalArrivesOnAHealthyLink:
    """The premise: this is not a link failure. Everything about the transport works."""

    @pytest.mark.asyncio
    async def test_a_perfect_link_still_carries_a_slow_down(self):
        reporter = _reporter()
        reporter._observe_ingest_pressure(
            {"ok": True, "server_time": "t", "ingest_pressure": "critical"}
        )
        assert reporter.ingest_pressure == "critical", (
            "the agent did not hear the cloud on a link with no faults at all — which is "
            "the only kind of link this signal travels on"
        )

    @pytest.mark.asyncio
    async def test_the_books_balance_while_the_cloud_asks_for_less(self):
        """The conservation law is the whole DDIL contract, and it must hold in this case
        too — a reading held back because the cloud asked is `still_buffered`, not lost.
        """
        with TemporaryDirectory() as directory:
            buffer = _buffer(directory)
            link = LinkController()          # healthy: not denied, no loss, no flap
            uplink = FakeUplink(link)

            produced = await _produce(buffer, 400)

            # The cloud says critical, so the agent holds rather than draining.
            reporter = _reporter()
            reporter._observe_ingest_pressure({"ingest_pressure": "critical"})
            assert reporter.ingest_pressure == "critical"

            ledger = await conservation(buffer, uplink, produced)
            assert ledger["still_buffered"] == produced, (
                f"readings went somewhere other than the buffer while the agent was asked "
                f"to hold them: {ledger}"
            )
            assert ledger["sent"] == 0

    @pytest.mark.asyncio
    async def test_recovery_drains_what_was_held(self):
        """Backpressure that is never lifted is an outage the agent inflicted on itself.
        The signal has to be reversible, and the held data has to leave when it is."""
        with TemporaryDirectory() as directory:
            buffer = _buffer(directory)
            link = LinkController()
            uplink = FakeUplink(link)
            produced = await _produce(buffer, 400)

            reporter = _reporter()
            reporter._observe_ingest_pressure({"ingest_pressure": "critical"})
            reporter._observe_ingest_pressure({"ingest_pressure": "normal"})
            assert reporter.ingest_pressure == "normal"

            await drain(buffer, uplink, batch_size=100, rounds=8)
            ledger = await conservation(buffer, uplink, produced)
            assert ledger["sent"] == produced, (
                f"the pressure was lifted and the backlog did not leave: {ledger}"
            )
            assert ledger["still_buffered"] == 0


class TestEveryWrongSignalKeepsTheDataMoving:
    """The asymmetry that protects the fleet. A denied link is obvious and self-correcting;
    a fleet wrongly told to hold is silent, and stays silent until someone notices ingest
    volume fell — which looks exactly like devices going offline or a quiet shift."""

    @pytest.mark.parametrize(
        "ack",
        [
            {"ok": True, "server_time": "t"},                    # old backend, no field
            {"ingest_pressure": "SLOW_DOWN"},                    # typo upstream
            {"ingest_pressure": None},                           # null
            {"ingest_pressure": 12345},                          # wrong type
            "not a dict at all",                                 # malformed body
        ],
    )
    @pytest.mark.asyncio
    async def test_a_wrong_signal_leaves_the_agent_sending(self, ack):
        reporter = _reporter()
        reporter._observe_ingest_pressure(ack)
        assert reporter.ingest_pressure == "normal"

    @pytest.mark.asyncio
    async def test_a_malformed_ack_does_not_clear_a_real_throttle_either(self):
        """The mirror of the case above, and the one a naive `if level: set()` gets wrong: a
        malformed response is not evidence the cloud recovered, so it must not lift a
        throttle that was legitimately applied."""
        reporter = _reporter()
        reporter._observe_ingest_pressure({"ingest_pressure": "elevated"})
        reporter._observe_ingest_pressure({"ingest_pressure": 12345})
        assert reporter.ingest_pressure == "elevated"

    @pytest.mark.asyncio
    async def test_a_wrongly_throttled_agent_still_delivers_everything(self):
        """The end-to-end version: whatever the signal does, the conservation law holds and
        the data is deliverable once the agent sends. Nothing about backpressure may lose a
        reading — that is the property the whole mechanism exists to protect."""
        with TemporaryDirectory() as directory:
            buffer = _buffer(directory)
            link = LinkController()
            uplink = FakeUplink(link)
            produced = await _produce(buffer, 300)

            reporter = _reporter()
            for ack in ({"ingest_pressure": "nonsense"}, "bad", {"ingest_pressure": None}):
                reporter._observe_ingest_pressure(ack)
            assert reporter.ingest_pressure == "normal"

            await drain(buffer, uplink, batch_size=100, rounds=6)
            ledger = await conservation(buffer, uplink, produced)
            assert ledger["sent"] == produced, ledger

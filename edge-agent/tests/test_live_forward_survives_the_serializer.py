"""The live forward must survive the producer's own serializer (FS-495).

THE DEFECT. `main.py` configures the producer with

    value_serializer=lambda v: json.dumps(v).encode('utf-8')

and hands that same producer to the coordinator (`main.py:259, 270`). The coordinator then
pre-encodes and passes the bytes as the value (`collectors/coordinator.py:334-337`):

    payload = json.dumps(message).encode('utf-8')
    await self.kafka_producer.send(topic, payload)

aiokafka applies the serializer to whatever it is given, so this is
`json.dumps(b'{...}')` → **TypeError: Object of type bytes is not JSON serializable**, on
every message, since the day it was written.

WHY NO TEST SAW IT. `tests/test_edge_agent_integration.py:47-55` defines a `FakeProducer`
whose `send()` appends `value` to a list. It applies no serializer, so it accepts bytes
happily — the double is wrong at exactly the seam that is broken. And
`test_coordinator_roundtrip.py:95` passes `kafka_producer=None`, which skips the path
entirely. **A fake that does not model the contract cannot fail the way the real thing does.**

WHAT IT COSTS. Not data loss: the message is buffered before the forward is attempted, and
the backfill path serialises correctly (`main.py:314`), so everything eventually arrives by
the slow route. What is lost is the immediate path — every message takes the retry road — and
the only signal was `logger.debug` plus a metric (`coordinator.py:302-309`, addressed in
FS-496).

So this file's producer double does the one thing the old one omitted: it applies the same
serializer the real producer is configured with.

THESE DRIVE `_forward_to_kafka` DIRECTLY. The call site is gated off by
`IMMEDIATE_FORWARD_ENABLED` (FS-499) because publishing a second copy needs a topic and a
delivery-marking decision that has not been made. The serialisation contract is a property of
this function whether or not anything calls it today — and asserting it here means the day the
gate opens, it opens onto correct code. The last test below pins the gate itself.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from opsgrid_agent.collectors import coordinator as coordinator_module  # noqa: E402

from tests.test_edge_agent_integration import new_agent, run  # noqa: E402


class SerializingProducer:
    """A producer double that behaves like the configured `AIOKafkaProducer`.

    The real one is built with `value_serializer=lambda v: json.dumps(v).encode('utf-8')`
    (`main.py:259`) and applies it inside `send()`. Modelling that is the entire point: the
    existing `FakeProducer` stores `value` verbatim, which is why a value the real serializer
    cannot accept looked fine for as long as it did.
    """

    def __init__(self) -> None:
        self.sent: list[tuple[str, bytes, str | None]] = []

    async def send(self, topic, value=None, key=None):
        encoded = json.dumps(value).encode("utf-8")  # raises on bytes, exactly as aiokafka does
        self.sent.append((topic, encoded, key))


class LiveForwardSurvivesTheSerializer(unittest.TestCase):
    def test_a_message_reaches_the_producer(self):
        """The assertion the old double could not make."""

        async def scenario():
            agent = new_agent()
            producer = SerializingProducer()
            agent.coordinator.kafka_producer = producer
            await agent.coordinator._forward_to_kafka(
                {
                    "timestamp_edge": "2026-08-06T12:00:00",
                    "asset_id": "a1",
                    "topic": "telemetry",
                    "payload": {"temperature": 41.2},
                }
            )
            return producer.sent

        sent = run(scenario())
        self.assertEqual(
            len(sent),
            1,
            "the live forward produced nothing. Before FS-495 the coordinator pre-encoded "
            "the message and the producer's own serializer then raised on the bytes — "
            "swallowed, so the send simply never happened.",
        )

    def test_the_value_handed_over_is_serializable(self):
        """The direct statement of the defect, independent of the agent wiring.

        A value the configured serializer cannot accept is a message that never leaves,
        whatever else is true about the pipeline.
        """

        async def scenario():
            agent = new_agent()
            captured: list[object] = []

            class Capturing:
                async def send(self, topic, value=None, key=None):
                    captured.append(value)

            agent.coordinator.kafka_producer = Capturing()
            await agent.coordinator._forward_to_kafka(
                {
                    "timestamp_edge": "2026-08-06T12:00:00",
                    "asset_id": "a1",
                    "topic": "telemetry",
                    "payload": {"temperature": 41.2},
                }
            )
            return captured

        captured = run(scenario())
        self.assertEqual(len(captured), 1, "nothing was handed to the producer at all")
        try:
            json.dumps(captured[0])
        except TypeError as exc:  # pragma: no cover - the failure this test exists for
            self.fail(
                f"the coordinator handed the producer a value its own serializer rejects: "
                f"{exc}. `main.py:259` sets value_serializer=json.dumps(...).encode, so the "
                f"value must be a plain object, not pre-encoded bytes."
            )

    def test_the_topic_carries_the_asset(self):
        """Guards the fix from being 'send the raw dict to the wrong topic'."""

        async def scenario():
            agent = new_agent()
            producer = SerializingProducer()
            agent.coordinator.kafka_producer = producer
            await agent.coordinator._forward_to_kafka(
                {
                    "timestamp_edge": "2026-08-06T12:00:00",
                    "asset_id": "press-1",
                    "topic": "telemetry",
                    "payload": {"temperature": 41.2},
                }
            )
            return producer.sent

        sent = run(scenario())
        self.assertTrue(sent, "nothing was sent")
        self.assertIn("press-1", sent[0][0])


class TheGateIsClosedUntilTheDecisionIsMade(unittest.TestCase):
    """FS-499. Re-enabling the immediate forward must be a deliberate act.

    Correcting only the topic would deliver every reading twice, because nothing marks the
    buffered row sent — `mark_sent` is called by the backfill loop alone. Switching this on
    needs the org in the topic, an ack-guaranteed send, and the marking, together.
    """

    def test_the_immediate_forward_is_off(self):
        self.assertFalse(
            coordinator_module.IMMEDIATE_FORWARD_ENABLED,
            "the immediate Kafka forward was re-enabled. Unless the topic now carries the "
            "organization and the buffered row is marked sent, every reading is delivered "
            "twice — or, with the old topic, rejected as invalid_topic_format and dropped "
            "while the backfill copy arrives.",
        )


if __name__ == "__main__":
    unittest.main()

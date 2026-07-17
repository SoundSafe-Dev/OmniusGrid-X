"""End-to-end integration test for the EdgeAgent data path.

Exercises the REAL wiring: coordinator._on_collector_message -> StoreForwardBuffer
-> EdgeAgent._backfill_worker -> (fake) Kafka -> mark_sent, and the failure path
-> increment_retry, and EdgeAgent._cleanup_worker -> dead-letter. This is the
class of regression the store_message bug was.

Importing opsgrid_agent.main pulls the mature mqtt collector (paho + the legacy
omniusgrid_agent.packml import) and the coordinator's legacy omniusgrid_agent
imports. We fake only what's needed so the REAL buffer/backfill/cleanup code runs
without drivers and independent of the pending opsgrid_agent rename.

Run: python -m unittest tests.test_edge_agent_integration   (from edge-agent/)
"""

import asyncio
import os
import sys
import tempfile
import types
import unittest
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Reuse the coordinator's legacy-name shim, then fake main's mqtt import, BEFORE
# importing opsgrid_agent.main.
from tests.test_coordinator_roundtrip import _install_legacy_shims

_install_legacy_shims()
_fake_mqtt = types.ModuleType("opsgrid_agent.collectors.mqtt")
_fake_mqtt.BambuCollector = type("BambuCollector", (), {})
_fake_mqtt.MQTTCollector = type("MQTTCollector", (), {})
sys.modules["opsgrid_agent.collectors.mqtt"] = _fake_mqtt

import opsgrid_agent.main as agent_main  # noqa: E402


def run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class FakeProducer:
    def __init__(self, fail=False):
        self.fail = fail
        self.sent = []

    async def send(self, topic, value=None, key=None):
        if self.fail:
            raise RuntimeError("kafka down")
        self.sent.append((topic, value, key))


def new_agent():
    tmpdir = tempfile.mkdtemp()
    os.environ["BUFFER_PATH"] = os.path.join(tmpdir, "buffer.db")
    os.environ["COLLECTORS"] = "[]"
    return agent_main.EdgeAgent()


async def one_pass(coro_factory):
    """Run a worker for a single iteration, then cancel it during its trailing sleep."""
    task = asyncio.ensure_future(coro_factory())
    await asyncio.sleep(0.3)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


MSG = {
    "timestamp_edge": "2026-07-05T12:00:00",
    "asset_id": "a1",
    "topic": "telemetry",
    "collector_type": "can_bus",
    "payload": {"v": 1},
}


class EdgeAgentIntegrationTest(unittest.TestCase):
    def test_collector_to_buffer_to_backfill_to_sent(self):
        async def scenario():
            agent = new_agent()
            agent.kafka_producer = FakeProducer(fail=False)
            # Seed through the real coordinator path (coordinator kafka is None -> buffers).
            await agent.coordinator._on_collector_message(dict(MSG))
            self.assertEqual((await agent.buffer.get_stats())["total_messages"], 1)

            agent._running = True
            await one_pass(agent._backfill_worker)

            remaining = (await agent.buffer.get_stats())["total_messages"]
            return remaining, len(agent.kafka_producer.sent)

        remaining, sent = run(scenario())
        self.assertEqual(remaining, 0)      # mark_sent removed it
        self.assertEqual(sent, 1)           # forwarded to kafka

    def test_backfill_failure_increments_retry(self):
        async def scenario():
            agent = new_agent()
            agent.kafka_producer = FakeProducer(fail=True)
            await agent.coordinator._on_collector_message(dict(MSG))

            agent._running = True
            await one_pass(agent._backfill_worker)

            pending = await agent.buffer.get_pending_messages()
            return pending

        pending = run(scenario())
        self.assertEqual(len(pending), 1)   # still buffered
        self.assertEqual(pending[0].retry_count, 1)

    def test_cleanup_worker_dead_letters_exhausted(self):
        async def scenario():
            agent = new_agent()
            await agent.buffer.store(datetime(2026, 7, 5, 12, 0, 0), "a1", "telemetry", {"v": 1})
            pending = await agent.buffer.get_pending_messages()
            for _ in range(5):  # exhaust retries (max_retry=5)
                await agent.buffer.increment_retry([pending[0].id])

            agent._running = True
            await one_pass(agent._cleanup_worker)

            return await agent.buffer.get_stats()

        stats = run(scenario())
        self.assertEqual(stats["total_messages"], 0)
        self.assertEqual(stats["dead_lettered"], 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)

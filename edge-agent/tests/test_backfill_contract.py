"""Edge -> backend message contract tests.

Guards the drift where the backfill path dropped packml_state (which the backend
ingestion worker reads at the top level), silently losing PackML state — and thus
backend/historical OEE — for anything sent after a Kafka outage.
"""

import json
import os
import sys
import unittest
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Reuse the integration harness (installs shims + imports opsgrid_agent.main).
from tests.test_edge_agent_integration import new_agent, FakeProducer, one_pass, run

# Keys the backend ingestion worker relies on without a default
# (backend/app/workers/ingestion.py). sequence_num defaults to 0 there, so it is
# only required on the backfill path (asserted separately below).
INGESTION_REQUIRED_KEYS = {"timestamp_edge", "asset_id", "payload"}


class BackfillContractTest(unittest.TestCase):
    def test_live_path_forwards_packml_state_top_level(self):
        async def scenario():
            agent = new_agent()
            fp = FakeProducer(fail=False)
            agent.coordinator.kafka_producer = fp  # enable immediate forward
            await agent.coordinator._on_collector_message({
                "timestamp_edge": "2026-07-05T12:00:00",
                "asset_id": "a1",
                "topic": "telemetry",
                "collector_type": "modbus",
                "packml_state": "Execute",
                "payload": {"temp": 42, "packml_state": "Execute"},
            })
            return fp.sent

        sent = run(scenario())
        self.assertEqual(len(sent), 1)
        # _forward_to_kafka serializes the whole message to bytes.
        _topic, raw, _key = sent[0]
        value = json.loads(raw)
        self.assertEqual(value["packml_state"], "Execute")
        self.assertTrue(INGESTION_REQUIRED_KEYS <= set(value))

    def test_backfill_preserves_packml_state(self):
        async def scenario():
            agent = new_agent()
            agent.kafka_producer = FakeProducer(fail=False)
            # Collectors persist packml_state INSIDE payload (adapter + modbus).
            await agent.buffer.store(
                datetime(2026, 7, 5, 12, 0, 0), "a1", "telemetry",
                {"temp": 42, "packml_state": "Execute", "packml_category": "productive"},
            )
            agent._running = True
            await one_pass(agent._backfill_worker)
            return agent.kafka_producer.sent

        sent = run(scenario())
        self.assertEqual(len(sent), 1)
        _topic, value, _key = sent[0]
        self.assertEqual(value["packml_state"], "Execute")   # reconstructed top-level
        self.assertTrue(value.get("backfilled"))
        self.assertIn("sequence_num", value)                 # backfill carries it
        self.assertTrue(INGESTION_REQUIRED_KEYS <= set(value))

    def test_backfill_without_packml_state_omits_key(self):
        async def scenario():
            agent = new_agent()
            agent.kafka_producer = FakeProducer(fail=False)
            await agent.buffer.store(
                datetime(2026, 7, 5, 12, 0, 0), "a2", "telemetry", {"temp": 42},
            )
            agent._running = True
            await one_pass(agent._backfill_worker)
            return agent.kafka_producer.sent

        sent = run(scenario())
        _topic, value, _key = sent[0]
        self.assertNotIn("packml_state", value)              # not fabricated
        self.assertTrue(INGESTION_REQUIRED_KEYS <= set(value))


if __name__ == "__main__":
    unittest.main(verbosity=2)

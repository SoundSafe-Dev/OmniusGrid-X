"""Tests for the edge local-OEE tracker (analytics/oee_tracker.py)."""

import os
import sys
import unittest
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from prometheus_client import REGISTRY

from opsgrid_agent.analytics import oee_tracker


def msg(asset_id, state, ts, **payload):
    p = {"packml_state": state}
    p.update(payload)
    return {
        "asset_id": asset_id,
        "timestamp_edge": ts.isoformat(),
        "packml_state": state,
        "payload": p,
    }


class OEETrackerTest(unittest.TestCase):
    def setUp(self):
        oee_tracker.reset()

    def test_execute_stopped_execute_sequence(self):
        now = datetime.now()  # LocalOEECalculator uses local now()
        oee_tracker.record(msg("m1", "Execute", now - timedelta(seconds=100)))
        oee_tracker.record(msg("m1", "Stopped", now - timedelta(seconds=40)))  # Execute lasted 60s
        result = oee_tracker.record(
            msg("m1", "Execute", now, total_parts=10, good_parts=9)  # Stopped lasted 40s
        )

        self.assertIsNotNone(result)
        self.assertGreater(result["availability"], 0.0)  # Execute time counted
        self.assertEqual(result["quality"], 90.0)         # 9/10

        # Gauge published for the asset.
        self.assertEqual(
            REGISTRY.get_sample_value("edge_oee_quality", {"asset_id": "m1"}), 90.0
        )

    def test_message_without_packml_state_is_noop(self):
        result = oee_tracker.record(
            {"asset_id": "m2", "timestamp_edge": datetime.utcnow().isoformat(), "payload": {"v": 1}}
        )
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main(verbosity=2)

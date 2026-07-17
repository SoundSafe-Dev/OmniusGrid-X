"""Tests for the edge anomaly tracker (analytics/anomaly_tracker.py)."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from prometheus_client import REGISTRY

from opsgrid_agent.analytics import anomaly_tracker


def payload_msg(asset_id, **payload):
    return {"asset_id": asset_id, "payload": payload}


class AnomalyTrackerTest(unittest.TestCase):
    def setUp(self):
        anomaly_tracker.reset()

    def test_detects_outlier_after_warmup(self):
        # Need >= 20 samples before detection kicks in.
        for _ in range(25):
            self.assertEqual(anomaly_tracker.record(payload_msg("m1", temp=10.0)), [])
        found = anomaly_tracker.record(payload_msg("m1", temp=100.0))
        self.assertTrue(any(a["metric_name"] == "temp" for a in found))

        z = REGISTRY.get_sample_value("edge_anomaly_z_score", {"asset_id": "m1", "metric": "temp"})
        self.assertGreater(z, 3.0)

    def test_stable_series_has_no_anomaly(self):
        found = []
        for i in range(30):
            found += anomaly_tracker.record(payload_msg("m2", temp=10.0 + (i % 3) * 0.1))
        self.assertEqual(found, [])

    def test_skips_non_numeric_and_packml_fields(self):
        # packml_* + string fields are ignored; no crash, no metrics.
        r = anomaly_tracker.record(payload_msg("m3", packml_state="Execute", label="foo"))
        self.assertEqual(r, [])

    def test_handles_modbus_nested_telemetry(self):
        for _ in range(25):
            anomaly_tracker.record({"asset_id": "m4", "payload": {"telemetry": {"rpm": 1000.0}}})
        found = anomaly_tracker.record({"asset_id": "m4", "payload": {"telemetry": {"rpm": 9000.0}}})
        self.assertTrue(any(a["metric_name"] == "rpm" for a in found))


if __name__ == "__main__":
    unittest.main(verbosity=2)

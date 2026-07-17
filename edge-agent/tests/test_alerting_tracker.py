"""Tests for the edge alerting tracker (analytics/alerting_tracker.py)."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from prometheus_client import REGISTRY

from opsgrid_agent.analytics import alerting_tracker


def rule(**over):
    r = {
        "rule_id": "hot",
        "metric_name": "temp",
        "condition": ">",
        "threshold": 80,
        "severity": "critical",
        "message_template": "temp {value} > {threshold}",
    }
    r.update(over)
    return r


class AlertingTrackerTest(unittest.TestCase):
    def setUp(self):
        alerting_tracker.reset()

    def test_rule_fires_and_increments_counter(self):
        alerting_tracker.configure("m1", [rule()])
        labels = {"asset_id": "m1", "rule_id": "hot", "severity": "critical"}
        before = REGISTRY.get_sample_value("edge_alert_triggered_total", labels) or 0.0

        fired = alerting_tracker.record({"asset_id": "m1", "payload": {"temp": 90}})

        self.assertEqual(len(fired), 1)
        self.assertEqual(fired[0]["rule_id"], "hot")
        after = REGISTRY.get_sample_value("edge_alert_triggered_total", labels)
        self.assertEqual(after, before + 1)

    def test_below_threshold_does_not_fire(self):
        alerting_tracker.configure("m2", [rule(severity="warning")])
        self.assertEqual(alerting_tracker.record({"asset_id": "m2", "payload": {"temp": 50}}), [])

    def test_unconfigured_asset_is_noop(self):
        self.assertEqual(
            alerting_tracker.record({"asset_id": "nope", "payload": {"temp": 9999}}), []
        )

    def test_cooldown_suppresses_second_fire(self):
        alerting_tracker.configure("m3", [rule(severity="warning", cooldown_seconds=300)])
        first = alerting_tracker.record({"asset_id": "m3", "payload": {"temp": 90}})
        second = alerting_tracker.record({"asset_id": "m3", "payload": {"temp": 95}})
        self.assertEqual(len(first), 1)
        self.assertEqual(len(second), 0)  # within cooldown

    def test_invalid_rule_is_skipped(self):
        # Missing threshold -> rule dropped, no crash.
        alerting_tracker.configure("m4", [{"rule_id": "bad", "metric_name": "temp"}])
        self.assertEqual(alerting_tracker.record({"asset_id": "m4", "payload": {"temp": 9999}}), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)

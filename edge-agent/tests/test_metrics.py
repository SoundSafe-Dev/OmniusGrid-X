"""Unit tests for edge-agent Prometheus metrics helpers."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from prometheus_client import REGISTRY, generate_latest

from opsgrid_agent import metrics


class MetricsTest(unittest.TestCase):
    def test_record_message_increments_counter_and_age(self):
        labels = {"asset_id": "metrics-test", "collector_type": "can_bus"}
        before = REGISTRY.get_sample_value("edge_collector_messages_total", labels) or 0.0

        metrics.record_message("metrics-test", "can_bus", age_seconds=1.5)

        after = REGISTRY.get_sample_value("edge_collector_messages_total", labels)
        self.assertEqual(after, before + 1)

        age_count = REGISTRY.get_sample_value(
            "edge_collector_message_age_seconds_count", {"collector_type": "can_bus"}
        )
        self.assertGreaterEqual(age_count, 1)

    def test_record_error_increments_counter(self):
        labels = {"asset_id": "metrics-test", "collector_type": "profinet"}
        before = REGISTRY.get_sample_value("edge_collector_errors_total", labels) or 0.0
        metrics.record_error("metrics-test", "profinet")
        after = REGISTRY.get_sample_value("edge_collector_errors_total", labels)
        self.assertEqual(after, before + 1)

    def test_set_connection_state(self):
        labels = {"asset_id": "metrics-test", "collector_type": "bacnet"}
        metrics.set_connection_state("metrics-test", "bacnet", up=True)
        self.assertEqual(
            REGISTRY.get_sample_value("edge_collector_connection_state", labels), 1.0
        )
        metrics.set_connection_state("metrics-test", "bacnet", up=False)
        self.assertEqual(
            REGISTRY.get_sample_value("edge_collector_connection_state", labels), 0.0
        )

    def test_poll_failure_and_recovery_update_bounded_metrics(self):
        labels = {"asset_id": "poll-metrics-test", "collector_type": "http_rest"}
        failure_labels = {**labels, "failure_class": "transport"}
        failure_before = (
            REGISTRY.get_sample_value(
                "edge_collector_poll_failures_total", failure_labels
            )
            or 0.0
        )
        recovery_before = (
            REGISTRY.get_sample_value(
                "edge_collector_poll_recoveries_total", labels
            )
            or 0.0
        )

        metrics.record_poll_failure(
            "poll-metrics-test", "http_rest", "transport", 3
        )

        self.assertEqual(
            REGISTRY.get_sample_value(
                "edge_collector_poll_failures_total", failure_labels
            ),
            failure_before + 1,
        )
        self.assertEqual(
            REGISTRY.get_sample_value(
                "edge_collector_poll_consecutive_failures", labels
            ),
            3.0,
        )
        self.assertEqual(
            REGISTRY.get_sample_value("edge_collector_connection_state", labels),
            0.0,
        )

        metrics.record_poll_success(
            "poll-metrics-test", "http_rest", recovered=True
        )

        self.assertEqual(
            REGISTRY.get_sample_value(
                "edge_collector_poll_recoveries_total", labels
            ),
            recovery_before + 1,
        )
        self.assertEqual(
            REGISTRY.get_sample_value(
                "edge_collector_poll_consecutive_failures", labels
            ),
            0.0,
        )
        self.assertEqual(
            REGISTRY.get_sample_value("edge_collector_connection_state", labels),
            1.0,
        )

    def test_unknown_poll_failure_class_is_folded_into_unexpected(self):
        asset_id = "bounded-poll-class-test"
        bounded = {
            "asset_id": asset_id,
            "collector_type": "http_rest",
            "failure_class": "unexpected",
        }
        before = (
            REGISTRY.get_sample_value(
                "edge_collector_poll_failures_total", bounded
            )
            or 0.0
        )

        metrics.record_poll_failure(asset_id, "http_rest", "secret-and-unbounded", 1)

        self.assertEqual(
            REGISTRY.get_sample_value(
                "edge_collector_poll_failures_total", bounded
            ),
            before + 1,
        )
        self.assertIsNone(
            REGISTRY.get_sample_value(
                "edge_collector_poll_failures_total",
                {
                    "asset_id": asset_id,
                    "collector_type": "http_rest",
                    "failure_class": "secret-and-unbounded",
                },
            )
        )

    def test_metrics_are_exposed_in_scrape_output(self):
        metrics.record_message("scrape-test", "http_rest")
        text = generate_latest().decode()
        self.assertIn("edge_collector_messages_total", text)
        self.assertIn('collector_type="http_rest"', text)


if __name__ == "__main__":
    unittest.main(verbosity=2)

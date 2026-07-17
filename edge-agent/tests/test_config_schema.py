"""Unit tests for edge-agent collector config validation (opsgrid_agent.config_schema)."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pydantic import ValidationError

from opsgrid_agent.config_schema import (
    AgentConfig,
    CollectorEntry,
    PackMLConfig,
    validate_entries,
)


class CollectorEntryTest(unittest.TestCase):
    def test_accepts_collector_type_field_name(self):
        e = CollectorEntry(asset_id="a1", collector_type="can_bus", config={"channel": "can0"})
        self.assertEqual(e.collector_type, "can_bus")

    def test_accepts_type_alias(self):
        # The env COLLECTORS JSON uses `type`.
        e = CollectorEntry.model_validate({"asset_id": "a1", "type": "modbus", "config": {}})
        self.assertEqual(e.collector_type, "modbus")

    def test_serializes_as_type_for_initializer(self):
        # EdgeAgent._initialize_collectors reads `type`.
        dumped = CollectorEntry(asset_id="a1", collector_type="http_rest").model_dump(by_alias=True)
        self.assertEqual(dumped["type"], "http_rest")
        self.assertIn("asset_id", dumped)
        self.assertIn("config", dumped)

    def test_rejects_unknown_type(self):
        with self.assertRaises(ValidationError):
            CollectorEntry(asset_id="a1", collector_type="carrier_pigeon")

    def test_rejects_missing_asset_id(self):
        with self.assertRaises(ValidationError):
            CollectorEntry.model_validate({"type": "modbus"})

    def test_enabled_defaults_true(self):
        self.assertTrue(CollectorEntry(asset_id="a1", collector_type="mqtt").enabled)


class PackMLConfigTest(unittest.TestCase):
    def test_parses_nested_packml_block(self):
        entry = CollectorEntry(
            asset_id="plc1",
            collector_type="ethernet_ip",
            config={"ip_address": "10.0.0.1", "packml": {"asset_type": "industrial_plc", "state_key": "state"}},
        )
        pm = entry.packml()
        self.assertIsInstance(pm, PackMLConfig)
        self.assertEqual(pm.asset_type, "industrial_plc")
        self.assertEqual(pm.state_key, "state")

    def test_no_packml_returns_none(self):
        entry = CollectorEntry(asset_id="plc1", collector_type="ethernet_ip", config={})
        self.assertIsNone(entry.packml())


class ValidateEntriesTest(unittest.TestCase):
    def test_agent_config_and_validate_entries(self):
        raw = [
            {"asset_id": "a1", "collector_type": "can_bus", "config": {"channel": "can0"}},
            {"asset_id": "a2", "type": "modbus", "config": {}},
        ]
        cfg = AgentConfig(collectors=raw)
        self.assertEqual(len(cfg.collectors), 2)

        normalized = validate_entries(raw)
        self.assertEqual({e["type"] for e in normalized}, {"can_bus", "modbus"})


if __name__ == "__main__":
    unittest.main(verbosity=2)

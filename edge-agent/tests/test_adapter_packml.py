"""Tests for optional PackML state mapping in CoordinatorCollectorAdapter."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from opsgrid_agent.collectors.adapter import coordinator_adapter
from opsgrid_agent.collectors.base import BaseCollector


class _FakeInner(BaseCollector):
    """Minimal BaseCollector; the adapter only needs add_data_handler + lifecycle."""

    async def start(self):
        await super().start()

    async def stop(self):
        await super().stop()


def make_adapter(**config):
    Adapter = coordinator_adapter(_FakeInner)
    return Adapter(on_message_callback=None, **config)


class AdapterPackMLTest(unittest.TestCase):
    PACKML = {"asset_type": "generic", "state_key": "state",
              "mappings": {"1": "Execute", "0": "Stopped"}}

    def test_maps_state_to_packml_and_mirrors_modbus_shape(self):
        adapter = make_adapter(asset_id="plc1", packml=self.PACKML)
        message = {"asset_id": "plc1", "payload": {"state": "1", "line_speed": 42}}

        adapter._apply_packml(message)

        # Top-level + in-payload, matching modbus_collector's emitted shape.
        self.assertEqual(message["packml_state"], "Execute")
        self.assertEqual(message["payload"]["packml_state"], "Execute")
        self.assertEqual(message["payload"]["packml_category"], "productive")
        self.assertEqual(message["payload"]["line_speed"], 42)  # untouched

    def test_stopped_state_is_availability_loss(self):
        adapter = make_adapter(asset_id="plc1", packml=self.PACKML)
        message = {"payload": {"state": "0"}}
        adapter._apply_packml(message)
        self.assertEqual(message["payload"]["packml_state"], "Stopped")
        self.assertEqual(message["payload"]["packml_category"], "availability_loss")

    def test_no_packml_config_is_noop(self):
        adapter = make_adapter(asset_id="plc1")  # no packml block
        message = {"payload": {"state": "1"}}
        adapter._apply_packml(message)
        self.assertNotIn("packml_state", message)
        self.assertNotIn("packml_state", message["payload"])

    def test_missing_state_field_is_noop(self):
        adapter = make_adapter(asset_id="plc1", packml=self.PACKML)
        message = {"payload": {"temperature": 20.0}}  # no `state` key
        adapter._apply_packml(message)
        self.assertNotIn("packml_state", message)


if __name__ == "__main__":
    unittest.main(verbosity=2)

"""Regression test: coordinator -> store-and-forward buffer round trip.

Guards the bug where `UnifiedCollectorCoordinator._on_collector_message` called a
non-existent `buffer.store_message(...)`, so every collector reading raised inside
the handler's `except` and nothing was ever buffered.

The coordinator module still carries legacy `omniusgrid_agent.*` absolute imports
(the `opsgrid_agent` rename is Hridyansh's `package-renaming-fix` lane). To exercise
the REAL handler against a REAL StoreForwardBuffer regardless of that rename, we:
  1. try importing the coordinator directly (works post-rename / with drivers), and
  2. if that fails, install lightweight sys.modules shims for the legacy names
     (real buffer, stub mature collectors) and retry.

Run: python -m unittest tests.test_coordinator_roundtrip   (from edge-agent/)
"""

import asyncio
import json
import os
import sys
import tempfile
import types
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _install_legacy_shims():
    """Map the coordinator's legacy `omniusgrid_agent.*` imports.

    Real StoreForwardBuffer (so the round trip is genuine); stub classes for the
    mature collectors (so importing the coordinator needs no MQTT/OPC-UA/Modbus
    driver libs). The new collectors + adapter are imported relatively by the
    coordinator and load for real.
    """
    import opsgrid_agent.buffer.store_forward as real_store_forward

    def pkg(name):
        m = types.ModuleType(name)
        m.__path__ = []  # mark as package
        return m

    sys.modules.setdefault("omniusgrid_agent", pkg("omniusgrid_agent"))
    sys.modules.setdefault("omniusgrid_agent.collectors", pkg("omniusgrid_agent.collectors"))
    sys.modules.setdefault("omniusgrid_agent.buffer", pkg("omniusgrid_agent.buffer"))
    # Real buffer.
    sys.modules["omniusgrid_agent.buffer.store_forward"] = real_store_forward

    # Stub mature collector modules with the symbols the coordinator imports.
    stubs = {
        "omniusgrid_agent.collectors.mqtt": ["BambuCollector", "MQTTCollector"],
        "omniusgrid_agent.collectors.screen_scraper": ["QidiCollector", "SovolCollector"],
        "omniusgrid_agent.collectors.file_watcher": ["OrcaSlicerCollector"],
        "omniusgrid_agent.collectors.opcua_collector": ["OPCUACollector"],
        "omniusgrid_agent.collectors.modbus_collector": ["ModbusCollector"],
    }
    for mod_name, symbols in stubs.items():
        mod = types.ModuleType(mod_name)
        for sym in symbols:
            setattr(mod, sym, type(sym, (), {}))
        sys.modules[mod_name] = mod


def import_coordinator():
    sys.modules.pop("opsgrid_agent.collectors.coordinator", None)
    try:
        import opsgrid_agent.collectors.coordinator as coord
        return coord
    except (ImportError, ModuleNotFoundError):
        sys.modules.pop("opsgrid_agent.collectors.coordinator", None)
        _install_legacy_shims()
        import opsgrid_agent.collectors.coordinator as coord
        return coord


class CoordinatorBufferRoundTripTest(unittest.TestCase):
    def test_collector_message_is_persisted_to_buffer(self):
        coord = import_coordinator()
        from opsgrid_agent.buffer.store_forward import StoreForwardBuffer

        tmpdir = tempfile.mkdtemp()
        buffer = StoreForwardBuffer(
            buffer_path=os.path.join(tmpdir, "buffer.db"),
            retention_hours=24,
        )
        coordinator = coord.UnifiedCollectorCoordinator(
            buffer=buffer, kafka_producer=None
        )

        # A canonical envelope as emitted by every new collector.
        message = {
            "timestamp_edge": "2026-07-05T12:00:00",
            "asset_id": "veh-1",
            "topic": "telemetry",
            "collector_type": "can_bus",
            "payload": {"can_id": "0x0A1", "value": 5},
        }

        run(coordinator._on_collector_message(message))

        stats = run(buffer.get_stats())
        self.assertEqual(stats["total_messages"], 1)

        pending = run(buffer.get_pending_messages())
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0].asset_id, "veh-1")
        self.assertEqual(pending[0].topic, "telemetry")
        self.assertEqual(json.loads(pending[0].payload)["value"], 5)


if __name__ == "__main__":
    unittest.main(verbosity=2)

"""Unit tests for the industrial-protocol collectors.

These tests inject fake driver modules (pylogix, snap7, BAC0, can) into
``sys.modules`` *before* importing the collectors, so they exercise the real
collector logic — connect, poll, decode, normalize, emit — without any driver
libraries installed or any hardware present.

Run with: python -m unittest edge-agent/tests/test_industrial_collectors.py
(from the edge-agent directory, or with edge-agent on sys.path).
"""

import asyncio
import os
import sys
import types
import unittest

# Ensure the package root (edge-agent/) is importable.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


# --------------------------------------------------------------------------- #
# Fake drivers
# --------------------------------------------------------------------------- #
def install_fake_pylogix(read_results):
    mod = types.ModuleType("pylogix")

    class FakePLC:
        def __init__(self):
            self.IPAddress = None
            self.ProcessorSlot = None
            self.Port = None
            self.closed = False

        def Read(self, tags):
            return read_results

        def Close(self):
            self.closed = True

    mod.PLC = FakePLC
    sys.modules["pylogix"] = mod
    return mod


def install_fake_snap7(db_bytes):
    mod = types.ModuleType("snap7")
    client_mod = types.ModuleType("snap7.client")
    util_mod = types.ModuleType("snap7.util")

    class FakeClient:
        def __init__(self):
            self.connected = False

        def connect(self, ip, rack, slot):
            self.connected = True

        def db_read(self, number, start, size):
            return bytearray(db_bytes[:size])

        def disconnect(self):
            self.connected = False

    client_mod.Client = FakeClient
    util_mod.get_real = lambda data, off: float(int.from_bytes(data[off:off + 4], "big"))
    util_mod.get_int = lambda data, off: int.from_bytes(data[off:off + 2], "big")
    util_mod.get_dint = lambda data, off: int.from_bytes(data[off:off + 4], "big")
    util_mod.get_word = lambda data, off: int.from_bytes(data[off:off + 2], "big")
    util_mod.get_dword = lambda data, off: int.from_bytes(data[off:off + 4], "big")
    util_mod.get_bool = lambda data, off, bit: bool(data[off] & (1 << bit))

    mod.client = client_mod
    mod.util = util_mod
    sys.modules["snap7"] = mod
    sys.modules["snap7.client"] = client_mod
    sys.modules["snap7.util"] = util_mod
    return mod


def install_fake_bac0(values_by_request):
    mod = types.ModuleType("BAC0")

    class FakeApp:
        def __init__(self):
            self.disconnected = False

        def read(self, request):
            return values_by_request.get(request)

        def disconnect(self):
            self.disconnected = True

    mod.lite = lambda *a, **k: FakeApp()
    sys.modules["BAC0"] = mod
    return mod


def install_fake_can(frames):
    mod = types.ModuleType("can")

    class FakeMessage:
        def __init__(self, arbitration_id, data, timestamp=0.0, is_extended_id=False):
            self.arbitration_id = arbitration_id
            self.data = data
            self.dlc = len(data)
            self.timestamp = timestamp
            self.is_extended_id = is_extended_id

    class FakeBus:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self._frames = list(frames)
            self.shut = False

        def recv(self, timeout=None):
            if self._frames:
                return self._frames.pop(0)
            return None

        def shutdown(self):
            self.shut = True

    mod.Message = FakeMessage
    mod.Bus = FakeBus
    sys.modules["can"] = mod
    return mod, FakeMessage


def fresh_import(module_name):
    """Import (or re-import) a collector module after fakes are installed."""
    for name in list(sys.modules):
        if name.startswith("opsgrid_agent.collectors." + module_name):
            del sys.modules[name]
    return __import__(
        "opsgrid_agent.collectors." + module_name, fromlist=["*"]
    )


# --------------------------------------------------------------------------- #
# Tests
# --------------------------------------------------------------------------- #
class EthernetIPTest(unittest.TestCase):
    def test_reads_and_emits_successful_tags(self):
        resp_ok = types.SimpleNamespace(TagName="Program:MainProgram.Temp", Value=72.5, Status="Success")
        resp_bad = types.SimpleNamespace(TagName="BadTag", Value=None, Status="Path segment error")
        install_fake_pylogix([resp_ok, resp_bad])
        mod = fresh_import("ethernet_ip")

        collector = mod.EthernetIPCollector({
            "asset_id": "plc-1",
            "ip_address": "10.0.0.10",
            "tags": ["Program:MainProgram.Temp", "BadTag"],
        })
        emitted = []
        collector.add_data_handler(lambda d: emitted.append(d))

        run(collector._collect())

        self.assertEqual(len(emitted), 1)
        payload = emitted[0]["payload"]
        self.assertEqual(payload["program_mainprogram_temp"], 72.5)
        self.assertNotIn("badtag", payload)
        self.assertEqual(emitted[0]["collector_type"], "ethernet_ip")

    def test_start_without_driver_sets_not_running(self):
        # Remove the fake so the import falls back to unavailable.
        sys.modules.pop("pylogix", None)
        mod = fresh_import("ethernet_ip")
        mod._PYLOGIX_AVAILABLE = False
        collector = mod.EthernetIPCollector({"asset_id": "x", "ip_address": "1.1.1.1"})
        run(collector.start())
        self.assertFalse(collector.running)


class ProfinetTest(unittest.TestCase):
    def test_decodes_typed_fields(self):
        # 12 bytes: real@0 = 1000, dint@4 = 42, bool@8 bit0 = 1
        data = bytearray(12)
        data[0:4] = (1000).to_bytes(4, "big")
        data[4:8] = (42).to_bytes(4, "big")
        data[8] = 0b00000001
        install_fake_snap7(bytes(data))
        mod = fresh_import("profinet")

        collector = mod.ProfinetCollector({
            "asset_id": "s7-1",
            "ip_address": "10.0.0.20",
            "db_blocks": [{
                "number": 1, "start": 0, "size": 12,
                "fields": [
                    {"name": "temp", "offset": 0, "type": "real"},
                    {"name": "count", "offset": 4, "type": "dint"},
                    {"name": "running", "offset": 8, "type": "bool", "bit": 0},
                ],
            }],
        })
        emitted = []
        collector.add_data_handler(lambda d: emitted.append(d))

        run(collector._collect())

        self.assertEqual(len(emitted), 1)
        payload = emitted[0]["payload"]
        self.assertEqual(payload["db1_temp"], 1000.0)
        self.assertEqual(payload["db1_count"], 42)
        self.assertTrue(payload["db1_running"])

    def test_default_extraction_without_fields(self):
        install_fake_snap7((123).to_bytes(4, "big"))
        mod = fresh_import("profinet")
        collector = mod.ProfinetCollector({
            "asset_id": "s7-2", "ip_address": "10.0.0.21",
            "db_blocks": [{"number": 5, "start": 0, "size": 4}],
        })
        emitted = []
        collector.add_data_handler(lambda d: emitted.append(d))
        run(collector._collect())
        self.assertEqual(emitted[0]["payload"]["db5_value"], 123)


class BACnetTest(unittest.TestCase):
    def test_reads_objects(self):
        install_fake_bac0({
            "10.0.0.30 analogInput 1 presentValue": 21.4,
            "10.0.0.30 binaryInput 2 presentValue": 1,
        })
        mod = fresh_import("bacnet")
        collector = mod.BACnetCollector({
            "asset_id": "ahu-1",
            "ip_address": "10.0.0.30",
            "objects": [
                {"name": "Zone-Temp", "object_type": "analogInput", "object_instance": 1},
                {"name": "Fan Status", "object_type": "binaryInput", "object_instance": 2},
            ],
        })
        emitted = []
        collector.add_data_handler(lambda d: emitted.append(d))
        run(collector._collect())

        payload = emitted[0]["payload"]
        self.assertEqual(payload["zone_temp"], 21.4)
        self.assertEqual(payload["fan_status"], 1)


class CANBusTest(unittest.TestCase):
    def test_decodes_frames(self):
        _, FakeMessage = install_fake_can([])
        frames = [FakeMessage(0x123, bytes([1, 0, 0, 0, 9, 9, 9, 9]), timestamp=1000.0)]
        install_fake_can(frames)
        mod = fresh_import("can_bus")
        collector = mod.CANBusCollector({
            "asset_id": "veh-1", "channel": "vcan0", "batch_size": 5,
        })
        emitted = []
        collector.add_data_handler(lambda d: emitted.append(d))
        run(collector._collect())

        self.assertEqual(len(emitted), 1)
        payload = emitted[0]["payload"]
        self.assertEqual(payload["can_id"], "0x123")
        self.assertEqual(payload["dlc"], 8)
        self.assertEqual(payload["byte_0"], 1)
        self.assertEqual(payload["value"], 1)  # little-endian 0x00000001


class LifecycleTest(unittest.TestCase):
    def test_base_start_stop_toggles_running(self):
        install_fake_can([])
        mod = fresh_import("can_bus")
        collector = mod.CANBusCollector({"asset_id": "veh-2", "channel": "vcan0"})

        async def scenario():
            await collector.start()
            self.assertTrue(collector.running)
            await collector.stop()
            self.assertFalse(collector.running)

        # start() and stop() must share one event loop (the poll task is bound to it).
        run(scenario())


if __name__ == "__main__":
    unittest.main(verbosity=2)

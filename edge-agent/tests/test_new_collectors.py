"""Tests for the SNMP, Sparkplug B, and DNP3 collectors.

Drivers are faked via sys.modules (pattern from test_industrial_collectors.py) so
these run without pysnmp / paho / tahu / dnp3-python and with no hardware.
"""

import asyncio
import os
import sys
import types
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def fresh_import(module_name):
    full = "opsgrid_agent.collectors." + module_name
    sys.modules.pop(full, None)
    return __import__(full, fromlist=["*"])


# --------------------------------------------------------------------------- #
# Fakes
# --------------------------------------------------------------------------- #
def install_fake_pysnmp(value=42):
    hl = types.ModuleType("pysnmp.hlapi")
    for sym in ("SnmpEngine", "CommunityData", "UdpTransportTarget",
                "ContextData", "ObjectType", "ObjectIdentity"):
        setattr(hl, sym, lambda *a, **k: None)
    hl.getCmd = lambda *a, **k: iter([(None, 0, 0, [("1.3.6.1.2.1", value)])])
    pkg = types.ModuleType("pysnmp")
    pkg.hlapi = hl
    sys.modules["pysnmp"] = pkg
    sys.modules["pysnmp.hlapi"] = hl


def install_fake_dnp3():
    pkg = types.ModuleType("dnp3_python")
    station = types.ModuleType("dnp3_python.dnp3station")
    master_new = types.ModuleType("dnp3_python.dnp3station.master_new")

    class FakeMaster:
        def __init__(self, **kwargs):
            self.soe_handler = types.SimpleNamespace(
                gv_index_value_nested_dict={
                    "AnalogInput": {0: {"t0": 12.5}},
                    "BinaryInput": {1: {"t0": True}},
                }
            )

        def start(self):
            pass

        def shutdown(self):
            pass

    master_new.MyMasterNew = FakeMaster
    station.master_new = master_new
    pkg.dnp3station = station
    sys.modules["dnp3_python"] = pkg
    sys.modules["dnp3_python.dnp3station"] = station
    sys.modules["dnp3_python.dnp3station.master_new"] = master_new


def install_fake_sparkplug_pb(metrics):
    mod = types.ModuleType("sparkplug_b_pb2")

    class FakeMetric:
        def __init__(self, name, value):
            self.name = name
            self.double_value = value

        def WhichOneof(self, _):
            return "double_value"

    class FakePayload:
        def __init__(self):
            self.metrics = [FakeMetric(n, v) for n, v in metrics]

        def ParseFromString(self, _):
            pass

    mod.Payload = FakePayload
    sys.modules["sparkplug_b_pb2"] = mod


# --------------------------------------------------------------------------- #
# Tests
# --------------------------------------------------------------------------- #
class SNMPTest(unittest.TestCase):
    def test_reads_and_normalizes(self):
        install_fake_pysnmp(42)
        mod = fresh_import("snmp")
        c = mod.SNMPCollector({"asset_id": "n1", "host": "10.0.0.1",
                               "oids": [{"name": "inOctets", "oid": "1.3.6.1.2.1"}]})
        values = c._read_oids(c._resolve_oids())
        self.assertEqual(values["inoctets"], 42)
        env = c._normalize_data(values)
        self.assertEqual(env["collector_type"], "snmp")
        self.assertEqual(env["payload"]["inoctets"], 42)

    def test_missing_driver_disables(self):
        sys.modules.pop("pysnmp", None)
        sys.modules.pop("pysnmp.hlapi", None)
        mod = fresh_import("snmp")
        mod._PYSNMP_AVAILABLE = False
        c = mod.SNMPCollector({"asset_id": "n1", "host": "10.0.0.1"})
        run(c.start())
        self.assertFalse(c.running)


class DNP3Test(unittest.TestCase):
    def test_reads_points(self):
        install_fake_dnp3()
        mod = fresh_import("dnp3")
        c = mod.DNP3Collector({"asset_id": "o1", "host": "10.0.0.2", "points": [
            {"name": "flow", "group": "analog", "index": 0},
            {"name": "trip", "group": "binary", "index": 1},
        ]})
        run(c._connect())
        values = c._read_points()
        self.assertEqual(values["flow"], 12.5)
        self.assertEqual(values["trip"], True)
        self.assertEqual(c._normalize_data(values)["collector_type"], "dnp3")

    def test_missing_driver_disables(self):
        for n in ("dnp3_python", "dnp3_python.dnp3station", "dnp3_python.dnp3station.master_new"):
            sys.modules.pop(n, None)
        mod = fresh_import("dnp3")
        mod._DNP3_AVAILABLE = False
        c = mod.DNP3Collector({"asset_id": "o1", "host": "10.0.0.2"})
        run(c.start())
        self.assertFalse(c.running)


class SparkplugTest(unittest.TestCase):
    def test_decode_and_normalize(self):
        install_fake_sparkplug_pb([("Temperature/Zone1", 25.0), ("Pressure", 3.2)])
        mod = fresh_import("sparkplug_b")
        c = mod.SparkplugBCollector({"asset_id": "s1", "host": "broker"})
        values = c._decode(b"protobuf-bytes")
        self.assertEqual(values["Temperature/Zone1"], 25.0)
        env = c._normalize_data(values)
        self.assertEqual(env["collector_type"], "sparkplug_b")
        self.assertEqual(env["payload"]["temperature_zone1"], 25.0)  # / -> _, lowercased

    def test_missing_driver_disables(self):
        sys.modules.pop("sparkplug_b_pb2", None)
        mod = fresh_import("sparkplug_b")
        mod._SPARKPLUG_PB_AVAILABLE = False
        mod._PAHO_AVAILABLE = False
        c = mod.SparkplugBCollector({"asset_id": "s1", "host": "broker"})
        run(c.start())
        self.assertFalse(c.running)


if __name__ == "__main__":
    unittest.main(verbosity=2)

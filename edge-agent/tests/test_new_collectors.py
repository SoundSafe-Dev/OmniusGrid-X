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


class SpbMetric:
    """Richer Sparkplug metric stub: carries name, alias, seq, timestamp and a
    ``value`` oneof so alias/message-type paths can be exercised."""

    def __init__(self, name="", alias=0, value=None, which="double_value"):
        self.name = name
        self.alias = alias
        self._which = which if value is not None else None
        # Populate the concrete value field so getattr(metric, which) works.
        for f in ("double_value", "float_value", "long_value", "int_value",
                  "boolean_value", "string_value"):
            setattr(self, f, value if f == which else None)

    def WhichOneof(self, _):
        return self._which


def install_fake_spb_payload():
    """A programmable Sparkplug payload stub keyed off the raw bytes passed in.

    The collector calls ``ParseFromString(payload_bytes)``; we smuggle the
    desired (metrics, seq, timestamp) through a registry indexed by those bytes.
    """
    mod = types.ModuleType("sparkplug_b_pb2")
    registry = {}

    class MetricList(list):
        """List that also supports protobuf's repeated-field .add()."""

        def add(self):
            m = types.SimpleNamespace()
            self.append(m)
            return m

    class FakePayload:
        def __init__(self):
            self.metrics = MetricList()
            self.seq = 0
            self.timestamp = 0

        def ParseFromString(self, raw):
            spec = registry.get(raw, {})
            self.metrics = MetricList(spec.get("metrics", []))
            self.seq = spec.get("seq", 0)
            self.timestamp = spec.get("timestamp", 0)

        def SerializeToString(self):
            return b"serialized"

    mod.Payload = FakePayload
    mod._registry = registry
    sys.modules["sparkplug_b_pb2"] = mod
    return registry


class RecordingClient:
    """Captures publish() calls so rebirth requests are observable."""

    def __init__(self):
        self.published = []

    def publish(self, topic, payload):
        self.published.append((topic, payload))


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

    # -- FS-121 correctness guards -------------------------------------- #
    def test_counter64_no_float_precision_loss(self):
        """Large Counter64 values must not be rounded via float() (loss > 2**53).

        Before the fix a Counter64 of 2**64-1 coerced to 2**64 (off by one),
        corrupting every consumption/rate derived from the counter.
        """
        install_fake_pysnmp()
        mod = fresh_import("snmp")
        big = 2**64 - 1
        self.assertEqual(mod.SNMPCollector._coerce(big), big)
        self.assertNotEqual(mod.SNMPCollector._coerce(big), 2**64)
        # 2**53+1 is the classic first integer float cannot represent exactly.
        self.assertEqual(mod.SNMPCollector._coerce(2**53 + 1), 2**53 + 1)

    def test_coerce_bool_and_string_and_float(self):
        install_fake_pysnmp()
        mod = fresh_import("snmp")
        self.assertIs(mod.SNMPCollector._coerce(True), True)   # not coerced to 1
        self.assertEqual(mod.SNMPCollector._coerce("up"), "up")
        self.assertEqual(mod.SNMPCollector._coerce(3.5), 3.5)
        self.assertEqual(mod.SNMPCollector._coerce(3.0), 3)

    def test_timestamp_is_aware_utc(self):
        install_fake_pysnmp(42)
        mod = fresh_import("snmp")
        c = mod.SNMPCollector({"asset_id": "n1", "host": "10.0.0.1"})
        from datetime import datetime
        env = c._normalize_data({"x": 1})
        ts = datetime.fromisoformat(env["timestamp_edge"])
        self.assertIsNotNone(ts.tzinfo)  # aware, not naive local time


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

    # -- FS-120 correctness guards -------------------------------------- #
    def test_aliased_data_resolves_via_birth(self):
        """DDATA carrying only aliases (no names) must resolve against the birth.

        Before the fix, data metrics without a ``name`` were silently dropped —
        losing essentially all telemetry from bandwidth-optimised nodes.
        """
        registry = install_fake_spb_payload()
        mod = fresh_import("sparkplug_b")
        c = mod.SparkplugBCollector({"asset_id": "s1", "host": "broker"})

        registry[b"birth"] = {"seq": 0, "metrics": [
            SpbMetric(name="Temperature", alias=1, value=20.0),
            SpbMetric(name="Pressure", alias=2, value=3.0),
        ]}
        registry[b"data"] = {"seq": 1, "metrics": [
            SpbMetric(name="", alias=1, value=25.5),   # alias-only
            SpbMetric(name="", alias=2, value=4.2),
        ]}

        birth = c._process("spBv1.0/g/NBIRTH/nodeA", b"birth")
        self.assertEqual(birth["payload"]["temperature"], 20.0)

        data = c._process("spBv1.0/g/NDATA/nodeA", b"data")
        self.assertEqual(data["payload"]["temperature"], 25.5)
        self.assertEqual(data["payload"]["pressure"], 4.2)

    def test_unresolved_alias_triggers_rebirth(self):
        """DATA with an alias we never learned -> request a rebirth (not silence)."""
        registry = install_fake_spb_payload()
        mod = fresh_import("sparkplug_b")
        c = mod.SparkplugBCollector({"asset_id": "s1", "host": "broker"})
        client = RecordingClient()
        c._client = client

        registry[b"orphan"] = {"seq": 5, "metrics": [
            SpbMetric(name="", alias=99, value=1.0),
        ]}
        result = c._process("spBv1.0/g/NDATA/nodeB", b"orphan")
        self.assertIsNone(result)  # nothing resolvable
        # A rebirth NCMD was published so the node re-sends its birth/alias map.
        self.assertTrue(client.published)
        self.assertEqual(client.published[0][0], "spBv1.0/g/NCMD/nodeB")

    def test_sequence_gap_requests_rebirth_but_keeps_data(self):
        """A seq gap must fire a rebirth yet still emit the resolvable reading."""
        registry = install_fake_spb_payload()
        mod = fresh_import("sparkplug_b")
        c = mod.SparkplugBCollector({"asset_id": "s1", "host": "broker"})
        client = RecordingClient()
        c._client = client

        registry[b"b"] = {"seq": 0, "metrics": [SpbMetric(name="RPM", alias=1, value=100.0)]}
        registry[b"gap"] = {"seq": 7, "metrics": [SpbMetric(name="", alias=1, value=110.0)]}
        c._process("spBv1.0/g/NBIRTH/nodeC", b"b")     # expected next seq = 1
        out = c._process("spBv1.0/g/NDATA/nodeC", b"gap")  # seq 7 -> gap
        self.assertEqual(out["payload"]["rpm"], 110.0)  # data NOT dropped
        self.assertEqual(client.published[0][0], "spBv1.0/g/NCMD/nodeC")

    def test_death_and_state_emit_nothing(self):
        registry = install_fake_spb_payload()
        mod = fresh_import("sparkplug_b")
        c = mod.SparkplugBCollector({"asset_id": "s1", "host": "broker"})
        registry[b"d"] = {"seq": 0, "metrics": [SpbMetric(name="bdSeq", alias=0, value=3.0)]}
        self.assertIsNone(c._process("spBv1.0/g/NDEATH/nodeD", b"d"))
        self.assertIsNone(c._process("spBv1.0/g/STATE/host1", b"d"))

    def test_timestamp_is_aware_utc(self):
        registry = install_fake_spb_payload()
        mod = fresh_import("sparkplug_b")
        c = mod.SparkplugBCollector({"asset_id": "s1", "host": "broker"})
        # payload epoch-millis timestamp is used and is aware UTC.
        registry[b"t"] = {"seq": 0, "timestamp": 1_700_000_000_000,
                          "metrics": [SpbMetric(name="v", alias=1, value=1.0)]}
        from datetime import datetime, timezone
        env = c._process("spBv1.0/g/NBIRTH/nodeE", b"t")
        ts = datetime.fromisoformat(env["timestamp_edge"])
        self.assertIsNotNone(ts.tzinfo)
        self.assertEqual(ts, datetime(2023, 11, 14, 22, 13, 20, tzinfo=timezone.utc))

    def test_control_and_bdseq_metrics_excluded(self):
        registry = install_fake_spb_payload()
        mod = fresh_import("sparkplug_b")
        c = mod.SparkplugBCollector({"asset_id": "s1", "host": "broker"})
        registry[b"birth"] = {"seq": 0, "metrics": [
            SpbMetric(name="bdSeq", alias=0, value=7.0),
            SpbMetric(name="Node Control/Rebirth", alias=0, value=False, which="boolean_value"),
            SpbMetric(name="Flow", alias=1, value=9.0),
        ]}
        env = c._process("spBv1.0/g/NBIRTH/nodeF", b"birth")
        self.assertEqual(set(env["payload"].keys()), {"flow"})


if __name__ == "__main__":
    unittest.main(verbosity=2)

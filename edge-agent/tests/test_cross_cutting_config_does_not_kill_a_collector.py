"""A `quality:` block must not stop the collector it configures (FS-500).

THE DEFECT. `_start_collector` splatted the whole config block into the constructor:

    collector = collector_class(**config.config, on_message_callback=...)

Four of the keys in that dict are not the collector's business — they are read from the same
place by other parts of the agent:

    quality  -> coordinator, `_quality`
    packml   -> collectors/adapter.py:55
    alerts   -> main.py:506
    oee      -> main.py:512

Four of the seventeen registered collector types take no `**kwargs`: **mqtt, modbus, opcua,
orca_file**. For those, writing any of those four blocks raised
`TypeError: unexpected keyword argument`, which `_start_collector`'s own handler catches and
logs as `collector_start_failed` — and **the collector never ran**.

The symptom is one log line at startup naming a config key the operator had every reason to
believe was supported, and then silence from that asset forever. Whether it happened depended
on which device you were talking to, because the adapter-wrapped collectors take the raw dict
and were unaffected — so the same config file works for a BACnet asset and kills an MQTT one.

WHY NOTHING CAUGHT IT. There is no test that starts a collector with a `quality:` block. The
quality pipeline has its own tests, the collectors have theirs, and the failure is in the
handover: one component reads a key out of a dict that another component is about to reject.
"""

from __future__ import annotations

import asyncio
import inspect
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from opsgrid_agent.buffer.store_forward import StoreForwardBuffer  # noqa: E402
from opsgrid_agent.collectors.coordinator import (  # noqa: E402
    CROSS_CUTTING_KEYS,
    CollectorConfig,
    UnifiedCollectorCoordinator,
)

#: The minimum each strict collector needs to be constructed at all. Supplied so the test
#: isolates the cross-cutting keys — without these it fails on a MISSING required argument,
#: which is a different defect and would have made the assertion below dishonest.
MINIMUM_CONFIG = {
    "mqtt": {"broker_host": "broker.example"},
    "modbus": {"connection_type": "tcp"},
    "opcua": {"server_url": "opc.tcp://device.example:4840", "asset_id": "a1"},
    "orca_file": {"watch_path": "/tmp", "asset_id": "a1"},
}

#: The blocks an operator can legitimately write beside any collector.
BLOCKS = {
    "quality": {"deadband": {"absolute": 0.5}},
    "packml": {"state_key": "state", "asset_type": "generic"},
    "alerts": {"rules": []},
    "oee": {"ideal_cycle_time_seconds": 12},
}


def _collectors_without_kwargs():
    """The registered types whose constructor would reject an unexpected key."""
    out = []
    for name, cls in UnifiedCollectorCoordinator.SUPPORTED_COLLECTORS.items():
        try:
            sig = inspect.signature(cls.__init__)
        except (TypeError, ValueError):  # pragma: no cover - builtins
            continue
        if not any(p.kind == p.VAR_KEYWORD for p in sig.parameters.values()):
            out.append(name)
    return sorted(out)


class TheCrossCuttingKeysAreNotPassedToConstructors(unittest.IsolatedAsyncioTestCase):
    async def _coordinator(self, tmpdir):
        return UnifiedCollectorCoordinator(
            buffer=StoreForwardBuffer(buffer_path=os.path.join(tmpdir, "b.db"))
        )

    def test_the_strict_collectors_still_exist(self):
        """Vacuity. If every collector grew `**kwargs`, the defect is gone and so is this
        test's subject — which should be noticed rather than silently passing."""
        strict = _collectors_without_kwargs()
        self.assertTrue(
            strict,
            "no registered collector rejects unexpected keys any more, so this test proves "
            "nothing. Either that is a real improvement worth recording, or the registry "
            "read is broken.",
        )

    async def test_a_strict_collector_starts_with_every_block_present(self):
        """The whole defect, on the collector types that actually break."""
        with tempfile.TemporaryDirectory() as tmpdir:
            for collector_type in _collectors_without_kwargs():
                coordinator = await self._coordinator(tmpdir)
                coordinator.register_collector(
                    CollectorConfig(
                        asset_id=f"a-{collector_type}",
                        collector_type=collector_type,
                        config={**MINIMUM_CONFIG.get(collector_type, {}), **BLOCKS},
                    )
                )

                await coordinator._start_collector(coordinator.configs[f"a-{collector_type}"])

                self.assertIn(
                    f"a-{collector_type}",
                    coordinator.collectors,
                    f"{collector_type} did not start with the four cross-cutting blocks "
                    f"present. Before FS-500 the whole config dict was splatted into the "
                    f"constructor, so a `quality:` block raised TypeError, was caught, "
                    f"logged as collector_start_failed — and the asset went silent.",
                )
                await coordinator.stop_all()

    async def test_the_collectors_own_keys_still_reach_it(self):
        """The other direction. Stripping too much would leave a collector configured with
        nothing, which fails in the same invisible way.

        USES A STUB, NOT `mqtt`. The first version constructed a real MQTTCollector and
        failed only when the whole suite ran: `test_edge_agent_integration.py:31-34` installs
        a fake `opsgrid_agent.collectors.mqtt` module into `sys.modules`, so by the time this
        ran the registered class was somebody else's double. A test that asserts what the
        coordinator passes along should not also depend on which collector implementation
        happens to be loaded — so it registers its own.
        """
        received = {}

        class _Recording:
            def __init__(self, **kwargs):
                received.update(kwargs)

            async def start(self):
                return

            async def stop(self):
                return

        with tempfile.TemporaryDirectory() as tmpdir:
            coordinator = await self._coordinator(tmpdir)
            coordinator.SUPPORTED_COLLECTORS = dict(coordinator.SUPPORTED_COLLECTORS)
            coordinator.SUPPORTED_COLLECTORS["recording"] = _Recording
            coordinator.register_collector(
                CollectorConfig(
                    asset_id="a1",
                    collector_type="recording",
                    config={"broker_host": "broker.example", "broker_port": 8883, **BLOCKS},
                )
            )

            await coordinator._start_collector(coordinator.configs["a1"])

            self.assertEqual(
                received.get("broker_host"),
                "broker.example",
                "the collector's own config no longer reaches it — the strip is too wide",
            )
            self.assertEqual(received.get("broker_port"), 8883)
            for key in CROSS_CUTTING_KEYS:
                self.assertNotIn(
                    key,
                    received,
                    f"{key!r} was passed to the constructor; it is read by the agent, not by "
                    f"the collector, and a strict collector raises TypeError on it (FS-500)",
                )
            await coordinator.stop_all()

    def test_the_stripped_set_matches_what_the_agent_reads(self):
        """The register. Adding a fifth cross-cutting key without adding it here reintroduces
        the defect for that key, silently — which is how this arrived in the first place."""
        self.assertEqual(
            CROSS_CUTTING_KEYS,
            frozenset({"quality", "packml", "alerts", "oee"}),
            "the cross-cutting key set changed. Every key here must be read by the agent "
            "(coordinator/adapter/main) rather than by a collector constructor; every key "
            "read that way must be here, or a strict collector dies on it.",
        )


if __name__ == "__main__":
    unittest.main()

"""A collector removed by hot-reload kept exporting its liveness gauge forever (FS-699).

A prometheus_client label child persists until removed. `stop_collector` popped the
collector and its task and left the `edge_collector_connection_state` child in the
registry, frozen at whatever the health monitor last wrote:

  * frozen at **0** — `EdgeCollectorDown` (severity HIGH, `for: 5m`) fires forever for a
    device that was deliberately decommissioned, and an alert that is always wrong about
    the same collector is an alert operators learn to silence;
  * frozen at **1** — a phantom healthy collector nobody configured, exported until the
    process restarts.

Absence is the honest answer for a removed collector, and the ordering makes the clear
race-free by construction: it runs at the end of `stop_collector`, and between it and the
reloader's `configs.pop` there is no `await`, so the monitor — another task on the same
loop — cannot republish the child in between. (It can republish *before*, which the clear
then wins.)

These tests drive the real `stop_collector`, not the FakeCoordinator that
`test_config_reload.py` substitutes at exactly this seam — the double records that "stop"
was called and cannot see what the registry still exports afterwards, which is the whole
finding (rule 191).
"""

from __future__ import annotations

import os
import tempfile

import pytest

from opsgrid_agent import metrics
from opsgrid_agent.buffer.store_forward import StoreForwardBuffer
from opsgrid_agent.collectors.coordinator import (
    CollectorConfig,
    UnifiedCollectorCoordinator,
)


def _connection_children() -> set[tuple[str, str]]:
    return {
        (sample.labels["asset_id"], sample.labels["collector_type"])
        for metric in metrics.connection_state.collect()
        for sample in metric.samples
    }


def _coordinator() -> UnifiedCollectorCoordinator:
    buffer = StoreForwardBuffer(
        buffer_path=os.path.join(tempfile.mkdtemp(), "buffer.db"),
        retention_hours=1,
    )
    return UnifiedCollectorCoordinator(buffer=buffer, kafka_producer=None)


class TestTheClaimIsWithdrawn:
    @pytest.mark.asyncio
    async def test_stopping_a_collector_removes_its_series(self):
        """THE PROPERTY. Before the fix the child survived removal at its last value."""
        coordinator = _coordinator()
        coordinator.configs["press-11"] = CollectorConfig(
            collector_type="http_rest", asset_id="press-11", config={}
        )
        metrics.set_connection_state("press-11", "http_rest", up=False)
        assert ("press-11", "http_rest") in _connection_children()

        await coordinator.stop_collector("press-11")

        assert ("press-11", "http_rest") not in _connection_children(), (
            "the removed collector still exports connection_state — frozen at 0 this "
            "holds EdgeCollectorDown firing forever for a decommissioned device"
        )

    @pytest.mark.asyncio
    async def test_other_collectors_series_survive(self):
        """NEGATIVE CONTROL. A clear() of the whole gauge would pass the test above and
        blind EdgeCollectorDown for every OTHER collector until the monitor's next pass."""
        coordinator = _coordinator()
        coordinator.configs["press-12"] = CollectorConfig(
            collector_type="http_rest", asset_id="press-12", config={}
        )
        metrics.set_connection_state("press-12", "http_rest", up=False)
        metrics.set_connection_state("press-13", "snmp", up=True)

        await coordinator.stop_collector("press-12")

        assert ("press-13", "snmp") in _connection_children()

    @pytest.mark.asyncio
    async def test_stopping_a_collector_that_never_published_is_not_an_error(self):
        """A collector removed before the monitor's first 30s pass has no child to
        withdraw; `stop_collector` must not raise over that."""
        coordinator = _coordinator()
        coordinator.configs["press-14"] = CollectorConfig(
            collector_type="snmp", asset_id="press-14", config={}
        )
        await coordinator.stop_collector("press-14")
        assert ("press-14", "snmp") not in _connection_children()

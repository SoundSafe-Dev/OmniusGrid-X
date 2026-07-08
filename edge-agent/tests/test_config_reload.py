"""Tests for collector config hot-reload (task 24)."""

import pytest

from dataclasses import dataclass, field
from typing import Any, Dict

from opsgrid_agent.config_reload import ConfigReloader, diff_configs


# Minimal stand-in for coordinator.CollectorConfig. The reloader is duck-typed,
# and coordinator.py is not importable standalone on this branch (pre-existing
# stale package imports, resolved by the convergence task), so we avoid importing
# it here and mirror only the fields the reloader reads.
@dataclass
class _Cfg:
    collector_type: str
    asset_id: str
    config: Dict[str, Any] = field(default_factory=dict)
    enabled: bool = True


def cfg(asset, ctype="modbus", enabled=True, **config):
    return _Cfg(collector_type=ctype, asset_id=asset, config=config, enabled=enabled)


# --- pure diff ---------------------------------------------------------------

def test_diff_classifies_all_four():
    current = {"a": cfg("a", host="1"), "b": cfg("b"), "c": cfg("c")}
    new = {"a": cfg("a", host="1"), "b": cfg("b", host="2"), "d": cfg("d")}
    report = diff_configs(current, new)
    assert report.added == ["d"]
    assert report.removed == ["c"]
    assert report.changed == ["b"]      # host changed
    assert report.unchanged == ["a"]


def test_diff_is_order_insensitive_on_config_dict():
    current = {"a": cfg("a", x=1, y=2)}
    new = {"a": cfg("a", y=2, x=1)}
    assert diff_configs(current, new).unchanged == ["a"]


# --- applied reload against a fake coordinator -------------------------------

class FakeCoordinator:
    def __init__(self):
        self.configs = {}
        self._quality = {}
        self._running = True
        self.calls = []

    def register_collector(self, config):
        self.configs[config.asset_id] = config
        self.calls.append(("register", config.asset_id))

    async def _start_collector(self, config):
        self.calls.append(("start", config.asset_id))

    async def restart_collector(self, asset_id):
        self.calls.append(("restart", asset_id))

    async def stop_collector(self, asset_id):
        self.calls.append(("stop", asset_id))


@pytest.mark.asyncio
async def test_reload_applies_add_remove_change():
    coord = FakeCoordinator()
    coord.configs = {"keep": cfg("keep"), "drop": cfg("drop"), "mod": cfg("mod", host="1")}
    reloader = ConfigReloader(coord)

    report = await reloader.reload([cfg("keep"), cfg("mod", host="2"), cfg("new")])

    assert report.summary == {"added": 1, "removed": 1, "changed": 1, "unchanged": 1}
    assert ("stop", "drop") in coord.calls
    assert ("start", "new") in coord.calls
    assert ("restart", "mod") in coord.calls
    assert "drop" not in coord.configs
    assert "new" in coord.configs


@pytest.mark.asyncio
async def test_reload_does_not_start_when_not_running():
    coord = FakeCoordinator()
    coord._running = False
    reloader = ConfigReloader(coord)
    await reloader.reload([cfg("new")])
    # registered but not started while coordinator is stopped
    assert ("register", "new") in coord.calls
    assert ("start", "new") not in coord.calls

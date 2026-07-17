"""Collector config hot-reload (task 24).

Lets an operator add, remove, or reconfigure collectors without restarting the
whole agent (which would drop every other collector's connection and buffer
state). The reloader diffs the running configuration against a freshly-loaded
one and applies the minimal set of changes:

    added     -> register + start
    removed   -> stop + deregister
    changed   -> re-register (rebuilds the quality pipeline) + restart
    unchanged -> left running, untouched

The diff (:func:`diff_configs`) is pure and unit-testable; :class:`ConfigReloader`
applies it against a live coordinator.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, List

import structlog

if TYPE_CHECKING:  # avoid a runtime import of the coordinator module
    from .collectors.coordinator import CollectorConfig, UnifiedCollectorCoordinator

logger = structlog.get_logger()

# The reloader is duck-typed against the coordinator and any object exposing
# collector_type/asset_id/enabled/config, so this module imports cleanly on its
# own. (coordinator.py currently carries pre-existing stale package imports;
# that is resolved by the fixed-sprints<->integration convergence, task 25.)
CollectorConfig = Any  # type: ignore[assignment]


@dataclass
class ReloadReport:
    added: List[str] = field(default_factory=list)
    removed: List[str] = field(default_factory=list)
    changed: List[str] = field(default_factory=list)
    unchanged: List[str] = field(default_factory=list)

    @property
    def summary(self) -> Dict[str, int]:
        return {
            "added": len(self.added),
            "removed": len(self.removed),
            "changed": len(self.changed),
            "unchanged": len(self.unchanged),
        }


def _identity(cfg: CollectorConfig) -> tuple:
    """Value tuple that decides whether a collector needs restarting."""
    return (cfg.collector_type, cfg.enabled, _freeze(cfg.config))


def _freeze(value):
    """Hashable, order-insensitive snapshot of a config dict for comparison."""
    if isinstance(value, dict):
        return tuple(sorted((k, _freeze(v)) for k, v in value.items()))
    if isinstance(value, list):
        return tuple(_freeze(v) for v in value)
    return value


def diff_configs(
    current: Dict[str, CollectorConfig], new: Dict[str, CollectorConfig]
) -> ReloadReport:
    """Classify each asset as added / removed / changed / unchanged."""
    report = ReloadReport()
    for asset_id in new:
        if asset_id not in current:
            report.added.append(asset_id)
        elif _identity(current[asset_id]) != _identity(new[asset_id]):
            report.changed.append(asset_id)
        else:
            report.unchanged.append(asset_id)
    for asset_id in current:
        if asset_id not in new:
            report.removed.append(asset_id)
    return report


class ConfigReloader:
    """Applies a config diff to a running coordinator with minimal disruption."""

    def __init__(self, coordinator: UnifiedCollectorCoordinator):
        self.coordinator = coordinator

    async def reload(self, new_configs: List[CollectorConfig]) -> ReloadReport:
        new_map = {c.asset_id: c for c in new_configs}
        report = diff_configs(dict(self.coordinator.configs), new_map)

        for asset_id in report.removed:
            await self.coordinator.stop_collector(asset_id)
            self.coordinator.configs.pop(asset_id, None)
            self.coordinator._quality.pop(asset_id, None)

        for asset_id in report.added:
            cfg = new_map[asset_id]
            self.coordinator.register_collector(cfg)
            if getattr(self.coordinator, "_running", False) and cfg.enabled:
                await self.coordinator._start_collector(cfg)

        for asset_id in report.changed:
            # register_collector overwrites the stored config and rebuilds the
            # quality pipeline; restart_collector then relaunches from it.
            self.coordinator.register_collector(new_map[asset_id])
            if getattr(self.coordinator, "_running", False):
                await self.coordinator.restart_collector(asset_id)

        logger.info("config_reloaded", **report.summary)
        return report

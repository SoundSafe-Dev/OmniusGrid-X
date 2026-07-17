"""Adapter bridging BaseCollector-style collectors to the coordinator contract.

Two collector styles exist in this package:

* **Coordinator-native** (mqtt, opcua, modbus, screen_scraper, file_watcher):
  instantiated as ``Collector(**config, on_message_callback=cb)``; ``start()``
  runs the collector loop until ``stop()``; each reading is delivered by
  awaiting ``on_message_callback(message)``.

* **BaseCollector** (ethernet_ip, profinet, bacnet, can_bus, http_rest):
  instantiated as ``Collector(config_dict)``; ``start()`` spawns a background
  poll task and returns immediately; each reading is delivered by calling the
  synchronous data handlers registered via ``add_data_handler``.

``UnifiedCollectorCoordinator`` speaks the first contract. This adapter wraps a
BaseCollector so it satisfies that contract, letting the new collectors be
registered in ``SUPPORTED_COLLECTORS`` with no changes to their source.
"""

import asyncio
from typing import Any, Callable, Dict, Optional

import structlog

from .base import BaseCollector
# Relative import keeps the adapter independent of the omniusgrid_agent ->
# opsgrid_agent package rename (Hridyansh's package-renaming-fix).
from ..packml import create_mapper_for_asset_type

logger = structlog.get_logger()


class CoordinatorCollectorAdapter:
    """Wrap a :class:`BaseCollector` for the coordinator's collector contract."""

    #: Concrete BaseCollector subclass to instantiate. Set on generated subclasses.
    inner_cls: type = BaseCollector

    def __init__(self, on_message_callback: Optional[Callable] = None, **config: Any):
        self.asset_id = config.get("asset_id")
        self._on_message_callback = on_message_callback
        self._collector: BaseCollector = self.inner_cls(config)
        self._collector.add_data_handler(self._forward)
        # Created lazily in start() so it binds to the loop that actually runs
        # the collector (avoids cross-loop issues; robust on Python 3.9+).
        self._stop_event: Optional[asyncio.Event] = None
        self._stopped = False

        # Optional state -> PackML mapping. BaseCollector-style collectors emit
        # raw payloads; when a `packml` block is present in config we normalize a
        # raw state field the same way modbus/opcua do, so OEE/state analytics see
        # one shape regardless of collector. No-op when `packml` is absent.
        self._mapper = None
        self._state_key = None
        packml_conf = config.get("packml")
        if packml_conf:
            self._state_key = packml_conf.get("state_key", "state")
            self._mapper = create_mapper_for_asset_type(
                packml_conf.get("asset_type", "generic"),
                packml_conf.get("mappings"),
            )

    def _apply_packml(self, message: Dict[str, Any]) -> None:
        """Enrich the envelope with PackML state, mirroring the modbus shape."""
        if self._mapper is None:
            return
        payload = message.get("payload") or {}
        raw_state = payload.get(self._state_key)
        if raw_state is None:
            return
        state = self._mapper.map_state(str(raw_state))
        message["packml_state"] = state.value
        payload["packml_state"] = state.value
        payload["packml_category"] = self._mapper.get_state_category(state)
        message["payload"] = payload

    def _forward(self, message: Dict[str, Any]) -> None:
        """Forward an emitted reading to the coordinator's async callback.

        ``emit()`` invokes data handlers synchronously on the event loop, so we
        schedule the awaitable callback as a task rather than blocking the
        collector's poll loop.
        """
        self._apply_packml(message)
        if self._on_message_callback is None:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:  # pragma: no cover - emit always runs on the loop
            logger.error("adapter_no_running_loop", asset_id=self.asset_id)
            return
        loop.create_task(self._on_message_callback(message))

    async def start(self) -> None:
        """Start the wrapped collector and block until stopped.

        Blocking mirrors the coordinator-native collectors so the coordinator's
        ``_run_collector`` supervision loop does not hot-restart us. If the inner
        collector fails to start (e.g. a missing driver library) it logs and
        clears its running flag; we still wait here so the coordinator treats the
        collector as parked rather than crash-looping it.
        """
        if self._stopped:
            return
        self._stop_event = asyncio.Event()
        await self._collector.start()
        if self._stopped:  # stop() raced in during inner start()
            return
        await self._stop_event.wait()

    async def stop(self) -> None:
        """Stop the wrapped collector and release :meth:`start`."""
        self._stopped = True
        await self._collector.stop()
        if self._stop_event is not None:
            self._stop_event.set()

    @property
    def running(self) -> bool:
        return self._collector.running


def coordinator_adapter(inner_cls: type) -> type:
    """Build a coordinator-compatible adapter class for a BaseCollector subclass.

    Returns a new subclass of :class:`CoordinatorCollectorAdapter` bound to
    ``inner_cls``, suitable for registration in ``SUPPORTED_COLLECTORS``.
    """
    return type(
        f"{inner_cls.__name__}CoordinatorAdapter",
        (CoordinatorCollectorAdapter,),
        {"inner_cls": inner_cls},
    )

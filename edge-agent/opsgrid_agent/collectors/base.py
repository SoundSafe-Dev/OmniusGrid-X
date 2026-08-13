"""Base Collector Interface for Edge Agent"""

import os
from abc import ABC, abstractmethod
from typing import Dict, Any, Callable, Optional
from datetime import datetime
import structlog

from opsgrid_agent import metrics

logger = structlog.get_logger()


class BaseCollector(ABC):
    """
    Base class for all collectors.

    Defines the interface that all collectors must implement.
    """

    # Set True on collector classes whose default source is SYNTHETIC (video,
    # audio). Under EDGE_REQUIRE_EXPLICIT_SOURCES=true (production posture) an
    # omitted 'source' on such a collector is a config error — one shared guard
    # here so every current and future synthetic-capable collector inherits it.
    has_synthetic_default = False

    #: The source values this collector understands. When set, a `source` outside this
    #: set is a CONFIG ERROR rather than a silent fallback (FS-457).
    #:
    #: `has_synthetic_default` above catches an OMITTED source. It cannot catch a source
    #: that is present and misspelled — and both synthetic-capable collectors branched on
    #: one exact string and synthesized on everything else, so `source: "mic"` or
    #: `source: "rtsp"` produced fabricated audio and fabricated motion scores, silently,
    #: on a collector the operator believed was reading hardware.
    #:
    #: A typo should stop the collector, not quietly change what it measures.
    known_sources: tuple[str, ...] = ()

    #: Label the error counter carries. The coordinator overwrites this with the
    #: CONFIGURED collector type so `errors_total` and `connection_state` can be
    #: joined on (asset_id, collector_type) — a counter labelled with the class
    #: name and a gauge labelled with the config type describe the same collector
    #: and will not line up in a query. The class name is the fallback for a
    #: collector constructed directly, as tests do.
    collector_type: str = ""

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.asset_id = config.get("asset_id")
        self._running = False
        self._data_handlers: list[Callable[[Dict[str, Any]], None]] = []

        if (
            self.has_synthetic_default
            and "source" not in config
            and os.getenv("EDGE_REQUIRE_EXPLICIT_SOURCES", "false").lower() == "true"
        ):
            raise ValueError(
                f"{type(self).__name__} requires an explicit 'source' "
                "(EDGE_REQUIRE_EXPLICIT_SOURCES is enabled)"
            )

        source = config.get("source")
        if self.known_sources and source is not None and source not in self.known_sources:
            raise ValueError(
                f"{type(self).__name__} got source={source!r}, which it does not "
                f"understand. Known sources: {', '.join(sorted(self.known_sources))}. "
                f"Refusing to start rather than falling back to synthetic data that "
                f"would look like a reading from hardware."
            )
    
    @abstractmethod
    async def start(self) -> None:
        """
        Start the collector.

        Subclasses must override and call ``await super().start()`` first so the
        running flag is set before their poll loop begins.
        """
        self._running = True

    @abstractmethod
    async def stop(self) -> None:
        """
        Stop the collector.

        Subclasses must override and call ``await super().stop()`` first so the
        running flag is cleared, allowing their poll loop to exit cleanly.
        """
        self._running = False
    
    def add_data_handler(self, handler: Callable[[Dict[str, Any]], None]) -> None:
        """
        Add a handler to be called when data is collected.
        
        Args:
            handler: Function to call with collected data
        """
        self._data_handlers.append(handler)
    
    async def emit(self, data: Dict[str, Any]) -> None:
        """
        Emit collected data to all registered handlers.
        
        Args:
            data: Collected telemetry data
        """
        for handler in self._data_handlers:
            try:
                handler(data)
            except Exception as e:
                logger.error(
                    "data_handler_failed",
                    asset_id=self.asset_id,
                    error=str(e)
                )
    
    def record_failure(self, event: str, **fields: Any) -> None:
        """Report a failed collection cycle: log it AND count it (FS-691).

        `emit()` is the shared seam for a reading that worked. There was no seam for
        one that did not, and the consequence was measurable: `metrics.errors_total`
        existed and **no collector incremented it, in any of the fifteen**. The
        coordinator calls `record_error` only when a message *handler* raises, which
        cannot fire for a poll that failed — a failed poll produces no message to
        hand over. So the seam this module's docstring describes covers deliveries
        completely and errors not at all.

        What that looked like, driven against a real `http.server` returning 500:
        three seconds of polling, **zero readings, `running` True, and no counter
        anywhere naming the asset**. `connection_state` is derived from
        `task is not None and not task.done()` (`coordinator.py:504`), and the poll
        task is perfectly healthy — it is the device that is not. Nothing in
        `infra/prometheus/alerts.yml` keys on a collector that is up and silent:
        the agent heartbeats, so `EdgeAgentOffline` is quiet; the buffer is empty
        because nothing was collected, so `EdgeAgentBufferHigh` is quiet. A machine
        that stopped reporting a month ago looks exactly like a machine that is idle.

        Use this instead of a bare `logger.error` on any path where a collection
        cycle failed. Not for a config error at construction — that path raises, and
        a collector that never started has no asset to attribute the failure to.
        """
        logger.error(event, asset_id=self.asset_id, **fields)
        metrics.record_error(
            self.asset_id or "unknown",
            self.collector_type or type(self).__name__,
        )

    @property
    def running(self) -> bool:
        """Check if collector is running."""
        return self._running

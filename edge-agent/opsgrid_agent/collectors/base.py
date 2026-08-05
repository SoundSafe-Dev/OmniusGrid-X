"""Base Collector Interface for Edge Agent"""

import os
from abc import ABC, abstractmethod
from typing import Dict, Any, Callable, Optional
from datetime import datetime
import structlog

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
    
    @property
    def running(self) -> bool:
        """Check if collector is running."""
        return self._running

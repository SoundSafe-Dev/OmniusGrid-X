"""Base Collector Interface for Edge Agent"""

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
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.asset_id = config.get("asset_id")
        self._running = False
        self._data_handlers: list[Callable[[Dict[str, Any]], None]] = []
    
    @abstractmethod
    async def start(self) -> None:
        """Start the collector."""
        pass
    
    @abstractmethod
    async def stop(self) -> None:
        """Stop the collector."""
        pass
    
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

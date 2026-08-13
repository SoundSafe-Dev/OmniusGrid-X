"""HTTP/REST API Collector for Edge Agent"""

from typing import Dict, Any, Optional
from datetime import datetime, timezone
import httpx
import asyncio
import structlog

from .base import BaseCollector

logger = structlog.get_logger()


class HTTPRestCollector(BaseCollector):
    """
    Collector for HTTP/REST APIs.
    
    Polls REST endpoints at configurable intervals.
    """
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.url = config.get("url")
        self.method = config.get("method", "GET")
        self.headers = config.get("headers", {})
        self.params = config.get("params", {})
        self.auth = config.get("auth")  # {"username": "...", "password": "..."}
        self.timeout = config.get("timeout", 30)
        self.poll_interval = config.get("poll_interval", 60)  # seconds
        self.client: Optional[httpx.AsyncClient] = None
        self._poll_task: Optional[asyncio.Task] = None
    
    async def start(self) -> None:
        """Start the HTTP collector."""
        await super().start()
        
        # Create HTTP client
        auth = None
        if self.auth:
            auth = httpx.BasicAuth(
                username=self.auth.get("username", ""),
                password=self.auth.get("password", "")
            )
        
        self.client = httpx.AsyncClient(
            timeout=self.timeout,
            auth=auth,
            headers=self.headers
        )
        
        # Start polling task
        self._poll_task = asyncio.create_task(self._poll_loop())
        
        logger.info(
            "http_collector_started",
            asset_id=self.asset_id,
            url=self.url,
            method=self.method,
            poll_interval=self.poll_interval
        )
    
    async def stop(self) -> None:
        """Stop the HTTP collector."""
        await super().stop()
        
        if self._poll_task:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass
        
        if self.client:
            await self.client.aclose()
        
        logger.info("http_collector_stopped", asset_id=self.asset_id)
    
    async def _poll_loop(self) -> None:
        """Poll the HTTP endpoint at configured intervals."""
        while self._running:
            try:
                await self._collect()
            except Exception as e:
                logger.error(
                    "http_poll_error",
                    asset_id=self.asset_id,
                    url=self.url,
                    error=str(e)
                )
            
            await asyncio.sleep(self.poll_interval)
    
    async def _collect(self) -> None:
        """Collect data from HTTP endpoint."""
        if not self.client:
            return
        
        try:
            response = await self.client.request(
                method=self.method,
                url=self.url,
                params=self.params
            )
            response.raise_for_status()
            
            data = response.json()
            
            # Normalize and emit data
            normalized = self._normalize_data(data)
            await self.emit(normalized)
            
            logger.debug(
                "http_data_collected",
                asset_id=self.asset_id,
                url=self.url,
                status_code=response.status_code
            )
            
        # COUNTED, NOT ONLY LOGGED (FS-691). A device answering 500 forever polls
        # cleanly forever: the task stays alive, so `connection_state` reads up; no
        # message reaches the coordinator, so nothing else moves. `record_failure`
        # is what makes the asset's silence visible as a number.
        except httpx.HTTPError as e:
            self.record_failure(
                "http_request_failed",
                url=self.url,
                error=str(e)
            )
        except Exception as e:
            self.record_failure(
                "http_collection_error",
                url=self.url,
                error=str(e)
            )
    
    def _normalize_data(self, data: Any) -> Dict[str, Any]:
        """
        Normalize HTTP response data to standard format.
        
        Args:
            data: Raw response data
            
        Returns:
            Normalized telemetry data
        """
        # AWARE UTC (FS-461) — see the note in ethernet_ip.py.
        timestamp = datetime.now(timezone.utc)
        
        # Handle different response structures
        if isinstance(data, dict):
            # If data is a dict, flatten it
            normalized = {
                "timestamp_edge": timestamp.isoformat(),
                "asset_id": self.asset_id,
                "topic": "telemetry",
                "payload": {}
            }
            
            for key, value in data.items():
                if isinstance(value, (int, float, str, bool)):
                    normalized["payload"][key] = value
                elif isinstance(value, dict):
                    # Flatten nested dicts
                    for sub_key, sub_value in value.items():
                        if isinstance(sub_value, (int, float, str, bool)):
                            normalized["payload"][f"{key}_{sub_key}"] = sub_value
            
            return normalized
        
        elif isinstance(data, list):
            # If data is a list, use first item or aggregate
            if len(data) > 0 and isinstance(data[0], dict):
                return self._normalize_data(data[0])
            else:
                return {
                    "timestamp_edge": timestamp.isoformat(),
                    "asset_id": self.asset_id,
                    "topic": "telemetry",
                    "payload": {"value": data}
                }
        
        else:
            return {
                "timestamp_edge": timestamp.isoformat(),
                "asset_id": self.asset_id,
                "topic": "telemetry",
                "payload": {"value": data}
            }

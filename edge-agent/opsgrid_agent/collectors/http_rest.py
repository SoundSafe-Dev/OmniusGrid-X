"""HTTP/REST API collector with observable, retryable poll outcomes."""

import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from urllib.parse import urlsplit, urlunsplit

import httpx
import structlog

from .. import metrics
from .base import BaseCollector

logger = structlog.get_logger()

COLLECTOR_TYPE = "http_rest"


def _safe_log_url(url: Any) -> str:
    """Return useful endpoint context without credentials, query, or fragment."""
    try:
        parsed = urlsplit(str(url or ""))
        hostname = parsed.hostname
        if not parsed.scheme or not hostname:
            return "<invalid-url>"
        if ":" in hostname:
            hostname = f"[{hostname}]"
        netloc = hostname
        if parsed.port is not None:
            netloc = f"{netloc}:{parsed.port}"
        return urlunsplit((parsed.scheme, netloc, parsed.path, "", ""))
    except (TypeError, ValueError):
        return "<invalid-url>"


class HTTPRestCollector(BaseCollector):
    """
    Collector for HTTP/REST APIs.
    
    Polls REST endpoints at configurable intervals.
    """
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.url = config.get("url")
        self._log_url = _safe_log_url(self.url)
        self.method = config.get("method", "GET")
        self.headers = config.get("headers", {})
        self.params = config.get("params", {})
        self.auth = config.get("auth")  # {"username": "...", "password": "..."}
        self.timeout = config.get("timeout", 30)
        self.poll_interval = config.get("poll_interval", 60)  # seconds
        self.client: Optional[httpx.AsyncClient] = None
        self._poll_task: Optional[asyncio.Task] = None
        self._poll_state = "starting"
        self._consecutive_failures = 0
        self._last_success_at: Optional[str] = None
        self._last_failure_at: Optional[str] = None
        self._last_failure_class: Optional[str] = None

    @property
    def health_status(self) -> Dict[str, Any]:
        """Bounded poll health exposed through the coordinator adapter."""
        healthy: Optional[bool]
        if self._poll_state == "healthy":
            healthy = True
        elif self._poll_state == "degraded":
            healthy = False
        else:
            healthy = None
        return {
            "state": self._poll_state,
            "healthy": healthy,
            "consecutive_failures": self._consecutive_failures,
            "last_success_at": self._last_success_at,
            "last_failure_at": self._last_failure_at,
            "last_failure_class": self._last_failure_class,
        }

    def _record_failure(
        self,
        failure_class: str,
        error: Exception,
        *,
        status_code: Optional[int] = None,
    ) -> None:
        first_failure = self._consecutive_failures == 0
        self._consecutive_failures += 1
        self._poll_state = "degraded"
        self._last_failure_at = datetime.now(timezone.utc).isoformat()
        self._last_failure_class = failure_class
        metrics.record_poll_failure(
            self.asset_id,
            COLLECTOR_TYPE,
            failure_class,
            self._consecutive_failures,
        )

        event = "http_poll_failed" if first_failure else "http_poll_still_failing"
        log = logger.warning if first_failure else logger.debug
        fields = {
            "asset_id": self.asset_id,
            "url": self._log_url,
            "failure_class": failure_class,
            "exception_type": type(error).__name__,
            "consecutive_failures": self._consecutive_failures,
        }
        if status_code is not None:
            fields["status_code"] = status_code
        log(event, **fields)

    def _record_success(self) -> None:
        recovered = self._consecutive_failures > 0
        previous_failure_class = self._last_failure_class
        self._consecutive_failures = 0
        self._poll_state = "healthy"
        self._last_success_at = datetime.now(timezone.utc).isoformat()
        metrics.record_poll_success(
            self.asset_id,
            COLLECTOR_TYPE,
            recovered=recovered,
        )
        if recovered:
            logger.info(
                "http_poll_recovered",
                asset_id=self.asset_id,
                url=self._log_url,
                previous_failure_class=previous_failure_class,
            )
    
    async def start(self) -> None:
        """Start the HTTP collector."""
        await super().start()
        self._poll_state = "starting"
        self._consecutive_failures = 0
        
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
            url=self._log_url,
            method=self.method,
            poll_interval=self.poll_interval
        )
    
    async def stop(self) -> None:
        """Stop the HTTP collector."""
        await super().stop()
        self._poll_state = "stopped"
        
        if self._poll_task:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass
        
        if self.client:
            await self.client.aclose()

        metrics.set_connection_state(self.asset_id, COLLECTOR_TYPE, up=False)
        
        logger.info("http_collector_stopped", asset_id=self.asset_id)
    
    async def _poll_loop(self) -> None:
        """Own cadence and classify unexpected collector bugs once."""
        while self._running:
            try:
                await self._collect()
            except Exception as error:
                # Request/status/decode failures are handled in `_collect` and
                # remain retryable. Anything reaching this boundary is an
                # unexpected programming/normalization failure: keep probing,
                # but make that distinct degraded state observable.
                self._record_failure("unexpected", error)
            
            await asyncio.sleep(self.poll_interval)
    
    async def _collect(self) -> bool:
        """Collect once, classifying expected operational failures."""
        if not self.client:
            return False
        
        try:
            response = await self.client.request(
                method=self.method,
                url=self.url,
                params=self.params
            )
        except httpx.HTTPStatusError as error:
            status_code = getattr(getattr(error, "response", None), "status_code", None)
            self._record_failure("http_status", error, status_code=status_code)
            return False
        except httpx.HTTPError as error:
            self._record_failure("transport", error)
            return False

        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as error:
            self._record_failure("http_status", error, status_code=response.status_code)
            return False

        try:
            data = response.json()
        except (ValueError, UnicodeError) as error:
            self._record_failure("decode", error)
            return False

        # Normalization/programming errors deliberately propagate to the poll
        # loop, where they receive the distinct `unexpected` policy.
        normalized = self._normalize_data(data)
        await self.emit(normalized)
        self._record_success()

        logger.debug(
            "http_data_collected",
            asset_id=self.asset_id,
            url=self._log_url,
            status_code=response.status_code
        )
        return True
    
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
                "collector_type": COLLECTOR_TYPE,
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
                    "collector_type": COLLECTOR_TYPE,
                    "topic": "telemetry",
                    "payload": {"value": data}
                }
        
        else:
            return {
                "timestamp_edge": timestamp.isoformat(),
                "asset_id": self.asset_id,
                "collector_type": COLLECTOR_TYPE,
                "topic": "telemetry",
                "payload": {"value": data}
            }

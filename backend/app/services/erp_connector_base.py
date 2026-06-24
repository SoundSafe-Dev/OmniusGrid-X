"""Common ERP connector primitives.

This module is intentionally small and dependency-light. The old ERP WIP branch
contained vendor-specific connectors, but the current task first needs a stable
base that connection tests and sync triggers can call consistently.
"""

from __future__ import annotations

import asyncio
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any

import aiohttp
import structlog

logger = structlog.get_logger()


class ERPType(str, Enum):
    """Supported ERP platforms."""

    SAP = "sap"
    ORACLE = "oracle"
    DYNAMICS = "dynamics"
    NETSUITE = "netsuite"
    ODOO = "odoo"
    INFOR = "infor"
    EPICOR = "epicor"
    GENERIC = "generic"


class AuthType(str, Enum):
    """Authentication types understood by the generic connector."""

    OAUTH2 = "oauth2"
    API_KEY = "api_key"
    CERTIFICATE = "certificate"
    BASIC = "basic"
    TOKEN = "token"
    NONE = "none"


@dataclass
class ERPConfig:
    """Runtime connector configuration built from IntegrationConfiguration."""

    erp_type: ERPType
    auth_type: AuthType
    base_url: str
    auth_config: dict[str, Any] = field(default_factory=dict)
    rate_limit: dict[str, int] = field(default_factory=dict)
    timeout: int = 30
    retry_config: dict[str, Any] = field(default_factory=dict)
    circuit_breaker: dict[str, Any] = field(default_factory=dict)
    extra_config: dict[str, Any] = field(default_factory=dict)


@dataclass
class CircuitBreakerState:
    failure_count: int = 0
    last_failure_time: datetime | None = None
    state: str = "closed"


class ERPConnectorBase(ABC):
    """Base class for ERP connectors with retry, rate limit, and health hooks."""

    def __init__(self, config: ERPConfig, organization_id: str, integration_id: str):
        self.config = config
        self.organization_id = organization_id
        self.integration_id = integration_id
        self.circuit_breaker = CircuitBreakerState()
        self._auth_token: str | None = None
        self._token_expiry: datetime | None = None
        self._request_timestamps: list[float] = []

        self.retry_config = {
            "max_retries": 3,
            "backoff_multiplier": 2.0,
            "initial_delay": 1.0,
            **(config.retry_config or {}),
        }
        self.circuit_breaker_config = {
            "failure_threshold": 5,
            "recovery_timeout": 60,
            **(config.circuit_breaker or {}),
        }
        rate_limit = config.rate_limit or {}
        self.rate_limit_per_minute = int(rate_limit.get("requests_per_minute", 60))
        self.burst_limit = int(rate_limit.get("burst_limit", 10))

    @abstractmethod
    async def authenticate(self) -> str | None:
        """Authenticate with the ERP system."""

    @abstractmethod
    async def fetch_data(
        self,
        entity_type: str,
        filters: dict[str, Any] | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch entity data from the ERP system."""

    @abstractmethod
    async def health_check(self) -> dict[str, Any]:
        """Perform a connection health check."""

    async def execute_with_retry(self, operation, *args, **kwargs) -> Any:
        """Run an async operation with rate limiting, retry, and circuit breaker."""

        max_retries = int(kwargs.pop("max_retries", self.retry_config["max_retries"]))
        initial_delay = float(self.retry_config["initial_delay"])
        multiplier = float(self.retry_config["backoff_multiplier"])

        last_exception: Exception | None = None
        for attempt in range(max_retries + 1):
            try:
                if not self._circuit_breaker_allows_request():
                    raise RuntimeError("ERP connector circuit breaker is open")

                await self._rate_limit()
                result = await operation(*args, **kwargs)
                self._record_success()
                return result
            except Exception as exc:
                last_exception = exc
                if not self._is_transient_error(exc):
                    raise

                self._record_failure()
                if attempt >= max_retries:
                    raise

                delay = initial_delay * (multiplier ** attempt)
                logger.warning(
                    "erp_operation_retrying",
                    integration_id=self.integration_id,
                    attempt=attempt + 1,
                    max_retries=max_retries,
                    delay=delay,
                    error=str(exc),
                )
                await asyncio.sleep(delay)

        if last_exception:
            raise last_exception
        raise RuntimeError("ERP operation failed without an exception")

    async def get_auth_token(self) -> str | None:
        """Return a cached token or authenticate when needed."""

        if self._auth_token and self._token_expiry:
            if datetime.utcnow() < self._token_expiry:
                return self._auth_token

        self._auth_token = await self.authenticate()
        self._token_expiry = datetime.utcnow() + timedelta(hours=1)
        return self._auth_token

    def validate_config(self) -> bool:
        """Validate the common config fields before network work starts."""

        if not self.config.base_url:
            return False
        if self.config.auth_type == AuthType.API_KEY:
            return bool(self.config.auth_config.get("api_key"))
        if self.config.auth_type == AuthType.BASIC:
            return bool(
                self.config.auth_config.get("username")
                and self.config.auth_config.get("password")
            )
        if self.config.auth_type in {AuthType.TOKEN, AuthType.OAUTH2}:
            return bool(
                self.config.auth_config.get("access_token")
                or self.config.auth_config.get("token")
            )
        return True

    async def close(self) -> None:
        """Hook for connectors with persistent resources."""

    async def _rate_limit(self) -> None:
        now = time.time()
        self._request_timestamps = [
            ts for ts in self._request_timestamps if now - ts < 60
        ]

        if len(self._request_timestamps) >= self.rate_limit_per_minute:
            wait_time = 60 - (now - self._request_timestamps[0])
            await asyncio.sleep(max(wait_time, 0))

        recent = [ts for ts in self._request_timestamps if now - ts < 1]
        if len(recent) >= self.burst_limit:
            wait_time = 1 - (now - recent[0])
            await asyncio.sleep(max(wait_time, 0))

        self._request_timestamps.append(time.time())

    def _circuit_breaker_allows_request(self) -> bool:
        if self.circuit_breaker.state == "closed":
            return True
        if self.circuit_breaker.state == "half_open":
            return True
        if not self.circuit_breaker.last_failure_time:
            return False
        elapsed = (datetime.utcnow() - self.circuit_breaker.last_failure_time).total_seconds()
        if elapsed > int(self.circuit_breaker_config["recovery_timeout"]):
            self.circuit_breaker.state = "half_open"
            return True
        return False

    def _record_failure(self) -> None:
        self.circuit_breaker.failure_count += 1
        self.circuit_breaker.last_failure_time = datetime.utcnow()
        if self.circuit_breaker.failure_count >= int(
            self.circuit_breaker_config["failure_threshold"]
        ):
            self.circuit_breaker.state = "open"

    def _record_success(self) -> None:
        self.circuit_breaker.failure_count = 0
        self.circuit_breaker.last_failure_time = None
        self.circuit_breaker.state = "closed"

    def _is_transient_error(self, error: Exception) -> bool:
        message = str(error).lower()
        if any(code in message for code in ("400", "401", "403", "404")):
            return False
        return any(
            marker in message
            for marker in (
                "timeout",
                "connection",
                "429",
                "500",
                "502",
                "503",
                "504",
                "temporarily",
                "unavailable",
            )
        )


class GenericRESTERPConnector(ERPConnectorBase):
    """Generic REST connector used until vendor-specific connectors are revived."""

    async def authenticate(self) -> str | None:
        if self.config.auth_type in {AuthType.TOKEN, AuthType.OAUTH2}:
            return self.config.auth_config.get("access_token") or self.config.auth_config.get("token")
        if self.config.auth_type == AuthType.API_KEY:
            return self.config.auth_config.get("api_key")
        return None

    async def health_check(self) -> dict[str, Any]:
        endpoint = (
            self.config.extra_config.get("health_check_path")
            or self.config.extra_config.get("health_check_url")
            or ""
        )
        url = endpoint if str(endpoint).startswith("http") else self._join_url(endpoint)

        try:
            async def _check() -> dict[str, Any]:
                async with aiohttp.ClientSession(timeout=self._timeout()) as session:
                    async with session.get(url, headers=await self._headers()) as response:
                        text = await response.text()
                        if 200 <= response.status < 300:
                            return {
                                "status": "healthy",
                                "status_code": response.status,
                                "message": "ERP connection successful",
                                "checked_at": datetime.utcnow().isoformat(),
                            }
                        return {
                            "status": "unhealthy",
                            "status_code": response.status,
                            "message": text[:500],
                            "checked_at": datetime.utcnow().isoformat(),
                        }

            return await self.execute_with_retry(_check)
        except Exception as exc:
            return {
                "status": "unhealthy",
                "message": str(exc),
                "checked_at": datetime.utcnow().isoformat(),
            }

    async def fetch_data(
        self,
        entity_type: str,
        filters: dict[str, Any] | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        path_template = self.config.extra_config.get("entity_path_template", "/{entity_type}")
        path = str(path_template).format(entity_type=entity_type.strip("/"))
        url = self._join_url(path)
        params: dict[str, Any] = dict(filters or {})
        if limit is not None:
            params.setdefault("limit", limit)

        async def _fetch() -> list[dict[str, Any]]:
            async with aiohttp.ClientSession(timeout=self._timeout()) as session:
                async with session.get(
                    url,
                    headers=await self._headers(),
                    params=params,
                ) as response:
                    body = await response.text()
                    if response.status < 200 or response.status >= 300:
                        raise RuntimeError(f"ERP fetch failed: {response.status} - {body[:500]}")
                    payload = await response.json()
                    if isinstance(payload, list):
                        return [item for item in payload if isinstance(item, dict)]
                    if isinstance(payload, dict):
                        for key in ("items", "results", "value", "data"):
                            value = payload.get(key)
                            if isinstance(value, list):
                                return [item for item in value if isinstance(item, dict)]
                    return []

        return await self.execute_with_retry(_fetch)

    async def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        token = await self.get_auth_token()

        if self.config.auth_type in {AuthType.TOKEN, AuthType.OAUTH2} and token:
            headers["Authorization"] = f"Bearer {token}"
        elif self.config.auth_type == AuthType.API_KEY and token:
            header_name = self.config.auth_config.get("header_name", "X-API-Key")
            prefix = self.config.auth_config.get("prefix", "")
            headers[header_name] = f"{prefix}{token}" if prefix else token

        headers.update(self.config.extra_config.get("headers", {}))
        return headers

    def _timeout(self) -> aiohttp.ClientTimeout:
        return aiohttp.ClientTimeout(total=self.config.timeout)

    def _join_url(self, path: str) -> str:
        base = self.config.base_url.rstrip("/")
        clean_path = str(path or "").strip("/")
        return f"{base}/{clean_path}" if clean_path else base

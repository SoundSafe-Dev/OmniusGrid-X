"""
ERP Connector Base Class

Abstract base class for all ERP connectors providing common functionality:
- Authentication handling (OAuth2, API keys, certificates)
- Rate limiting and retry logic
- Error handling and logging
- Health check endpoints
- Configuration validation
- Circuit breaker pattern
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta, timezone
import asyncio
import time
import structlog
from dataclasses import dataclass, field
from enum import Enum

logger = structlog.get_logger()


class ERPType(Enum):
    """Supported ERP platforms"""
    SAP = "sap"
    ORACLE = "oracle"
    DYNAMICS = "dynamics"
    NETSUITE = "netsuite"
    ODOO = "odoo"
    INFOR = "infor"
    EPICOR = "epicor"
    GENERIC = "generic"


class AuthType(Enum):
    """Authentication types"""
    OAUTH2 = "oauth2"
    API_KEY = "api_key"
    CERTIFICATE = "certificate"
    BASIC = "basic"
    TOKEN = "token"


class ProcessingStatus(Enum):
    """Event processing status"""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    RETRYING = "retrying"


@dataclass
class ERPConfig:
    """ERP connector configuration"""
    erp_type: ERPType
    auth_type: AuthType
    base_url: str
    auth_config: Dict[str, Any]
    rate_limit: Dict[str, int]
    timeout: int = 30
    retry_config: Optional[Dict[str, Any]] = None
    circuit_breaker: Optional[Dict[str, Any]] = None
    # Connector-specific settings bag (company_id, account_id, realm, tenant_id,
    # service_path, ...). Each concrete connector reads the keys it needs.
    configuration: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CircuitBreakerState:
    """Circuit breaker state"""
    failure_count: int = 0
    last_failure_time: Optional[datetime] = None
    state: str = "closed"  # closed, open, half_open


class ERPConnectorBase(ABC):
    """
    Abstract base class for ERP connectors.
    
    All ERP connectors must inherit from this class and implement
    the abstract methods while inheriting common functionality.
    """
    
    def __init__(self, config: ERPConfig, organization_id: str, integration_id: str):
        self.config = config
        self.organization_id = organization_id
        self.integration_id = integration_id
        self.circuit_breaker = CircuitBreakerState()
        self._auth_token: Optional[str] = None
        self._token_expiry: Optional[datetime] = None
        
        # Initialize retry config with defaults
        self.retry_config = config.retry_config or {
            "max_retries": 3,
            "backoff_multiplier": 2.0,
            "initial_delay": 1.0
        }
        
        # Initialize circuit breaker config with defaults
        self.circuit_breaker_config = config.circuit_breaker or {
            "failure_threshold": 5,
            "recovery_timeout": 60
        }
        
        # Rate limiting
        self._request_timestamps: List[float] = []
        self.rate_limit_per_minute = config.rate_limit.get("requests_per_minute", 60)
        self.burst_limit = config.rate_limit.get("burst_limit", 10)
        
        logger.info(
            "erp_connector_initialized",
            erp_type=config.erp_type.value,
            organization_id=organization_id,
            integration_id=integration_id
        )
    
    @abstractmethod
    async def authenticate(self) -> str:
        """
        Authenticate with the ERP system and return access token.
        
        Returns:
            str: Access token or authentication credential
        """
        pass
    
    @abstractmethod
    async def fetch_data(
        self,
        entity_type: str,
        filters: Optional[Dict[str, Any]] = None,
        limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Fetch data from ERP system.
        
        Args:
            entity_type: Type of entity to fetch (e.g., 'PurchaseOrder', 'Invoice')
            filters: Optional filters to apply
            limit: Optional limit on number of records
            
        Returns:
            List of entity data dictionaries
        """
        pass
    
    @abstractmethod
    async def subscribe_to_events(self, event_types: List[str]) -> bool:
        """
        Subscribe to real-time events from ERP system.
        
        Args:
            event_types: List of event types to subscribe to
            
        Returns:
            bool: Success status
        """
        pass
    
    @abstractmethod
    async def health_check(self) -> Dict[str, Any]:
        """
        Perform health check on ERP connection.
        
        Returns:
            Dict with health status and details
        """
        pass
    
    async def execute_with_retry(
        self,
        operation,
        *args,
        max_retries: Optional[int] = None,
        **kwargs
    ) -> Any:
        """
        Execute operation with exponential backoff retry logic.
        
        Args:
            operation: Async function to execute
            args: Positional arguments for operation
            max_retries: Override default max retries
            kwargs: Keyword arguments for operation
            
        Returns:
            Result of operation
            
        Raises:
            Exception: If all retries exhausted
        """
        max_retries = max_retries or self.retry_config["max_retries"]
        initial_delay = self.retry_config["initial_delay"]
        backoff_multiplier = self.retry_config["backoff_multiplier"]
        
        last_exception = None
        
        for attempt in range(max_retries + 1):
            try:
                # Check circuit breaker
                if not self._circuit_breaker_check():
                    raise Exception("Circuit breaker is OPEN, requests blocked")
                
                # Check rate limit
                await self._rate_limit_check()
                
                # Execute operation
                result = await operation(*args, **kwargs)
                
                # Reset circuit breaker on success
                self._circuit_breaker_reset()
                
                logger.debug(
                    "operation_succeeded",
                    operation=operation.__name__,
                    attempt=attempt
                )
                
                return result
                
            except Exception as e:
                last_exception = e
                
                # Check if error is transient (retryable)
                if not self._is_transient_error(e):
                    logger.error(
                        "non_transient_error",
                        operation=operation.__name__,
                        error=str(e),
                        error_type=type(e).__name__
                    )
                    raise
                
                # Increment circuit breaker failure count
                self._circuit_breaker_record_failure()
                
                if attempt < max_retries:
                    delay = initial_delay * (backoff_multiplier ** attempt)
                    logger.warning(
                        "operation_failed_retrying",
                        operation=operation.__name__,
                        attempt=attempt,
                        max_retries=max_retries,
                        delay=delay,
                        error=str(e)
                    )
                    await asyncio.sleep(delay)
                else:
                    logger.error(
                        "operation_failed_all_retries_exhausted",
                        operation=operation.__name__,
                        max_retries=max_retries,
                        error=str(e)
                    )
                    raise
        
        raise last_exception
    
    async def _rate_limit_check(self):
        """Check and enforce rate limiting"""
        now = time.time()
        
        # Remove timestamps older than 1 minute
        self._request_timestamps = [
            ts for ts in self._request_timestamps
            if now - ts < 60
        ]
        
        # Check per-minute limit
        if len(self._request_timestamps) >= self.rate_limit_per_minute:
            wait_time = 60 - (now - self._request_timestamps[0])
            logger.warning(
                "rate_limit_exceeded",
                wait_time=wait_time,
                requests_in_minute=len(self._request_timestamps)
            )
            await asyncio.sleep(wait_time)
        
        # Check burst limit (requests in last second)
        recent_requests = [
            ts for ts in self._request_timestamps
            if now - ts < 1
        ]
        if len(recent_requests) >= self.burst_limit:
            wait_time = 1 - (now - recent_requests[0])
            await asyncio.sleep(wait_time)
        
        # Record this request
        self._request_timestamps.append(now)
    
    def _circuit_breaker_check(self) -> bool:
        """Check if circuit breaker allows requests"""
        if self.circuit_breaker.state == "closed":
            return True
        
        if self.circuit_breaker.state == "open":
            # Check if recovery timeout has passed
            if self.circuit_breaker.last_failure_time:
                time_since_failure = (
                    datetime.now(timezone.utc) - self.circuit_breaker.last_failure_time
                ).total_seconds()
                
                if time_since_failure > self.circuit_breaker_config["recovery_timeout"]:
                    # Transition to half-open
                    self.circuit_breaker.state = "half_open"
                    logger.info("circuit_breaker_half_open")
                    return True
            
            return False
        
        if self.circuit_breaker.state == "half_open":
            return True
        
        return False
    
    def _circuit_breaker_record_failure(self):
        """Record a failure in circuit breaker"""
        self.circuit_breaker.failure_count += 1
        self.circuit_breaker.last_failure_time = datetime.now(timezone.utc)
        
        threshold = self.circuit_breaker_config["failure_threshold"]
        
        if self.circuit_breaker.failure_count >= threshold:
            self.circuit_breaker.state = "open"
            logger.error(
                "circuit_breaker_opened",
                failure_count=self.circuit_breaker.failure_count,
                threshold=threshold
            )
    
    def _circuit_breaker_reset(self):
        """Reset circuit breaker on success"""
        if self.circuit_breaker.state == "half_open":
            self.circuit_breaker.state = "closed"
            self.circuit_breaker.failure_count = 0
            logger.info("circuit_breaker_closed")
    
    def _is_transient_error(self, error: Exception) -> bool:
        """
        Determine if an error is transient (retryable).
        
        Args:
            error: Exception to check
            
        Returns:
            bool: True if error is transient
        """
        error_type = type(error).__name__
        error_msg = str(error).lower()
        
        # Network errors
        transient_types = [
            "ConnectionError",
            "TimeoutError",
            "HTTPError",
            "RequestException"
        ]
        
        if error_type in transient_types:
            return True
        
        # Rate limit errors
        if "rate limit" in error_msg or "429" in error_msg:
            return True
        
        # Timeout errors
        if "timeout" in error_msg:
            return True
        
        # Service unavailable
        if "503" in error_msg or "service unavailable" in error_msg:
            return True
        
        # Authentication errors are not transient
        if "401" in error_msg or "unauthorized" in error_msg:
            return False
        
        # Not found errors are not transient
        if "404" in error_msg or "not found" in error_msg:
            return False
        
        # Default to transient for unknown errors
        return True
    
    def log_request(self, request: Dict[str, Any], response: Optional[Dict[str, Any]] = None):
        """
        Log request and response for audit trail.
        
        Args:
            request: Request details
            response: Optional response details
        """
        log_data = {
            "organization_id": self.organization_id,
            "integration_id": self.integration_id,
            "erp_type": self.config.erp_type.value,
            "request": request,
            "response": response
        }
        
        logger.info("erp_request_log", **log_data)
    
    def validate_config(self) -> bool:
        """
        Validate connector configuration.
        
        Returns:
            bool: True if configuration is valid
        """
        required_fields = ["base_url", "auth_type"]
        
        for field in required_fields:
            if not hasattr(self.config, field) or not getattr(self.config, field):
                logger.error(
                    "config_validation_failed",
                    missing_field=field
                )
                return False
        
        # Validate auth config based on auth type
        if self.config.auth_type == AuthType.OAUTH2:
            required_auth_fields = ["client_id", "client_secret", "token_url"]
        elif self.config.auth_type == AuthType.API_KEY:
            required_auth_fields = ["api_key"]
        elif self.config.auth_type == AuthType.BASIC:
            required_auth_fields = ["username", "password"]
        else:
            required_auth_fields = []
        
        for field in required_auth_fields:
            if field not in self.config.auth_config:
                logger.error(
                    "auth_config_validation_failed",
                    missing_field=field,
                    auth_type=self.config.auth_type.value
                )
                return False
        
        logger.info("config_validation_passed")
        return True
    
    async def get_auth_token(self) -> str:
        """
        Get valid authentication token, refreshing if necessary.
        
        Returns:
            str: Valid authentication token
        """
        # Check if token is still valid
        if self._auth_token and self._token_expiry:
            if datetime.now(timezone.utc) < self._token_expiry:
                return self._auth_token
        
        # Authenticate to get new token
        self._auth_token = await self.authenticate()
        
        # Set expiry (default 1 hour from now)
        self._token_expiry = datetime.now(timezone.utc) + timedelta(hours=1)
        
        return self._auth_token
    
    async def close(self):
        """Clean up resources when closing connector"""
        logger.info(
            "erp_connector_closing",
            erp_type=self.config.erp_type.value,
            integration_id=self.integration_id
        )

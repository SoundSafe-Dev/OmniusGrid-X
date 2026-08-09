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
    INTUIT = "intuit"        # QuickBooks Online
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

    def __post_init__(self):
        """Normalize `base_url` so a trailing slash cannot break every request.

        Five connectors build their endpoint by concatenating `base_url` with a
        path (`f"{config.base_url}/api/v1"`), so a configured value of
        `https://host/` yields `https://host//api/v1`. yarl preserves the empty
        segment verbatim, the server sees `//api/v1`, and the result is a 404 that
        looks like a wrong entity or a missing service — not like a stray slash in
        configuration. Trailing slashes on a base URL are one of the most common
        ways a human writes one, so this is normalized once here rather than
        remembered at six call sites.

        Found by pointing the SAP connector at a Prism mock generated from real
        SAP EDMX: the request arrived as `//A_PurchaseOrder` and matched no route.
        """
        if isinstance(self.base_url, str):
            self.base_url = self.base_url.strip().rstrip("/")


@dataclass
class CircuitBreakerState:
    """Circuit breaker state"""
    failure_count: int = 0
    last_failure_time: Optional[datetime] = None
    state: str = "closed"  # closed, open, half_open


class ERPWriteNotSupported(Exception):
    """This connector cannot write to its ERP, and says so rather than pretending.

    Caught by the posting drainer, which turns the posting into a `manual_required` item
    carrying an instruction — the analog path — instead of leaving it queued forever behind
    an integration that will never take it.
    """


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
        
        # Serialises authentication and rate-limit bookkeeping. Created here rather
        # than lazily: asyncio.Lock() no longer binds to a loop at construction
        # (3.10+), so this is safe even though __init__ runs outside the loop.
        self._auth_lock = asyncio.Lock()
        self._rate_limit_lock = asyncio.Lock()

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
    
    #: How real-time events are ACTUALLY subscribed to for this vendor, when it is
    #: not something this connector can do over the API. Prose, aimed at whoever has
    #: to set it up. `None` means the connector implements a verified subscription.
    EVENT_SUBSCRIPTION_MECHANISM: Optional[str] = (
        "no verified event-subscription path for this connector"
    )

    async def subscribe_to_events(self, event_types: List[str]) -> bool:
        """Report honestly that no verified subscription path exists.

        THE DEFECT THIS REPLACES, PROVEN AGAINST A REAL SERVER.

        All seven original connectors carried the same copy-pasted implementation:
        POST to a `/webhooks`-shaped URL with a `{name, url, event_type}` body. The
        payloads were byte-identical across seven unrelated vendors, so at most one
        of them could have been right. None was.

        Run against the live Odoo container, `subscribe_to_events` returned **True**.
        `POST /webhooks` is a 404 on Odoo. What actually happened is worse: the
        connector's URL resolved to `/xmlrpc/2/webhooks`, Odoo's `/xmlrpc/2/<...>`
        route matches anything, and it answered **HTTP 200 with an XML-RPC fault
        body containing a traceback**. The connector checked only
        `status not in (200, 201)`, saw 200, and reported success for a subscription
        that was never created.

        That is the same Odoo trap already fixed on the read path -- application
        faults arrive in the BODY with HTTP 200 -- surviving in a code path nobody
        had exercised, and it is the worst failure shape available: an operator
        enables real-time ERP events, the platform confirms it, and no event ever
        arrives, with no error anywhere to look at.

        So connectors now DECLARE the real mechanism instead of inventing an
        endpoint. Returning False is not a regression: there was never a working
        subscription to lose. A connector that gains a verified implementation
        overrides this method and sets EVENT_SUBSCRIPTION_MECHANISM to None.
        """
        logger.warning(
            "erp_event_subscription_not_available_via_api",
            erp_type=self.config.erp_type.value,
            integration_id=self.integration_id,
            requested=event_types,
            mechanism=self.EVENT_SUBSCRIPTION_MECHANISM,
        )
        return False


    #: How this connector WRITES an event back into the ERP, when it can. Prose, aimed at
    #: whoever has to set it up. `None` means the connector implements a verified write.
    #:
    #: Same discipline as EVENT_SUBSCRIPTION_MECHANISM directly above, and for the same
    #: reason: the read path was one-directional for this connector's whole life, and the
    #: tempting way to "add writes" is a copy-pasted POST to a plausible-looking URL. That is
    #: precisely what produced a subscription that reported success against a 404.
    WRITE_MECHANISM: Optional[str] = "no verified write path for this connector"

    async def post_event(
        self,
        event_type: str,
        payload: Dict[str, Any],
    ) -> str:
        """Write one platform event into the ERP and RETURN ITS IDENTIFIER.

        The return value is not decorative. A posting in `system_of_record_postings` cannot
        be marked `posted` without it — the database enforces that (migration 060) — because
        the identifier the far system hands back is the only evidence the write landed. A
        connector that "succeeds" without one has told us nothing checkable.

        THE DEFAULT IS A REFUSAL, NOT A NO-OP. No connector in this repository has a
        verified write path today; `fetch_data`, `subscribe_to_events` and `health_check`
        were the entire interface. Raising here means the drainer converts the posting to
        `manual_required` with an instruction for a person, which is true and actionable.
        Returning a fabricated reference, or silently doing nothing and reporting success,
        would put an unpostable obligation into a queue that looks drained.

        A connector that gains a real write overrides this and sets WRITE_MECHANISM to None.
        """
        logger.warning(
            "erp_write_not_available_via_api",
            erp_type=self.config.erp_type.value,
            integration_id=self.integration_id,
            event_type=event_type,
            mechanism=self.WRITE_MECHANISM,
        )
        raise ERPWriteNotSupported(
            f"{self.config.erp_type.value} has {self.WRITE_MECHANISM}"
        )

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
        """Reserve a slot in the sliding window, waiting until one is free.

        TWO DEFECTS THIS REPLACES, both measured rather than reasoned about.

        1. CONCURRENT CALLERS STAMPEDED. The old version computed a wait, slept, and
           proceeded -- with no lock and no re-check. So every waiting coroutine
           computed the same deadline, slept in parallel, and then all fired at
           once. Measured: 100 operations against a 10-per-minute limit completed in
           60 seconds. Ten times the configured rate, which is how an integration
           collects a vendor-side throttle from the component whose entire job is
           preventing that.

        2. THE RECORDED TIMESTAMP WAS STALE. `now` was captured before sleeping and
           appended after, so a request that waited 60 seconds recorded itself as
           having happened 60 seconds ago -- already outside its own window. The
           limiter therefore under-counted its own traffic, compounding (1).

        Now the check and the reservation happen together under a lock, the sleep
        happens outside it (so a waiter never blocks a caller who could proceed),
        and the loop re-checks rather than trusting a stale deadline.
        """
        while True:
            async with self._rate_limit_lock:
                now = time.time()
                self._request_timestamps = [
                    ts for ts in self._request_timestamps if now - ts < 60
                ]

                if len(self._request_timestamps) >= self.rate_limit_per_minute:
                    wait_time = 60 - (now - self._request_timestamps[0])
                    logger.warning(
                        "rate_limit_exceeded",
                        wait_time=wait_time,
                        requests_in_minute=len(self._request_timestamps),
                    )
                else:
                    recent_requests = [
                        ts for ts in self._request_timestamps if now - ts < 1
                    ]
                    if len(recent_requests) < self.burst_limit:
                        # Reserve the slot while still holding the lock, stamped
                        # with the CURRENT time.
                        self._request_timestamps.append(now)
                        return
                    wait_time = 1 - (now - recent_requests[0])

            # Sleep outside the lock. The floor keeps a rounding error from
            # spinning; the loop re-evaluates rather than assuming one wait is
            # enough, because another coroutine may take the slot first.
            await asyncio.sleep(max(wait_time, 0.001))

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
        
        # Authentication and authorization failures are PERMANENT.
        #
        # This list used to be just 401/unauthorized, while AUTH_ERROR_MARKERS a few
        # lines above already knew about 403, invalid_client and friends -- so the
        # health probe classified an error as an auth failure while the retry loop
        # classified the same error as transient and retried it three times with
        # exponential backoff.
        #
        # Two reasons that is worse than merely wasteful:
        #
        #   - Retrying cannot help. The token is captured in the operation's closure
        #     before the retry loop runs, so every attempt replays the SAME rejected
        #     credential. Seven seconds to reach the identical answer.
        #   - It hammers the provider's token endpoint with a credential that will
        #     never work, which is how an integration earns a rate-limit block on top
        #     of its original problem.
        #
        # `invalid_grant` specifically is what a lost rotated refresh token looks
        # like on Intuit, where refresh tokens rotate on every use and the previous
        # one is retired. It is as permanent as a failure gets.
        permanent_auth_markers = (
            "401", "unauthorized",
            "403", "forbidden", "access denied",
            "invalid_grant", "invalid_client", "invalid_token",
            "invalid credentials", "invalid apikey",
        )
        if any(marker in error_msg for marker in permanent_auth_markers):
            return False

        # Not found errors are not transient
        if "404" in error_msg or "not found" in error_msg:
            return False

        # Default to transient for unknown errors.
        #
        # Deliberately NOT including 400 here: a malformed query is permanent, but
        # some vendors return 400 for conditions that do clear, and defaulting a
        # whole status class to permanent would stop retrying things that should be
        # retried. The auth markers above are the cases that are unambiguously final.
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
        
        # `field_name`, not `field`: the latter shadows dataclasses.field, imported
        # at module scope and used by ERPConfig.
        for field_name in required_fields:
            if not hasattr(self.config, field_name) or not getattr(self.config, field_name):
                logger.error(
                    "config_validation_failed",
                    missing_field=field_name
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
        
        for field_name in required_auth_fields:
            if field_name not in self.config.auth_config:
                logger.error(
                    "auth_config_validation_failed",
                    missing_field=field_name,
                    auth_type=self.config.auth_type.value
                )
                return False
        
        logger.info("config_validation_passed")
        return True
    
    #: Used only when a connector cannot tell us the real lifetime. Deliberately
    #: short: over-refreshing costs one extra token request, while over-trusting a
    #: guessed lifetime serves dead credentials until it expires.
    DEFAULT_TOKEN_LIFETIME_SECONDS = 3600

    #: Refresh this many seconds BEFORE the provider's stated expiry. A token that
    #: expires mid-flight produces a 401 on a request that was valid when it was
    #: built, which surfaces as a random intermittent failure rather than an auth
    #: problem.
    TOKEN_REFRESH_SKEW_SECONDS = 60

    def _set_token(self, token: str, expires_in: Optional[float] = None) -> None:
        """Cache a token against the provider's OWN expiry.

        ``expires_in`` is the lifetime in seconds as reported by the token
        endpoint. Connectors that authenticate with a non-expiring credential
        (NetSuite TBA signs each request rather than issuing a token) pass None and
        get the conservative default.
        """
        self._auth_token = token
        lifetime = self.DEFAULT_TOKEN_LIFETIME_SECONDS if expires_in is None else float(expires_in)
        # Never let the skew produce an already-expired token for a short-lived one.
        effective = max(lifetime - self.TOKEN_REFRESH_SKEW_SECONDS, lifetime * 0.5)
        self._token_expiry = datetime.now(timezone.utc) + timedelta(seconds=effective)

    def invalidate_token(self) -> None:
        """Drop the cached token so the next call re-authenticates.

        Call this on a 401: the provider has decided the token is dead regardless
        of what its stated expiry claimed, and retrying with the same token just
        burns the retry budget.
        """
        self._auth_token = None
        self._token_expiry = None

    async def verify_credentials(self) -> None:
        """Prove the credential actually works, raising if it does not.

        The default delegates to `get_auth_token()`, which is a real round trip for
        OAuth2 connectors — a bad client_secret fails at the token endpoint.

        It is NOT sufficient for STATIC-credential connectors. Odoo and Epicor
        accept a long-lived API key, and for those `authenticate()` simply returns
        the value out of config without contacting anything, so a wrong key
        "authenticates" fine and only fails later on the first real call. Those
        connectors override this with something that round-trips.

        Found empirically: a deliberately wrong Odoo API key was reported DEGRADED
        rather than UNHEALTHY, because the probe below trusted get_auth_token().
        """
        await self.get_auth_token()

    #: Substrings that mark a fetch failure as an AUTH problem rather than a
    #: missing entity. Used as a backstop for static-credential connectors whose
    #: verify_credentials cannot round-trip: a 401 on the probe is an outage, not a
    #: module that is not installed.
    AUTH_ERROR_MARKERS = (
        "401", "403", "unauthorized", "forbidden", "invalid apikey", "invalid_client",
        "access denied", "authentication", "invalid credentials", "expired",
    )

    def _looks_like_auth_failure(self, error: str) -> bool:
        lowered = error.lower()
        return any(marker in lowered for marker in self.AUTH_ERROR_MARKERS)

    #: Exception types and message fragments that mean "we never reached the
    #: system", as opposed to "the system answered and declined". The distinction is
    #: the difference between paging someone and not.
    TRANSPORT_ERROR_MARKERS = (
        "cannot connect to host", "connection refused", "connection reset",
        "connection aborted", "server disconnected", "timeout", "timed out",
        "name or service not known", "temporary failure in name resolution",
        "nodename nor servname", "network is unreachable", "no route to host",
        "certificate verify failed", "ssl:",
    )

    def _looks_like_transport_failure(self, exc: Exception) -> bool:
        """Did we fail to reach the system at all?

        Checked by exception TYPE first, because aiohttp's connector errors carry
        the most reliable signal, then by message as a backstop for connectors that
        re-raise as a plain Exception (most of ours do).
        """
        import asyncio

        try:
            import aiohttp

            if isinstance(exc, (aiohttp.ClientConnectionError, aiohttp.ServerTimeoutError)):
                return True
        except ImportError:  # pragma: no cover - aiohttp is a hard dependency
            pass

        if isinstance(exc, (asyncio.TimeoutError, OSError, ConnectionError)):
            return True

        message = str(exc).lower()
        return any(marker in message for marker in self.TRANSPORT_ERROR_MARKERS)

    async def probe_health(
        self,
        entity_type: str,
        *,
        details: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Health check that separates "broken" from "that module is not installed".

        THE DEFECT THIS FIXES. Every connector's health check did
        `fetch_data(<business entity>, limit=1)` and mapped ANY exception to
        `unhealthy` — Epicor probed `Erp.BO.InvoiceSvc`, NetSuite `invoice`, SAP
        `PurchaseOrder`, Oracle `invoices`, Infor `invoice`. So a tenant that has
        not licensed or enabled that module had a perfectly working integration
        reported permanently unhealthy, because "the credential is wrong", "the host
        is unreachable" and "that entity does not exist here" all produced the same
        answer.

        Confirmed empirically against a real Odoo, where probing `sale.order` failed
        purely because the Sales module was not installed.

        The fix does not require knowing each vendor's universally-present entity —
        which we cannot know without their sandboxes. It reports WHICH failure
        happened:

            unhealthy  cannot reach the system or cannot authenticate. The
                       integration is broken and needs attention.
            degraded   authenticated fine, but the probe entity was unavailable.
                       The connection works; that entity/module may simply not be
                       present. Not an outage.
            healthy    authenticated and the entity answered.

        A monitor should page on `unhealthy`, not on `degraded`.
        """
        base: Dict[str, Any] = {
            "erp_type": self.config.erp_type.value,
            "integration_id": self.integration_id,
            "checked_at": datetime.now(timezone.utc).isoformat(),
            **(details or {}),
        }

        # Step 1: can we authenticate at all? This is the question that actually
        # determines whether the integration is broken.
        try:
            await self.verify_credentials()
        except Exception as exc:  # noqa: BLE001
            return {
                **base,
                "status": "unhealthy",
                "message": f"authentication failed: {exc}",
                "failure": "authentication",
            }

        # Step 2: probe an entity. A failure here is NOT necessarily an outage.
        try:
            await self.fetch_data(entity_type, limit=1)
        except Exception as exc:  # noqa: BLE001
            # Backstop for static-credential connectors: if the probe failed for an
            # AUTH reason, that is an outage regardless of which step surfaced it.
            # Without this a wrong API key reads as "that module is missing".
            if self._looks_like_auth_failure(str(exc)):
                return {
                    **base,
                    "status": "unhealthy",
                    "message": f"authentication rejected on probe: {exc}",
                    "failure": "authentication",
                }
            # A TRANSPORT failure is an outage, not a missing module. Without this
            # branch an unreachable system reports `degraded` and nobody is paged.
            #
            # Only visible once a connector had a DIFFERENT auth host and data host.
            # Everywhere else an unreachable host also breaks authentication, so it
            # exited at step 1 and reported unhealthy correctly. Dynamics
            # authenticates against login.microsoftonline.com and reads from
            # <org>.api.crm.dynamics.com, so with Dataverse unreachable it
            # authenticated fine and then reported "the probe entity was not
            # readable" -- i.e. a total outage as a non-paging condition.
            # Caught against a real environment by pointing api_url at a dead port.
            if self._looks_like_transport_failure(exc):
                return {
                    **base,
                    "status": "unhealthy",
                    "message": f"cannot reach {self.config.erp_type.value}: {exc}",
                    "failure": "connection",
                }
            return {
                **base,
                "status": "degraded",
                "message": (
                    f"authenticated, but probe entity {entity_type!r} was not "
                    f"readable: {exc}. This is often a module that is not "
                    f"installed or licensed rather than a connection fault."
                ),
                "failure": "probe_entity",
                "probe_entity": entity_type,
            }

        return {
            **base,
            "status": "healthy",
            "message": f"{self.config.erp_type.value} connection successful",
            "probe_entity": entity_type,
        }

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

        # Authenticate to get new token.
        #
        # `authenticate()` may record the real expiry via _set_token (which is what
        # an OAuth2 flow returning `expires_in` should do). If it only returns a
        # string, fall back to the conservative default below. This used to
        # hardcode one hour unconditionally: a provider issuing a 20-minute token
        # meant 40 minutes of serving a dead credential from cache, and every
        # request in that window failed with a 401 that looked like a permissions
        # problem.
        # SERIALISED. Without this lock every concurrent caller that arrives with an
        # empty cache authenticates: 20 simultaneous fetches produced 20 token
        # round trips, measured. That is wasteful against SAP and Entra ID, and
        # actively destructive against Intuit, where EVERY refresh rotates the
        # refresh token and retires the previous one -- so N concurrent refreshes
        # create N competing rotations, N-1 of which are discarded, leaving the
        # stored credential invalid.
        async with self._auth_lock:
            # Double-check: whoever held the lock first may have just filled it.
            if self._auth_token and self._token_expiry:
                if datetime.now(timezone.utc) < self._token_expiry:
                    return self._auth_token
            return await self._authenticate_and_cache()

    async def _authenticate_and_cache(self) -> str:
        # Clear first so an authenticate() that calls _set_token wins, and one that
        # only returns a string still lands in the cache below.
        self._auth_token = None
        self._token_expiry = None

        token = await self.authenticate()
        if self._token_expiry is None:
            self._set_token(token)
        else:
            # authenticate() recorded the provider's real expiry via _set_token.
            self._auth_token = token

        return token
    
    async def close(self):
        """Clean up resources when closing connector"""
        logger.info(
            "erp_connector_closing",
            erp_type=self.config.erp_type.value,
            integration_id=self.integration_id
        )

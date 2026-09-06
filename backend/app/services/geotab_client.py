"""A live MyGeotab API client (FS-987..993).

Everything in `geotab_service.py` was gated behind `_require_simulated`: there was no live
client at all, so every GeoTab surface in the product served `random`-generated demo data
or refused. This is the client those gates were waiting for.

**UNVERIFIED AGAINST A LIVE ACCOUNT, and that is stated rather than glossed.** This
repository has no MyGeotab credentials and Geotab publishes no isolated sandbox — a test
database there is a real database, and a write to it is a real write. The protocol below is
implemented from Geotab's published API documentation and is exercised end to end against a
fake transport (`tests/test_geotab_client.py`) which asserts the exact request bodies, the
session lifecycle, the error taxonomy and the paging arithmetic. What that cannot prove is
that Geotab agrees. **One live smoke call against a real database is required before this
is trusted with anything, and `GEOTAB_SIMULATED` stays the default until somebody makes
it.** Writing a client that has never spoken to the server it targets is exactly how this
codebase produced a Grafana datasource that could not connect and a webhook receiver that
rejected every real delivery; the difference here is that the limitation is written down.

THE PROTOCOL, briefly. MyGeotab is JSON-RPC-ish over a single POST endpoint:

    POST https://{server}/apiv1
    {"method": "Get", "params": {"typeName": "Device", "credentials": {...}}}

`Authenticate` exchanges database/username/password for a `sessionId`, and may answer with
a *different server* to talk to (`path`) — a redirect this client must follow, because
Geotab shards databases across servers and the documented entry point is `my.geotab.com`.

RATE LIMITS ARE READ, NOT GUESSED AT. Limits are per (method, entity, user, database) and
scale with fleet size; on breach the API returns `OverLimitException` with `Retry-After`.
This client honours that header rather than retrying immediately, because retrying into a
rate limit is what converts a slow period into an outage.

FEEDS, NOT WEBHOOKS. Geotab has no signed webhook — its "Web Request" rule template POSTs
form-encoded data with no HMAC and no mTLS, so a receiver cannot authenticate the sender.
The supported high-volume path is `GetFeed` with a continuation token, capped at 50,000
records per call. `get_feed` below is that, and the caller owns the token.
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional, Tuple

import aiohttp
import structlog

from app.core.config import settings

logger = structlog.get_logger()

#: Geotab's documented ceiling for one GetFeed call.
MAX_FEED_RESULTS = 50_000

#: Geotab's guidance is >=1010ms between calls on a sustained feed.
MIN_FEED_INTERVAL_SECONDS = 1.01


class GeotabError(RuntimeError):
    """A MyGeotab API error, carrying the vendor's own error name.

    The name matters: `InvalidUserException` is a credential problem an operator must fix,
    `OverLimitException` is backpressure that will pass on its own, and treating the two
    the same is how a throttled integration gets "fixed" by rotating working credentials.
    """

    def __init__(self, name: str, message: str, retry_after: Optional[float] = None):
        super().__init__(f"{name}: {message}")
        self.name = name
        self.message = message
        self.retry_after = retry_after

    @property
    def is_rate_limit(self) -> bool:
        return self.name == "OverLimitException"

    @property
    def is_auth_failure(self) -> bool:
        return self.name in {"InvalidUserException", "DbUnavailableException"}


class GeotabClient:
    """Session-managing MyGeotab client.

    One instance holds one authenticated session and re-authenticates on expiry, because a
    `sessionId` is long-lived but not permanent and the failure when it lapses is an
    `InvalidUserException` on an otherwise correct call.
    """

    def __init__(
        self,
        *,
        database: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
        server: str = "my.geotab.com",
        session_factory=None,
    ):
        self.database = database if database is not None else settings.GEOTAB_DATABASE
        self.username = username if username is not None else settings.GEOTAB_USERNAME
        self.password = password if password is not None else settings.GEOTAB_PASSWORD
        self.server = server
        # Injected in tests. Production builds a session per call with an explicit
        # timeout, matching the ERP connector layer's convention (FS-1008).
        self._session_factory = session_factory
        self._credentials: Optional[Dict[str, str]] = None

    # -- transport ---------------------------------------------------------------

    def _session(self) -> aiohttp.ClientSession:
        return aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=settings.GEOTAB_TIMEOUT_SECONDS)
        )

    async def _post(self, method: str, params: Dict[str, Any]) -> Any:
        """One JSON-RPC call, with the vendor's error taxonomy decoded.

        Geotab answers HTTP 200 with an `error` object rather than an HTTP error status
        for most failures, so a client that only checks `response.status` sees every
        failure as a success with unexpected content.
        """
        url = f"https://{self.server}/apiv1"
        body = {"method": method, "params": params}
        factory = self._session_factory or self._session
        async with factory() as session:
            async with session.post(url, json=body) as response:
                retry_after = _retry_after_seconds(response.headers)
                payload = await response.json()

        if isinstance(payload, dict) and payload.get("error"):
            name, message = _decode_error(payload["error"])
            raise GeotabError(name, message, retry_after)
        return payload.get("result") if isinstance(payload, dict) else payload

    # -- session -----------------------------------------------------------------

    async def authenticate(self) -> Dict[str, str]:
        """Exchange credentials for a session, following a server redirect if given.

        Geotab shards databases across servers: authenticating at `my.geotab.com` for a
        database that lives elsewhere succeeds and returns the real server in `path`.
        Ignoring it means every subsequent call goes to the wrong host.
        """
        if not (self.database and self.username and self.password):
            raise GeotabError(
                "MissingCredentials",
                "GEOTAB_DATABASE, GEOTAB_USERNAME and GEOTAB_PASSWORD must all be set "
                "for live mode. Note that Geotab now requires a Service Account "
                "credential for API users -- a personal login may be refused.",
            )
        result = await self._post(
            "Authenticate",
            {
                "database": self.database,
                "userName": self.username,
                "password": self.password,
            },
        )
        path = (result or {}).get("path")
        if path and path not in ("ThisServer", self.server):
            # Follow the shard, then authenticate again against it.
            logger.info("geotab_auth_redirect", from_server=self.server, to_server=path)
            self.server = path
            result = await self._post(
                "Authenticate",
                {
                    "database": self.database,
                    "userName": self.username,
                    "password": self.password,
                },
            )
        self._credentials = (result or {}).get("credentials")
        if not self._credentials:
            raise GeotabError("AuthenticationFailed", "no credentials in Authenticate result")
        logger.info("geotab_authenticated", database=self.database, server=self.server)
        return self._credentials

    async def _authenticated_params(self, params: Dict[str, Any]) -> Dict[str, Any]:
        if self._credentials is None:
            await self.authenticate()
        return {**params, "credentials": self._credentials}

    async def call(self, method: str, **params: Any) -> Any:
        """An authenticated call that re-authenticates once on session expiry.

        A lapsed `sessionId` surfaces as `InvalidUserException` on a call that is
        otherwise correct, so retrying it after a fresh authenticate is the difference
        between a self-healing integration and one that needs a restart.
        """
        try:
            return await self._post(method, await self._authenticated_params(params))
        except GeotabError as exc:
            if not exc.is_auth_failure or self._credentials is None:
                raise
            logger.info("geotab_session_expired_reauthenticating", method=method)
            self._credentials = None
            return await self._post(method, await self._authenticated_params(params))

    # -- data --------------------------------------------------------------------

    async def get(
        self, type_name: str, *, search: Optional[Dict[str, Any]] = None,
        results_limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """`Get` one entity type. Prefer `get_feed` for continuous extraction."""
        params: Dict[str, Any] = {"typeName": type_name}
        if search:
            params["search"] = search
        if results_limit:
            params["resultsLimit"] = results_limit
        return await self.call("Get", **params) or []

    async def get_feed(
        self, type_name: str, *, from_version: Optional[str] = None,
        results_limit: int = MAX_FEED_RESULTS,
    ) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        """One `GetFeed` page: returns (records, next_version).

        THE TOKEN IS THE CALLER'S TO PERSIST. A feed resumed from `None` re-reads from the
        beginning, so a consumer that forgets to store `toVersion` silently reprocesses
        history on every restart -- and one that stores it without checking for
        `data` exhaustion spins.
        """
        if results_limit > MAX_FEED_RESULTS:
            raise ValueError(
                f"resultsLimit {results_limit} exceeds Geotab's documented maximum of "
                f"{MAX_FEED_RESULTS} for GetFeed"
            )
        params: Dict[str, Any] = {"typeName": type_name, "resultsLimit": results_limit}
        if from_version:
            params["fromVersion"] = from_version
        result = await self.call("GetFeed", **params) or {}
        return result.get("data", []), result.get("toVersion")

    async def iter_feed(
        self, type_name: str, *, from_version: Optional[str] = None,
        max_pages: int = 100, results_limit: int = MAX_FEED_RESULTS,
    ):
        """Page a feed, honouring Geotab's own inter-call guidance.

        `max_pages` is a stop, not a target: a feed that keeps returning a full page is
        indistinguishable from one that is not advancing, and an unbounded loop over a
        misbehaving token is a busy-wait against a rate-limited API.
        """
        version = from_version
        for page in range(max_pages):
            records, version = await self.get_feed(
                type_name, from_version=version, results_limit=results_limit
            )
            if not records:
                return
            yield records, version
            if len(records) < results_limit:
                return
            await asyncio.sleep(MIN_FEED_INTERVAL_SECONDS)


def _decode_error(error: Any) -> Tuple[str, str]:
    """Geotab nests the useful name under `errors[0].name`."""
    if isinstance(error, dict):
        errors = error.get("errors") or []
        if errors and isinstance(errors[0], dict):
            first = errors[0]
            return (
                str(first.get("name") or "GeotabError"),
                str(first.get("message") or error.get("message") or ""),
            )
        return str(error.get("name") or "GeotabError"), str(error.get("message") or "")
    return "GeotabError", str(error)


def _retry_after_seconds(headers: Any) -> Optional[float]:
    """`Retry-After`, when the API is telling us how long to wait.

    Read rather than ignored: retrying immediately into a rate limit is what turns a busy
    period into an outage, and Geotab's limits scale with fleet size so a large customer
    hits them on traffic a small one never would.
    """
    try:
        raw = headers.get("Retry-After") if headers else None
    except AttributeError:  # pragma: no cover - defensive on a fake transport
        return None
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None

"""Intuit QuickBooks Online connector — request shape, envelope, paging, webhooks.

Everything here is hermetic: pure functions are checked by known-input/known-output,
and the HTTP paths run against a recorder that captures exactly what the connector
sent. No network, and no mock that returns whatever the code happens to ask for.

The assertions concentrate on the failure modes that actually bite:

  - QuickBooks has NO client-credentials grant. Its discovery document advertises
    `response_types_supported: ["code"]` only, so this connector must refresh a
    stored token, never authorize.
  - Refresh tokens ROTATE and the old one is retired. Losing the new value gives an
    integration that works once and then fails forever with `invalid_grant`.
  - An empty result omits the entity key entirely (`{"QueryResponse": {}}`), so "no
    rows" and "we did not understand the response" must not collapse together.
  - STARTPOSITION is 1-based; an off-by-one repeats or skips a row per page.
  - Query literals are single-quoted, so an apostrophe in a tenant-supplied filter
    is an injection vector, not a typo.
  - Webhook signatures must be computed over RAW bytes and compared in constant
    time.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from typing import Any, Dict, List, Optional
from unittest.mock import patch

import pytest

from app.services.erp_connector_base import AuthType, ERPConfig, ERPType
from app.services.erp_connectors.intuit_connector import IntuitConnector
from app.services.erp_connectors.intuit_qbo import (
    MAX_PAGE_SIZE,
    PRODUCTION_HOST,
    SANDBOX_HOST,
    TOKEN_ENDPOINT,
    QBOError,
    api_host,
    build_query,
    company_url,
    escape_query_literal,
    fault_to_error,
    parse_query_response,
    parse_token_response,
    verify_webhook_signature,
)

# ---------------------------------------------------------------------------
# Recorder
# ---------------------------------------------------------------------------


class _Resp:
    def __init__(self, status: int, payload: Any, *, raw_text: Optional[str] = None):
        self.status = status
        self._payload = payload
        self._raw = raw_text

    async def json(self, content_type=None):
        if self._raw is not None:
            return json.loads(self._raw)  # raises if the raw text is not JSON
        return self._payload

    async def text(self):
        return self._raw if self._raw is not None else json.dumps(self._payload)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _Recorder:
    """Captures every request and serves a queue of responses.

    A queue rather than one canned answer, because pagination correctness cannot be
    tested against a source that always returns the same page.
    """

    def __init__(self, responses: List[_Resp]):
        self._responses = list(responses)
        self.calls: List[Dict[str, Any]] = []

    def _next(self, method, url, **kw):
        self.calls.append({"method": method, "url": url, **kw})
        if not self._responses:
            raise AssertionError(f"unexpected extra {method} to {url}")
        return self._responses.pop(0)

    def get(self, url, headers=None, params=None, **kw):
        return self._next("GET", url, headers=headers, params=params)

    def post(self, url, headers=None, data=None, auth=None, **kw):
        return self._next("POST", url, headers=headers, data=data, auth=auth)

    async def close(self):
        return None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    # convenience
    @property
    def queries(self) -> List[str]:
        return [c["params"]["query"] for c in self.calls if c.get("params")]


def _config(**overrides) -> ERPConfig:
    configuration = {"realm_id": "4620816365", "environment": "sandbox"}
    configuration.update(overrides.pop("configuration", {}))
    auth_config = {
        "client_id": "ABclientid",
        "client_secret": "SEcret",
        "refresh_token": "RT-original",
    }
    auth_config.update(overrides.pop("auth_config", {}))
    return ERPConfig(
        erp_type=ERPType.INTUIT,
        auth_type=AuthType.OAUTH2,
        base_url=overrides.pop("base_url", ""),
        auth_config=auth_config,
        rate_limit={"requests_per_minute": 500},
        configuration=configuration,
        **overrides,
    )


def _connector(**overrides) -> IntuitConnector:
    return IntuitConnector(_config(**overrides), "org-1", "int-1")


def _authed(**overrides) -> IntuitConnector:
    """A connector with a live token, so fetch tests exercise only the read path."""
    connector = _connector(**overrides)
    connector._set_token("AT-live", 3600)
    return connector


# ---------------------------------------------------------------------------
# Hosts and URLs
# ---------------------------------------------------------------------------


class TestHostResolution:
    @pytest.mark.parametrize("name", ["sandbox", "SANDBOX", " Sandbox ", "sbx", "dev"])
    def test_sandbox_names_resolve_to_the_sandbox_host(self, name):
        assert api_host(name) == SANDBOX_HOST

    @pytest.mark.parametrize("name", ["production", "prod", "live", "PRODUCTION"])
    def test_production_names_resolve_to_the_production_host(self, name):
        assert api_host(name) == PRODUCTION_HOST

    def test_sandbox_and_production_are_different_hosts(self):
        """Not a path, not a header. A sandbox credential sent to the production
        host returns 401, which reads as a bad credential rather than a wrong
        host — the same confusion as the NetSuite `suitetalk.net` defect."""
        assert SANDBOX_HOST != PRODUCTION_HOST
        assert "sandbox" in SANDBOX_HOST

    def test_an_unknown_environment_raises_rather_than_guessing(self):
        """Defaulting a typo to production would send sandbox traffic at real
        company data."""
        with pytest.raises(ValueError, match="unknown Intuit environment"):
            api_host("staging")


class TestCompanyUrl:
    def test_builds_the_company_scoped_path(self):
        assert company_url(PRODUCTION_HOST, "123", "query") == (
            f"{PRODUCTION_HOST}/v3/company/123/query"
        )

    @pytest.mark.parametrize("host", [PRODUCTION_HOST, PRODUCTION_HOST + "/", PRODUCTION_HOST + "///"])
    def test_a_trailing_slash_on_the_host_cannot_create_an_empty_segment(self, host):
        url = company_url(host, "123", "query")
        assert "//" not in url.split("://", 1)[1], url

    @pytest.mark.parametrize("realm", ["/123/", "123"])
    def test_realm_id_slashes_are_stripped(self, realm):
        assert company_url(PRODUCTION_HOST, realm, "query").endswith("/company/123/query")

    def test_a_missing_realm_id_raises_with_an_explanation(self):
        with pytest.raises(ValueError, match="realm_id"):
            company_url(PRODUCTION_HOST, "", "query")


class TestConstruction:
    def test_realm_id_is_required_at_construction(self):
        """A missing company id cannot be recovered from later, and failing at the
        first fetch instead would surface as a confusing 404."""
        with pytest.raises(ValueError, match="realm_id"):
            IntuitConnector(_config(configuration={"realm_id": ""}), "org", "int")

    def test_environment_selects_the_host(self):
        assert _connector().host == SANDBOX_HOST
        assert _connector(configuration={"environment": "production"}).host == PRODUCTION_HOST

    def test_an_explicit_base_url_wins_over_the_environment(self):
        """Needed to point the connector at a mock or a proxy."""
        assert _connector(base_url="http://127.0.0.1:4010").host == "http://127.0.0.1:4010"

    def test_page_size_is_clamped_to_the_api_maximum(self):
        assert _connector(configuration={"page_size": 99999}).page_size == MAX_PAGE_SIZE
        assert _connector(configuration={"page_size": 0}).page_size == 1


# ---------------------------------------------------------------------------
# Query construction
# ---------------------------------------------------------------------------


class TestQueryConstruction:
    def test_start_position_is_one_based(self):
        assert "startposition 1" in build_query("Invoice")

    def test_zero_start_position_is_rejected(self):
        """0 is not "the beginning" in QBO. Silently accepting it skips or repeats a
        row at every page boundary, which stays invisible until someone reconciles
        totals."""
        with pytest.raises(ValueError, match="1-based"):
            build_query("Invoice", start_position=0)

    @pytest.mark.parametrize("size", [0, -1, MAX_PAGE_SIZE + 1])
    def test_page_size_out_of_range_is_rejected(self, size):
        with pytest.raises(ValueError, match="MAXRESULTS"):
            build_query("Invoice", max_results=size)

    def test_filters_are_typed_correctly(self):
        query = build_query(
            "Invoice",
            filters={"Balance": 100, "Active": True, "DocNumber": "A-1", "Memo": None},
        )
        assert "Balance = 100" in query          # bare number, not quoted
        assert "Active = true" in query          # lowercase JSON-ish boolean
        assert "DocNumber = 'A-1'" in query      # quoted string
        assert "Memo is null" in query           # not "= 'None'"

    def test_multiple_filters_are_anded(self):
        query = build_query("Invoice", filters={"a": 1, "b": 2})
        assert "where a = 1 and b = 2" in query

    def test_no_filters_emits_no_where_clause(self):
        assert "where" not in build_query("Invoice")

    def test_an_empty_entity_is_rejected(self):
        with pytest.raises(ValueError, match="entity is required"):
            build_query("")


class TestQueryEscaping:
    r"""An apostrophe in a tenant-supplied filter is an injection vector, because
    QBO's query language is SQL-shaped and literals are single-quoted."""

    def test_an_apostrophe_is_escaped(self):
        assert escape_query_literal("O'Brien") == r"O\'Brien"

    def test_a_backslash_is_escaped(self):
        assert escape_query_literal("a\\b") == "a\\\\b"

    def test_backslash_is_escaped_before_the_quote(self):
        r"""ORDER MATTERS. Escaping the quote first turns `\'` into `\\'`, whose
        backslash is then doubled again -- changing the value and re-opening the
        break-out. Escaping the backslash first is the only correct order."""
        # A literal backslash followed by a quote.
        assert escape_query_literal("\\'") == "\\\\\\'"

    def test_a_break_out_attempt_stays_inside_the_literal(self):
        query = build_query("Invoice", filters={"DocNumber": "x' or '1'='1"})
        # The injected quotes are all escaped, so nothing new is parsed as syntax.
        assert "or '1'='1" not in query
        assert r"\'" in query

    def test_the_escaped_value_is_still_the_same_value(self):
        """Escaping must be reversible -- an escape that mangles data is its own
        bug."""
        for raw in ["O'Brien", "a\\b", "\\'", "plain", "it's a \\ test"]:
            escaped = escape_query_literal(raw)
            unescaped = escaped.replace("\\'", "'").replace("\\\\", "\\")
            assert unescaped == raw, (raw, escaped, unescaped)


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------


class TestResponseEnvelope:
    def test_rows_are_extracted(self):
        payload = {"QueryResponse": {"Invoice": [{"Id": "1"}, {"Id": "2"}]}}
        assert len(parse_query_response(payload, "Invoice")) == 2

    def test_an_empty_query_response_is_an_honest_zero(self):
        """THE CASE THAT MATTERS. A query matching nothing returns
        {"QueryResponse": {}} -- the entity key is ABSENT, not an empty list."""
        assert parse_query_response({"QueryResponse": {}, "time": "t"}, "Invoice") == []

    def test_a_missing_envelope_raises_instead_of_reporting_zero_rows(self):
        """The other half of the same problem: without this, a response we do not
        understand becomes a confident "there are no invoices"."""
        with pytest.raises(QBOError, match="no QueryResponse envelope"):
            parse_query_response({"unexpected": True}, "Invoice")

    def test_a_single_object_is_normalized_to_a_list(self):
        """QBO returns a bare object rather than a list for some single-row reads
        (CompanyInfo among them); a caller doing len() on a dict would count its
        keys."""
        rows = parse_query_response({"QueryResponse": {"CompanyInfo": {"Id": "1"}}}, "CompanyInfo")
        assert rows == [{"Id": "1"}]

    def test_a_fault_in_a_200_body_still_raises(self):
        payload = {"Fault": {"type": "ValidationFault", "Error": [{"Message": "bad", "code": "4000"}]}}
        with pytest.raises(QBOError):
            parse_query_response(payload, "Invoice")


class TestFaultParsing:
    def test_codes_and_type_are_preserved(self):
        """Collapsing a Fault to its HTTP status loses the one detail that separates
        "your query is malformed" from "that entity is not available here" -- and the
        second is a DEGRADED health state, not an outage."""
        error = fault_to_error(
            {
                "Fault": {
                    "type": "ValidationFault",
                    "Error": [{"Message": "Invalid query", "Detail": "line 1", "code": "4000"}],
                }
            },
            status=400,
        )
        assert error.codes == ["4000"]
        assert error.status == 400
        assert "ValidationFault" in str(error)
        assert "Invalid query" in str(error)
        assert "line 1" in str(error)

    def test_an_empty_fault_still_produces_a_message(self):
        assert str(fault_to_error({"Fault": {}})) != ""


# ---------------------------------------------------------------------------
# Token handling
# ---------------------------------------------------------------------------


class TestTokenParsing:
    def test_returns_token_expiry_and_the_rotated_refresh_token(self):
        token, expires_in, rotated = parse_token_response(
            {"access_token": "AT", "expires_in": 3600, "refresh_token": "RT-new"}
        )
        assert (token, expires_in, rotated) == ("AT", 3600.0, "RT-new")

    def test_an_oauth_error_is_raised_with_its_description(self):
        with pytest.raises(QBOError, match="invalid_grant"):
            parse_token_response({"error": "invalid_grant", "error_description": "token expired"})

    def test_a_response_without_a_token_raises(self):
        with pytest.raises(QBOError, match="no access_token"):
            parse_token_response({"expires_in": 3600})

    def test_a_non_numeric_expiry_falls_back_rather_than_crashing(self):
        _, expires_in, _ = parse_token_response({"access_token": "AT", "expires_in": "soon"})
        assert expires_in is None


class TestAuthentication:
    async def test_missing_credentials_name_what_is_missing_and_why(self):
        connector = _connector(auth_config={"refresh_token": None, "client_secret": None})
        with pytest.raises(QBOError) as excinfo:
            await connector.authenticate()
        message = str(excinfo.value)
        assert "client_secret" in message and "refresh_token" in message
        # The explanation matters: someone will try to configure this like SAP.
        assert "client-credentials" in message

    async def test_sends_the_refresh_token_grant_with_basic_auth(self):
        recorder = _Recorder([_Resp(200, {"access_token": "AT", "expires_in": 3600})])
        connector = _connector()
        with patch("aiohttp.ClientSession", return_value=recorder):
            token = await connector.authenticate()

        assert token == "AT"
        call = recorder.calls[0]
        assert call["url"] == TOKEN_ENDPOINT
        # QuickBooks advertises only the code response type -- there is no
        # client-credentials grant to use here.
        assert call["data"]["grant_type"] == "refresh_token"
        assert call["data"]["refresh_token"] == "RT-original"
        # client_secret_basic, per the discovery document.
        import base64 as _b64
        expected = _b64.b64encode(b"ABclientid:SEcret").decode()
        assert call["headers"]["Authorization"] == f"Basic {expected}"
        assert call["headers"]["Content-Type"] == "application/x-www-form-urlencoded"
        assert call["headers"]["Accept"] == "application/json"

    async def test_the_provider_expiry_is_honoured(self):
        """A hardcoded lifetime means serving a dead credential from cache, and
        every request in that window fails with a 401 that looks like a permissions
        problem."""
        recorder = _Recorder([_Resp(200, {"access_token": "AT", "expires_in": 120})])
        connector = _connector()
        with patch("aiohttp.ClientSession", return_value=recorder):
            await connector.authenticate()
        from datetime import datetime, timezone

        remaining = (connector._token_expiry - datetime.now(timezone.utc)).total_seconds()
        assert remaining <= 120

    async def test_an_invalid_grant_is_surfaced_not_swallowed(self):
        """`invalid_grant` is what a lost rotated refresh token looks like. It must
        not be reported as a generic failure, or nobody will look at persistence."""
        recorder = _Recorder([_Resp(400, {"error": "invalid_grant"})])
        connector = _connector()
        with patch("aiohttp.ClientSession", return_value=recorder):
            with pytest.raises(QBOError, match="invalid_grant"):
                await connector.authenticate()
        # And exactly ONE attempt: a retired refresh token is permanently dead, so
        # retrying replays the same rejected credential against Intuit's token
        # endpoint. This assertion is what caught the retry loop doing that.
        assert len(recorder.calls) == 1

    async def test_a_non_json_token_response_is_reported_as_such(self):
        # A 502 IS transient, so retries are correct here -- the point of this test
        # is only that a gateway HTML page is not mistaken for a token response.
        recorder = _Recorder([_Resp(502, None, raw_text="<html>gateway</html>")])
        connector = _connector()
        connector.retry_config["max_retries"] = 0
        with patch("aiohttp.ClientSession", return_value=recorder):
            with pytest.raises(QBOError, match="non-JSON"):
                await connector.authenticate()


class TestRefreshTokenRotation:
    """THE FAILURE THIS CONNECTOR IS MOST LIKELY TO HIT IN PRODUCTION.

    Intuit issues a new refresh token on every refresh and retires the old one. A
    connector that drops it authenticates fine today and fails forever at the next
    refresh with `invalid_grant` -- which reads as "the customer revoked our access"
    and sends everyone looking in the wrong place.
    """

    async def test_a_rotated_token_is_handed_to_the_sink(self):
        stored = []
        recorder = _Recorder([
            _Resp(200, {"access_token": "AT", "expires_in": 3600, "refresh_token": "RT-new"})
        ])
        connector = _connector(configuration={"refresh_token_sink": stored.append})
        with patch("aiohttp.ClientSession", return_value=recorder):
            await connector.authenticate()
        assert stored == ["RT-new"]

    async def test_the_in_memory_config_is_updated_even_without_a_sink(self):
        """So a long-running worker does not break mid-run just because nobody
        supplied persistence."""
        recorder = _Recorder([
            _Resp(200, {"access_token": "AT", "expires_in": 3600, "refresh_token": "RT-new"})
        ])
        connector = _connector()
        with patch("aiohttp.ClientSession", return_value=recorder):
            await connector.authenticate()
        assert connector.config.auth_config["refresh_token"] == "RT-new"

    async def test_an_unchanged_token_is_not_reported_as_a_rotation(self):
        stored = []
        recorder = _Recorder([
            _Resp(200, {"access_token": "AT", "expires_in": 3600, "refresh_token": "RT-original"})
        ])
        connector = _connector(configuration={"refresh_token_sink": stored.append})
        with patch("aiohttp.ClientSession", return_value=recorder):
            await connector.authenticate()
        assert stored == []

    async def test_a_sink_that_throws_does_not_break_authentication(self):
        """Persistence failing is serious, but it must not also take down the sync
        that is otherwise working. It is logged as an error, not swallowed silently
        and not raised."""
        def _boom(_token):
            raise RuntimeError("database down")

        recorder = _Recorder([
            _Resp(200, {"access_token": "AT", "expires_in": 3600, "refresh_token": "RT-new"})
        ])
        connector = _connector(configuration={"refresh_token_sink": _boom})
        with patch("aiohttp.ClientSession", return_value=recorder):
            token = await connector.authenticate()
        assert token == "AT"


# ---------------------------------------------------------------------------
# Reads and pagination
# ---------------------------------------------------------------------------


def _page(entity: str, count: int, start: int = 1) -> _Resp:
    return _Resp(200, {"QueryResponse": {entity: [{"Id": str(start + i)} for i in range(count)]}})


class TestFetchRequestShape:
    async def test_hits_the_company_scoped_query_endpoint(self):
        recorder = _Recorder([_page("Invoice", 0)])
        connector = _authed()
        with patch("aiohttp.ClientSession", return_value=recorder):
            await connector.fetch_data("Invoice")
        assert recorder.calls[0]["url"] == f"{SANDBOX_HOST}/v3/company/4620816365/query"

    async def test_requests_json_explicitly(self):
        """QBO answers XML by default, and XML parsed as JSON fails in a way that
        says nothing about content negotiation."""
        recorder = _Recorder([_page("Invoice", 0)])
        with patch("aiohttp.ClientSession", return_value=recorder):
            await _authed().fetch_data("Invoice")
        assert recorder.calls[0]["headers"]["Accept"] == "application/json"

    async def test_sends_a_bearer_token(self):
        recorder = _Recorder([_page("Invoice", 0)])
        with patch("aiohttp.ClientSession", return_value=recorder):
            await _authed().fetch_data("Invoice")
        assert recorder.calls[0]["headers"]["Authorization"] == "Bearer AT-live"

    async def test_pins_a_minor_version(self):
        """Unpinned requests get the oldest supported behaviour, so field-level
        changes arrive silently."""
        recorder = _Recorder([_page("Invoice", 0)])
        with patch("aiohttp.ClientSession", return_value=recorder):
            await _authed().fetch_data("Invoice")
        assert recorder.calls[0]["params"]["minorversion"]


class TestPagination:
    async def test_follows_every_page(self):
        """Paging is where silent truncation lives: QBO caps a page at 1000 and
        defaults to 100, so returning only the first page quietly loses the rest."""
        recorder = _Recorder([_page("Invoice", 2, 1), _page("Invoice", 2, 3), _page("Invoice", 1, 5)])
        connector = _authed(configuration={"page_size": 2})
        with patch("aiohttp.ClientSession", return_value=recorder):
            rows = await connector.fetch_data("Invoice")
        assert [r["Id"] for r in rows] == ["1", "2", "3", "4", "5"]
        assert len(recorder.calls) == 3

    async def test_start_position_advances_by_rows_returned(self):
        recorder = _Recorder([_page("Invoice", 2, 1), _page("Invoice", 0)])
        connector = _authed(configuration={"page_size": 2})
        with patch("aiohttp.ClientSession", return_value=recorder):
            await connector.fetch_data("Invoice")
        assert "startposition 1" in recorder.queries[0]
        assert "startposition 3" in recorder.queries[1]

    async def test_a_short_page_ends_the_loop(self):
        recorder = _Recorder([_page("Invoice", 1, 1)])
        connector = _authed(configuration={"page_size": 5})
        with patch("aiohttp.ClientSession", return_value=recorder):
            rows = await connector.fetch_data("Invoice")
        assert len(rows) == 1
        assert len(recorder.calls) == 1

    async def test_no_duplicate_rows_across_pages(self):
        recorder = _Recorder([_page("Invoice", 3, 1), _page("Invoice", 3, 4), _page("Invoice", 0)])
        connector = _authed(configuration={"page_size": 3})
        with patch("aiohttp.ClientSession", return_value=recorder):
            rows = await connector.fetch_data("Invoice")
        ids = [r["Id"] for r in rows]
        assert len(ids) == len(set(ids)), ids

    async def test_limit_is_respected_exactly(self):
        recorder = _Recorder([_page("Invoice", 2, 1)])
        connector = _authed(configuration={"page_size": 2})
        with patch("aiohttp.ClientSession", return_value=recorder):
            rows = await connector.fetch_data("Invoice", limit=2)
        assert len(rows) == 2
        # No wasted extra request once the limit is met.
        assert len(recorder.calls) == 1

    async def test_a_limit_smaller_than_the_page_size_shrinks_the_request(self):
        """Asking for 1000 rows to return 3 is both slower and, on a rate-limited
        API, expensive."""
        recorder = _Recorder([_page("Invoice", 3, 1)])
        connector = _authed(configuration={"page_size": 100})
        with patch("aiohttp.ClientSession", return_value=recorder):
            await connector.fetch_data("Invoice", limit=3)
        assert "maxresults 3" in recorder.queries[0]

    async def test_an_empty_first_page_returns_empty_without_looping(self):
        recorder = _Recorder([_Resp(200, {"QueryResponse": {}})])
        with patch("aiohttp.ClientSession", return_value=recorder):
            rows = await _authed().fetch_data("Invoice")
        assert rows == []


class TestFetchErrorHandling:
    async def test_a_fault_body_is_raised_with_its_detail(self):
        recorder = _Recorder([
            _Resp(400, {"Fault": {"type": "ValidationFault",
                                  "Error": [{"Message": "Invalid query", "code": "4000"}]}})
        ])
        connector = _authed()
        connector.retry_config["max_retries"] = 0
        with patch("aiohttp.ClientSession", return_value=recorder):
            with pytest.raises(QBOError, match="Invalid query"):
                await connector.fetch_data("Invoice")

    async def test_a_401_invalidates_the_cached_token(self):
        """Retrying with a token the provider has already rejected just burns the
        retry budget."""
        recorder = _Recorder([_Resp(401, {"Fault": {"Error": [{"Message": "expired"}]}})])
        connector = _authed()
        connector.retry_config["max_retries"] = 0
        with patch("aiohttp.ClientSession", return_value=recorder):
            with pytest.raises(QBOError):
                await connector.fetch_data("Invoice")
        assert connector._auth_token is None

    async def test_an_html_error_page_is_not_reported_as_zero_rows(self):
        recorder = _Recorder([_Resp(503, None, raw_text="<html>upstream</html>")])
        connector = _authed()
        connector.retry_config["max_retries"] = 0
        with patch("aiohttp.ClientSession", return_value=recorder):
            with pytest.raises(QBOError, match="non-JSON"):
                await connector.fetch_data("Invoice")


# ---------------------------------------------------------------------------
# Webhooks
# ---------------------------------------------------------------------------


class TestWebhookSignature:
    VERIFIER = "d4b5c8e1-verifier"
    BODY = b'{"eventNotifications":[{"realmId":"123","dataChangeEvent":{"entities":[]}}]}'

    def _sign(self, body: bytes, verifier: str) -> str:
        return base64.b64encode(
            hmac.new(verifier.encode(), body, hashlib.sha256).digest()
        ).decode()

    def test_a_valid_signature_is_accepted(self):
        assert verify_webhook_signature(self.BODY, self._sign(self.BODY, self.VERIFIER), self.VERIFIER)

    def test_a_tampered_body_is_rejected(self):
        signature = self._sign(self.BODY, self.VERIFIER)
        assert not verify_webhook_signature(self.BODY + b" ", signature, self.VERIFIER)

    def test_a_signature_from_the_wrong_verifier_is_rejected(self):
        assert not verify_webhook_signature(self.BODY, self._sign(self.BODY, "other"), self.VERIFIER)

    def test_reserialized_json_does_not_verify(self):
        """WHY THE RAW BYTES ARE REQUIRED. Re-serializing the parsed body reorders
        keys and changes whitespace, so the digest never matches and every genuine
        notification would be rejected. This test exists so nobody "simplifies" the
        signature check into taking a dict."""
        signature = self._sign(self.BODY, self.VERIFIER)
        reserialized = json.dumps(json.loads(self.BODY), indent=2).encode()
        assert reserialized != self.BODY
        assert not verify_webhook_signature(reserialized, signature, self.VERIFIER)

    @pytest.mark.parametrize("header", ["", None, "not-base64!!", "YWJj"])
    def test_a_missing_or_malformed_header_is_rejected_without_raising(self, header):
        """An unverified webhook is a rejection, not a 500."""
        assert verify_webhook_signature(self.BODY, header, self.VERIFIER) is False

    def test_a_missing_verifier_token_rejects_rather_than_accepting(self):
        """Fail CLOSED. Treating an unconfigured verifier as "skip verification"
        would make the endpoint accept anything."""
        assert not verify_webhook_signature(self.BODY, self._sign(self.BODY, ""), "")

    def test_whitespace_around_the_header_is_tolerated(self):
        signature = self._sign(self.BODY, self.VERIFIER)
        assert verify_webhook_signature(self.BODY, f"  {signature}  ", self.VERIFIER)

    def test_the_connector_rejects_when_no_verifier_is_configured(self):
        connector = _connector()
        assert connector.verify_webhook_notification(self.BODY, "anything") is False

    def test_the_connector_verifies_with_the_configured_token(self):
        connector = _connector(configuration={"webhook_verifier_token": self.VERIFIER})
        assert connector.verify_webhook_notification(self.BODY, self._sign(self.BODY, self.VERIFIER))


class TestEventSubscription:
    async def test_it_reports_that_the_api_cannot_create_webhooks(self):
        """QuickBooks webhooks are configured in the Intuit developer portal; there
        is no create-subscription endpoint. Returning False beats POSTing to a
        plausible URL that does not exist -- the defect found across the other
        connectors, every one of which posts to an invented `/webhooks` path."""
        assert await _connector().subscribe_to_events(["Invoice"]) is False

    async def test_it_makes_no_http_request(self):
        recorder = _Recorder([])  # any request raises
        with patch("aiohttp.ClientSession", return_value=recorder):
            await _connector().subscribe_to_events(["Invoice"])
        assert recorder.calls == []


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


class TestHealthCheck:
    async def test_it_probes_an_entity_present_in_every_company(self):
        """`CompanyInfo` needs no module and no licence. Probing a business entity
        is what made other connectors report a working integration as an outage."""
        assert IntuitConnector.HEALTH_PROBE_ENTITY == "CompanyInfo"

    async def test_healthy_when_the_probe_returns(self):
        recorder = _Recorder([
            _Resp(200, {"access_token": "AT", "expires_in": 3600}),
            _Resp(200, {"QueryResponse": {"CompanyInfo": {"Id": "1"}}}),
        ])
        with patch("aiohttp.ClientSession", return_value=recorder):
            health = await _connector().health_check()
        assert health["status"] == "healthy", health

    async def test_a_bad_credential_is_unhealthy_not_degraded(self):
        """A wrong credential is an outage. Reporting it as degraded means nobody is
        paged for an integration that cannot work at all."""
        recorder = _Recorder([_Resp(400, {"error": "invalid_grant"})])
        connector = _connector()
        connector.retry_config["max_retries"] = 0
        with patch("aiohttp.ClientSession", return_value=recorder):
            health = await connector.health_check()
        assert health["status"] == "unhealthy", health
        assert health.get("failure") == "authentication", health

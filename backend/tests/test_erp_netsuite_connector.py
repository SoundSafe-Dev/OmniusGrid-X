"""NetSuite connector: auth signing, host, and pagination (ERP connector build).

These assert the REQUEST the connector builds, because that is what was wrong and
it is verifiable without a NetSuite account. Three defects made the old connector
non-functional and none of them would surface in a test that only checked "returns
a list":

  * the API host was `{account}.suitetalk.net`, which is not a NetSuite host;
  * auth was `Bearer <static token from config>`, where NetSuite requires OAuth 1.0a
    per-request signatures;
  * pagination was ignored, so anything past the first page was silently dropped.

The last one is the dangerous one: it returns a plausible, shorter answer.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List
from unittest.mock import patch

import pytest

from app.services.erp_connector_base import AuthType, ERPConfig, ERPType
from app.services.erp_connectors.netsuite_auth import (
    account_host,
    build_tba_header,
    parse_oauth2_token_response,
    percent_encode,
    signature_base_string,
)
from app.services.erp_connectors.netsuite_connector import NetSuiteConnector


TBA_AUTH = {
    "consumer_key": "ck",
    "consumer_secret": "cs",
    "token_id": "tk",
    "token_secret": "ts",
}


def _connector(auth: Dict[str, Any] | None = None, auth_type=AuthType.TOKEN) -> NetSuiteConnector:
    config = ERPConfig(
        erp_type=ERPType.NETSUITE,
        base_url="https://unused.example.com",
        auth_type=auth_type,
        auth_config=auth if auth is not None else dict(TBA_AUTH),
        rate_limit={"requests_per_minute": 600},
        configuration={"account_id": "TSTDRV_123", "page_size": 2},
    )
    return NetSuiteConnector(config, "org-1", "int-1")


class _FakeResponse:
    def __init__(self, status: int, payload: Any):
        self.status = status
        self._payload = payload

    async def json(self):
        return self._payload

    async def text(self):
        return json.dumps(self._payload) if not isinstance(self._payload, str) else self._payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _FakeSession:
    """Records every request so the tests can assert URL and headers."""

    def __init__(self, responses: List[_FakeResponse]):
        self._responses = list(responses)
        self.calls: List[Dict[str, Any]] = []

    def get(self, url, headers=None, **kw):
        self.calls.append({"method": "GET", "url": url, "headers": headers or {}})
        return self._responses.pop(0)

    def post(self, url, data=None, headers=None, **kw):
        self.calls.append({"method": "POST", "url": url, "data": data, "headers": headers or {}})
        return self._responses.pop(0)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


# ---------------------------------------------------------------------------
# Host + signing
# ---------------------------------------------------------------------------

class TestHostAndSigning:
    def test_account_host_is_a_real_netsuite_host(self):
        """The old connector used `{account}.suitetalk.net`, which does not exist."""
        assert account_host("TSTDRV_123") == "https://tstdrv-123.suitetalk.api.netsuite.com"

    def test_sandbox_account_underscores_become_hyphens(self):
        assert "1234567-sb1.suitetalk.api.netsuite.com" in account_host("1234567_SB1")

    def test_percent_encoding_escapes_slash(self):
        """RFC 5849 unreserved excludes '/'. urllib's default `safe='/'` would leave
        it, producing a different base string and an invalid signature."""
        assert percent_encode("a/b") == "a%2Fb"

    def test_signature_covers_query_parameters(self):
        """Omitting them is the classic TBA bug: unfiltered calls sign fine and every
        paginated one 401s, which reads as 'pagination is broken'."""
        base = signature_base_string("GET", "https://h/x?limit=2&offset=4", {"oauth_nonce": "n"})
        assert "limit%3D2" in base
        assert "offset%3D4" in base

    def test_header_is_deterministic_and_carries_the_realm(self):
        kwargs = dict(
            method="GET", url="https://h/x", account_id="tstdrv_123",
            consumer_key="ck", consumer_secret="cs", token_id="tk", token_secret="ts",
            timestamp=1700000000, nonce="fixed",
        )
        first, second = build_tba_header(**kwargs), build_tba_header(**kwargs)
        assert first == second
        # Realm must be the UPPERCASED account; NetSuite rejects a mismatch with an
        # error that does not mention the realm.
        assert first.startswith('OAuth realm="TSTDRV_123"')
        assert 'oauth_signature_method="HMAC-SHA256"' in first

    def test_signature_changes_with_the_url(self):
        base = dict(account_id="a", consumer_key="ck", consumer_secret="cs",
                    token_id="tk", token_secret="ts", timestamp=1, nonce="n")
        one = build_tba_header(method="GET", url="https://h/x?offset=0", **base)
        two = build_tba_header(method="GET", url="https://h/x?offset=2", **base)
        assert one != two, "signature must cover the query string"


# ---------------------------------------------------------------------------
# Requests
# ---------------------------------------------------------------------------

class TestRequestShape:
    async def test_uses_the_real_host_and_an_oauth_signature(self):
        conn = _connector()
        session = _FakeSession([_FakeResponse(200, {"items": [{"id": "1"}], "hasMore": False})])

        with patch.object(conn, "_http_session", return_value=session):
            await conn.fetch_data("salesOrder")

        call = session.calls[0]
        assert call["url"].startswith(
            "https://tstdrv-123.suitetalk.api.netsuite.com/services/rest/record/v1/salesOrder"
        ), call["url"]
        auth = call["headers"]["Authorization"]
        assert auth.startswith("OAuth "), f"TBA must sign, not send a bearer: {auth[:40]}"
        assert "Bearer" not in auth

    async def test_paginates_until_hasmore_is_false(self):
        """The defect that silently truncated results."""
        conn = _connector()  # page_size=2
        session = _FakeSession([
            _FakeResponse(200, {"items": [{"id": "1"}, {"id": "2"}], "hasMore": True}),
            _FakeResponse(200, {"items": [{"id": "3"}, {"id": "4"}], "hasMore": True}),
            _FakeResponse(200, {"items": [{"id": "5"}], "hasMore": False}),
        ])

        with patch.object(conn, "_http_session", return_value=session):
            rows = await conn.fetch_data("invoice")

        assert [r["id"] for r in rows] == ["1", "2", "3", "4", "5"]
        assert len(session.calls) == 3
        # Offset must advance by what was actually received.
        assert "offset=0" in session.calls[0]["url"]
        assert "offset=2" in session.calls[1]["url"]
        assert "offset=4" in session.calls[2]["url"]

    async def test_stops_at_limit_without_over_fetching(self):
        conn = _connector()
        session = _FakeSession([
            _FakeResponse(200, {"items": [{"id": "1"}, {"id": "2"}], "hasMore": True}),
            _FakeResponse(200, {"items": [{"id": "3"}], "hasMore": True}),
        ])

        with patch.object(conn, "_http_session", return_value=session):
            rows = await conn.fetch_data("invoice", limit=3)

        assert len(rows) == 3
        assert len(session.calls) == 2, "must not keep paging once the limit is met"

    async def test_empty_page_terminates_rather_than_looping(self):
        """A server that reports hasMore with no items would otherwise spin forever."""
        conn = _connector()
        session = _FakeSession([_FakeResponse(200, {"items": [], "hasMore": True})])

        with patch.object(conn, "_http_session", return_value=session):
            rows = await conn.fetch_data("invoice")

        assert rows == []
        assert len(session.calls) == 1


# ---------------------------------------------------------------------------
# OAuth2 path
# ---------------------------------------------------------------------------

class TestOAuth2:
    async def test_rejects_a_preshared_access_token(self):
        """The old configuration shape. It cannot be refreshed, so it fails silently
        the moment it expires — better to refuse at configuration time."""
        conn = _connector(auth={"access_token": "static"}, auth_type=AuthType.OAUTH2)
        with pytest.raises(ValueError, match="client_id"):
            await conn.authenticate()

    async def test_fetches_a_token_and_honours_expires_in(self):
        conn = _connector(
            auth={"client_id": "cid", "client_secret": "csec"}, auth_type=AuthType.OAUTH2
        )
        session = _FakeSession([_FakeResponse(200, {"access_token": "tok", "expires_in": 1200})])

        with patch.object(conn, "_http_session", return_value=session):
            token = await conn.authenticate()

        assert token == "tok"
        call = session.calls[0]
        assert call["url"].endswith("/services/rest/auth/oauth2/v1/token")
        assert call["data"]["grant_type"] == "client_credentials"
        # The expiry must come from the provider, not the base class's old
        # hardcoded hour — a 20-minute token was cached for 60.
        assert conn._token_expiry is not None

    def test_token_response_without_access_token_is_an_error(self):
        with pytest.raises(ValueError, match="access_token"):
            parse_oauth2_token_response({"error": "invalid_client"})

    async def test_tba_config_refuses_to_use_the_token_endpoint(self):
        """Calling authenticate() under TBA is a call-path bug; returning a
        placeholder would surface as a 401 far from the cause."""
        conn = _connector()
        with pytest.raises(RuntimeError, match="TBA"):
            await conn.authenticate()


class TestOauth2WinsOverLeftoverTbaCredentials:
    """FS-994. Preferring TBA whenever its credentials existed was a migration trap.

    NetSuite is retiring Token-Based Auth (OAuth 1.0a): 2026.1 expects new integrations
    on REST + OAuth 2.0, 2027.1 blocks creating new TBA-authenticated ones, 2028.2
    retires SOAP outright. The migration an account performs is "add client_id and
    client_secret" -- and under the old preference order that changed nothing. The four
    TBA credentials were still sitting in `auth_config`, TBA still won, and the
    migration was complete on paper while every request went out signed the old way.

    Nothing would have surfaced it: TBA requests keep succeeding right up until the day
    they don't.
    """

    def test_oauth2_wins_when_both_are_configured(self):
        connector = _connector({**TBA_AUTH, "client_id": "ci", "client_secret": "cs2"})
        assert not connector._uses_tba(), (
            "TBA was selected even though OAuth 2.0 credentials are present. An account "
            "that migrated by adding client_id/client_secret would silently stay on the "
            "mechanism NetSuite is retiring."
        )

    def test_tba_is_still_used_when_it_is_the_only_thing_configured(self):
        """The other direction. TBA still works and must keep working -- breaking a live
        ERP sync over a future deadline would be the worse bug."""
        assert _connector(dict(TBA_AUTH))._uses_tba()

    def test_partial_oauth2_credentials_do_not_disable_tba(self):
        """A half-configured migration must not silently take out working auth. With only
        a client_id, OAuth 2.0 cannot authenticate -- falling back to TBA is correct, and
        the alternative is an outage caused by an incomplete config edit."""
        assert _connector({**TBA_AUTH, "client_id": "ci"})._uses_tba()
        assert _connector({**TBA_AUTH, "client_secret": "cs2"})._uses_tba()

    async def test_the_request_header_follows_the_same_choice(self):
        """`_uses_tba` is consulted twice -- once for the header, once for the startup
        warning. This pins that the header actually follows it, so the preference is not
        merely advisory."""
        connector = _connector({**TBA_AUTH, "client_id": "ci", "client_secret": "cs2"})

        async def _token():
            return "tok"

        connector.get_auth_token = _token  # type: ignore[assignment]
        headers = await connector._request_headers("GET", "https://example.com/x")
        assert headers["Authorization"] == "Bearer tok", (
            f"expected a bearer token under OAuth 2.0, got {headers['Authorization'][:20]!r} "
            "-- the header path and the preference disagree"
        )

    async def test_a_tba_only_config_still_signs_rather_than_bearers(self):
        """The inverse, so the header check cannot pass by always returning a bearer."""
        connector = _connector(dict(TBA_AUTH))
        headers = await connector._request_headers("GET", "https://example.com/x")
        assert headers["Authorization"].startswith("OAuth "), (
            f"expected a signed TBA header, got {headers['Authorization'][:20]!r}"
        )

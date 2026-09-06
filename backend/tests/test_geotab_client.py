"""The live MyGeotab client, driven against a fake transport (FS-987..993).

WHAT THIS CAN AND CANNOT PROVE, stated up front because the distinction is the whole point.
It proves the client sends the request bodies Geotab's documentation describes, manages a
session the way that protocol requires, decodes the vendor's error taxonomy, follows a
server redirect, and pages a feed correctly. It does **not** prove Geotab agrees — this
repository has no MyGeotab credentials and Geotab publishes no isolated sandbox, so a live
smoke call is still required before the client is trusted, and `GEOTAB_SIMULATED` stays
the default until somebody makes one.

That limitation is exactly why these tests assert on the *wire* rather than on mocks of
the client's own methods. A test that stubs `client.get()` proves the caller works; these
assert the JSON that would leave the process, which is the part a live account would
disagree with.
"""
from __future__ import annotations

import json

import pytest

from app.services.geotab_client import (
    MAX_FEED_RESULTS,
    GeotabClient,
    GeotabError,
)


class _FakeResponse:
    def __init__(self, payload, headers=None):
        self._payload = payload
        self.headers = headers or {}
        self.status = 200

    async def json(self):
        return self._payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _FakeSession:
    """Records every request body and replays a scripted list of responses."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.requests = []

    def post(self, url, json=None):
        self.requests.append({"url": url, "body": json})
        if not self._responses:
            raise AssertionError(f"unexpected extra request to {url}: {json}")
        return self._responses.pop(0)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


def _client(responses, **kwargs):
    session = _FakeSession(responses)
    client = GeotabClient(
        database="db", username="u", password="p",
        session_factory=lambda: session, **kwargs
    )
    return client, session


def _auth_ok(session_id="sess-1", path=None):
    result = {"credentials": {"database": "db", "userName": "u", "sessionId": session_id}}
    if path:
        result["path"] = path
    return _FakeResponse({"result": result})


class TestAuthentication:
    async def test_it_sends_the_documented_authenticate_body(self):
        client, session = _client([_auth_ok()])
        await client.authenticate()
        body = session.requests[0]["body"]
        assert body["method"] == "Authenticate"
        assert body["params"] == {"database": "db", "userName": "u", "password": "p"}
        assert session.requests[0]["url"] == "https://my.geotab.com/apiv1"

    async def test_it_follows_a_server_redirect(self):
        """Geotab shards databases across servers: authenticating at my.geotab.com for a
        database that lives elsewhere SUCCEEDS and names the real server in `path`.
        Ignoring it sends every subsequent call to a host that does not have the data."""
        client, session = _client([
            _auth_ok(path="my3.geotab.com"),
            _auth_ok(session_id="sess-on-shard"),
        ])
        await client.authenticate()
        assert client.server == "my3.geotab.com"
        assert session.requests[1]["url"] == "https://my3.geotab.com/apiv1"
        assert client._credentials["sessionId"] == "sess-on-shard"

    async def test_thisserver_is_not_treated_as_a_redirect(self):
        """`ThisServer` means 'you are already in the right place'. Following it as a
        hostname would produce https://ThisServer/apiv1."""
        client, session = _client([_auth_ok(path="ThisServer")])
        await client.authenticate()
        assert client.server == "my.geotab.com"
        assert len(session.requests) == 1

    async def test_missing_credentials_name_the_service_account_requirement(self):
        client = GeotabClient(database="", username="", password="")
        with pytest.raises(GeotabError) as exc:
            await client.authenticate()
        assert "Service Account" in str(exc.value), (
            "the error should mention the Service Account requirement -- a personal "
            "login is the credential shape Geotab is retiring for API users"
        )


class TestTheVendorErrorTaxonomy:
    """`InvalidUserException` is a credential problem; `OverLimitException` is
    backpressure that passes on its own. Treating them alike is how a throttled
    integration gets 'fixed' by rotating credentials that were never wrong."""

    async def test_an_api_error_arrives_as_http_200_and_is_still_raised(self):
        """Geotab answers 200 with an `error` object for most failures, so a client that
        checks only `response.status` sees every failure as a success."""
        client, session = _client([
            _FakeResponse({"error": {"errors": [
                {"name": "InvalidUserException", "message": "bad password"}
            ]}})
        ])
        with pytest.raises(GeotabError) as exc:
            await client.authenticate()
        assert exc.value.name == "InvalidUserException"
        assert exc.value.is_auth_failure

    async def test_a_rate_limit_is_distinguishable_and_carries_retry_after(self):
        client, session = _client([
            _auth_ok(),
            _FakeResponse(
                {"error": {"errors": [{"name": "OverLimitException", "message": "slow down"}]}},
                headers={"Retry-After": "42"},
            ),
        ])
        with pytest.raises(GeotabError) as exc:
            await client.get("Device")
        assert exc.value.is_rate_limit
        assert not exc.value.is_auth_failure
        assert exc.value.retry_after == 42.0, (
            "Retry-After must be read, not guessed at -- retrying immediately into a rate "
            "limit is what turns a busy period into an outage"
        )


class TestSessionLifecycle:
    async def test_a_call_authenticates_once_then_reuses_the_session(self):
        client, session = _client([
            _auth_ok(),
            _FakeResponse({"result": [{"id": "b1"}]}),
            _FakeResponse({"result": [{"id": "b2"}]}),
        ])
        await client.get("Device")
        await client.get("Device")
        methods = [r["body"]["method"] for r in session.requests]
        assert methods == ["Authenticate", "Get", "Get"], (
            f"expected one Authenticate then two Gets, got {methods}"
        )

    async def test_an_expired_session_reauthenticates_and_retries_once(self):
        """A lapsed sessionId surfaces as InvalidUserException on an otherwise correct
        call. Retrying after a fresh authenticate is the difference between a
        self-healing integration and one that needs a restart."""
        client, session = _client([
            _auth_ok(session_id="old"),
            _FakeResponse({"error": {"errors": [{"name": "InvalidUserException"}]}}),
            _auth_ok(session_id="new"),
            _FakeResponse({"result": [{"id": "d1"}]}),
        ])
        devices = await client.get("Device")
        assert devices == [{"id": "d1"}]
        assert [r["body"]["method"] for r in session.requests] == [
            "Authenticate", "Get", "Authenticate", "Get"
        ]

    async def test_it_does_not_retry_forever(self):
        """Two auth failures in a row is a real credential problem, not an expired
        session -- it must surface rather than loop."""
        client, session = _client([
            _auth_ok(),
            _FakeResponse({"error": {"errors": [{"name": "InvalidUserException"}]}}),
            _auth_ok(),
            _FakeResponse({"error": {"errors": [{"name": "InvalidUserException"}]}}),
        ])
        with pytest.raises(GeotabError):
            await client.get("Device")


class TestTheRequestBodies:
    async def test_get_sends_typename_search_and_credentials(self):
        client, session = _client([_auth_ok(), _FakeResponse({"result": []})])
        await client.get("Trip", search={"deviceSearch": {"id": "b1"}}, results_limit=10)
        params = session.requests[1]["body"]["params"]
        assert params["typeName"] == "Trip"
        assert params["search"] == {"deviceSearch": {"id": "b1"}}
        assert params["resultsLimit"] == 10
        assert params["credentials"]["sessionId"] == "sess-1", (
            "every authenticated call must carry the session credentials"
        )

    async def test_the_body_is_json_serialisable(self):
        """A params dict that cannot be serialised fails at the socket, far from here."""
        client, session = _client([_auth_ok(), _FakeResponse({"result": []})])
        await client.get("Device")
        json.dumps(session.requests[1]["body"])


class TestFeedPaging:
    async def test_get_feed_returns_records_and_the_continuation_token(self):
        client, session = _client([
            _auth_ok(),
            _FakeResponse({"result": {"data": [{"id": "r1"}], "toVersion": "v2"}}),
        ])
        records, version = await client.get_feed("LogRecord")
        assert records == [{"id": "r1"}]
        assert version == "v2"

    async def test_a_resumed_feed_sends_the_token_back(self):
        client, session = _client([
            _auth_ok(),
            _FakeResponse({"result": {"data": [], "toVersion": "v3"}}),
        ])
        await client.get_feed("LogRecord", from_version="v2")
        assert session.requests[1]["body"]["params"]["fromVersion"] == "v2"

    async def test_it_refuses_a_results_limit_above_geotabs_documented_maximum(self):
        """50,000 is the documented cap. Asking for more is silently truncated by the
        API, which turns 'I asked for everything' into 'I got some of it' with no error."""
        client, _ = _client([])
        with pytest.raises(ValueError, match="50000|maximum"):
            await client.get_feed("LogRecord", results_limit=MAX_FEED_RESULTS + 1)

    async def test_iter_feed_stops_on_a_short_page(self, monkeypatch):
        """A page shorter than the limit means the feed is caught up. Continuing would
        busy-wait against a rate-limited API."""
        import app.services.geotab_client as mod

        async def _no_sleep(_seconds):
            return None

        monkeypatch.setattr(mod.asyncio, "sleep", _no_sleep)
        client, session = _client([
            _auth_ok(),
            _FakeResponse({"result": {"data": [{"id": "a"}], "toVersion": "v2"}}),
        ])
        pages = [p async for p in client.iter_feed("LogRecord", results_limit=5)]
        assert len(pages) == 1

    async def test_iter_feed_continues_while_pages_are_full(self, monkeypatch):
        import app.services.geotab_client as mod

        async def _no_sleep(_seconds):
            return None

        monkeypatch.setattr(mod.asyncio, "sleep", _no_sleep)
        full = [{"id": str(i)} for i in range(2)]
        client, session = _client([
            _auth_ok(),
            _FakeResponse({"result": {"data": full, "toVersion": "v2"}}),
            _FakeResponse({"result": {"data": [{"id": "last"}], "toVersion": "v3"}}),
        ])
        pages = [p async for p in client.iter_feed("LogRecord", results_limit=2)]
        assert len(pages) == 2
        assert session.requests[2]["body"]["params"]["fromVersion"] == "v2", (
            "the second page must resume from the first page's toVersion, or the feed "
            "re-reads history forever"
        )

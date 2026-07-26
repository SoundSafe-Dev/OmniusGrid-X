"""Validate the Intuit connector against a REAL QuickBooks company (Tier 4).

WHY THIS IS THE MOST VALUABLE INTUIT TEST AVAILABLE. `test_erp_intuit.py` asserts the
requests we BUILD, against Intuit's documentation and discovery document. That is
worth a great deal, but it cannot disconfirm a wrong assumption, because the recorder
returns whatever the code asks for.

Two things in particular can only be proven by Intuit itself:

  1. REFRESH-TOKEN ROTATION. Intuit decides when to issue a new refresh token and
     retire the old one. No fixture can prove we handle it, because the fixture's
     rotation behaviour is whatever we wrote. This is also the connector's most
     likely production failure: mishandle it and the integration works exactly once,
     then fails forever with `invalid_grant`.
  2. THE EMPTY-RESULT ENVELOPE. We believe a query matching nothing returns
     `{"QueryResponse": {}}` with the entity key absent rather than an empty list.
     That belief is load-bearing -- it is the difference between an honest zero and
     silently reporting no rows for a response we did not understand.

SETUP. The credentials come from a one-time interactive authorization; there is no
client-credentials grant to automate. Run:

    python scripts/intuit_authorize.py

then export what it prints:

    INTUIT_CLIENT_ID       from developer.intuit.com -> your app -> Keys & OAuth
    INTUIT_CLIENT_SECRET   same place
    INTUIT_REFRESH_TOKEN   printed by the authorize script
    INTUIT_REALM_ID        printed by the authorize script (the company id)
    INTUIT_ENVIRONMENT     'sandbox' (default) or 'production'

Skipped entirely when they are absent, so the default suite stays hermetic. Present
but STALE fails loudly, so an expired credential is distinguishable from an
unconfigured one.
"""

from __future__ import annotations

import os

import pytest

from app.services.erp_connector_base import AuthType, ERPConfig, ERPType
from app.services.erp_connectors.intuit_connector import IntuitConnector
from app.services.erp_connectors.intuit_qbo import QBOError

CLIENT_ID = os.environ.get("INTUIT_CLIENT_ID")
CLIENT_SECRET = os.environ.get("INTUIT_CLIENT_SECRET")
REFRESH_TOKEN = os.environ.get("INTUIT_REFRESH_TOKEN")
REALM_ID = os.environ.get("INTUIT_REALM_ID")
ENVIRONMENT = os.environ.get("INTUIT_ENVIRONMENT", "sandbox")

pytestmark = pytest.mark.skipif(
    not all([CLIENT_ID, CLIENT_SECRET, REFRESH_TOKEN, REALM_ID]),
    reason=(
        "needs a real QuickBooks company: set INTUIT_CLIENT_ID, INTUIT_CLIENT_SECRET, "
        "INTUIT_REFRESH_TOKEN, INTUIT_REALM_ID (run scripts/intuit_authorize.py)"
    ),
)


def _connector(**configuration) -> IntuitConnector:
    config = ERPConfig(
        erp_type=ERPType.INTUIT,
        auth_type=AuthType.OAUTH2,
        base_url="",
        auth_config={
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "refresh_token": REFRESH_TOKEN,
        },
        rate_limit={"requests_per_minute": 500},
        configuration={
            "realm_id": REALM_ID,
            "environment": ENVIRONMENT,
            **configuration,
        },
    )
    return IntuitConnector(config, "org-1", "int-1")


class TestAuthentication:
    async def test_the_refresh_token_actually_works(self):
        """Proves the credential is live, not merely that we sent something."""
        token = await _connector().get_auth_token()
        assert token and isinstance(token, str)

    async def test_a_wrong_client_secret_is_rejected(self):
        """A connector that cannot tell a good credential from a bad one reports
        every misconfiguration as an empty result set."""
        connector = _connector()
        connector.config.auth_config["client_secret"] = "definitely-wrong"
        connector.invalidate_token()
        with pytest.raises(Exception):
            await connector.get_auth_token()

    async def test_a_retired_refresh_token_reports_invalid_grant(self):
        """The failure everyone will eventually hit. It must name itself, because
        `invalid_grant` is the signal that a rotation was lost -- anything vaguer and
        nobody looks at persistence."""
        connector = _connector()
        connector.config.auth_config["refresh_token"] = "definitely-not-a-refresh-token"
        connector.invalidate_token()
        with pytest.raises(Exception) as excinfo:
            await connector.get_auth_token()
        assert "invalid_grant" in str(excinfo.value).lower()

    async def test_a_permanent_auth_failure_is_attempted_only_once(self):
        """Against the real endpoint, not a recorder. Retrying replays the same
        rejected credential and hammers Intuit's token endpoint, which is how an
        integration earns a rate-limit block on top of its original problem."""
        connector = _connector()
        connector.config.auth_config["refresh_token"] = "definitely-not-a-refresh-token"
        connector.invalidate_token()

        attempts = {"n": 0}
        original = connector._is_transient_error

        def _counting(error):
            attempts["n"] += 1
            return original(error)

        connector._is_transient_error = _counting
        with pytest.raises(Exception):
            await connector.get_auth_token()
        assert attempts["n"] == 1, f"a dead refresh token was retried {attempts['n']}x"


class TestRefreshTokenRotation:
    """THE ASSERTION THIS HARNESS EXISTS FOR.

    Only Intuit decides when to rotate. If it rotates during this run and the new
    value is captured, the mechanism is proven end to end against the real thing. If
    it does not rotate, that is also a real observation rather than a fixture's
    opinion -- so this test reports which happened instead of pretending certainty.
    """

    async def test_a_rotation_if_it_happens_is_captured(self):
        captured: list[str] = []
        connector = _connector(refresh_token_sink=captured.append)

        before = connector.config.auth_config["refresh_token"]
        await connector.authenticate()
        after = connector.config.auth_config["refresh_token"]

        if after != before:
            # Intuit rotated. The sink must have been told, or the next process to
            # start would authenticate with a retired token.
            assert captured == [after], (
                "Intuit rotated the refresh token but the sink was not called -- this "
                "is the 'works once, then dies forever' bug"
            )
            print(f"\nIntuit ROTATED the refresh token; sink captured it. New: {after[:12]}...")
        else:
            assert captured == [], "reported a rotation that did not happen"
            print("\nIntuit did not rotate on this refresh (also a real observation)")

    async def test_the_token_expiry_is_intuits_not_ours(self):
        """A hardcoded lifetime means serving a dead credential from cache, and every
        request in that window fails with a 401 that looks like a permissions
        problem."""
        from datetime import datetime, timezone

        connector = _connector()
        await connector.authenticate()
        remaining = (connector._token_expiry - datetime.now(timezone.utc)).total_seconds()
        # QBO access tokens are an hour; the skew must leave it comfortably inside.
        assert 0 < remaining <= 3600, remaining


class TestFetching:
    async def test_reads_the_company_record(self):
        """`CompanyInfo` exists in every QuickBooks company, which is why it is the
        health probe."""
        rows = await _connector().fetch_data("CompanyInfo")
        assert rows, "CompanyInfo returned nothing, which should be impossible"
        assert "Id" in rows[0] or "CompanyName" in rows[0]

    async def test_a_query_matching_nothing_returns_an_honest_empty_list(self):
        """CONFIRMS THE ENVELOPE BELIEF AGAINST REAL INTUIT.

        We coded for `{"QueryResponse": {}}` with the entity key ABSENT. If that is
        wrong, `parse_query_response` would raise here rather than return [] -- which
        is the correct failure, and exactly why the envelope is validated instead of
        defaulting to zero rows.
        """
        rows = await _connector().fetch_data(
            "Customer", filters={"DisplayName": "no-such-customer-zzz-omniusgrid"}
        )
        assert rows == []

    async def test_pagination_returns_more_than_one_page(self):
        """Paging is where silent truncation lives. With page_size=2 the connector
        must issue several requests and return their union.

        The sandbox company ships demo customers. If it has fewer than 3, this skips
        rather than passing vacuously -- a paging test against 1 row proves nothing.
        """
        available = await _connector().fetch_data("Customer", limit=10)
        if len(available) < 3:
            pytest.skip(f"company has only {len(available)} customers; need 3+ to page")

        rows = await _connector(page_size=2).fetch_data("Customer", limit=5)
        assert len(rows) > 2, f"paging stopped after the first page: {len(rows)} rows"
        ids = [r["Id"] for r in rows]
        assert len(ids) == len(set(ids)), "pagination returned duplicate rows"

    async def test_limit_is_respected_exactly(self):
        available = await _connector().fetch_data("Customer", limit=10)
        if len(available) < 2:
            pytest.skip("not enough customers to test a limit")
        rows = await _connector(page_size=1).fetch_data("Customer", limit=2)
        assert len(rows) == 2

    async def test_a_filter_actually_reaches_quickbooks(self):
        """Proves the where clause is understood rather than dropped. A dropped
        filter returns everything, which looks like a valid answer."""
        everyone = await _connector().fetch_data("Customer", limit=50)
        if not everyone:
            pytest.skip("no customers in this company")

        name = everyone[0].get("DisplayName")
        if not name:
            pytest.skip("first customer has no DisplayName to filter on")

        matched = await _connector().fetch_data("Customer", filters={"DisplayName": name})
        assert matched, "the filter returned nothing for a name we just read back"
        assert all(r.get("DisplayName") == name for r in matched)

    async def test_an_apostrophe_in_a_filter_does_not_break_the_query(self):
        """The escaping test that matters, run against the real parser.

        QBO's query language is SQL-shaped and literals are single-quoted, so an
        unescaped apostrophe ends the literal and the rest is parsed as syntax. Real
        QuickBooks is the only thing that can confirm our escaping is the escaping it
        expects. A ValidationFault here means we got it wrong.
        """
        rows = await _connector().fetch_data(
            "Customer", filters={"DisplayName": "O'Brien & Sons \\ Test"}
        )
        assert rows == []  # no such customer, but it must PARSE

    async def test_an_unknown_entity_raises_rather_than_returning_empty(self):
        """A connector that turns a typo'd entity into an empty result set gives a
        plausible answer that is simply wrong -- the failure class found throughout
        this codebase."""
        connector = _connector()
        connector.retry_config["max_retries"] = 0
        with pytest.raises((QBOError, Exception)):
            await connector.fetch_data("NoSuchEntityZZZ")


class TestHealthCheck:
    async def test_healthy_against_a_real_company(self):
        health = await _connector().health_check()
        assert health["status"] == "healthy", health

    async def test_a_bad_credential_is_unhealthy_not_degraded(self):
        """A wrong credential is an outage; reporting it as degraded means nobody is
        paged for an integration that cannot work at all."""
        connector = _connector()
        connector.config.auth_config["refresh_token"] = "definitely-wrong"
        connector.invalidate_token()
        connector.retry_config["max_retries"] = 0
        health = await connector.health_check()
        assert health["status"] == "unhealthy", health
        assert health.get("failure") == "authentication", health

    async def test_an_unreachable_host_is_unhealthy(self):
        """A health check that cannot go red is not a health check."""
        connector = _connector()
        connector.host = "http://127.0.0.1:1"  # nothing listening
        connector.retry_config["max_retries"] = 0
        health = await connector.health_check()
        assert health["status"] == "unhealthy", health

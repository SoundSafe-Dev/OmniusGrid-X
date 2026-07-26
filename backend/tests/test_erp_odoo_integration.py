"""End-to-end validation of the Odoo connector against a REAL Odoo (Tier 3).

WHY THIS IS THE MOST VALUABLE ERP TEST WE HAVE. Every other ERP test in this repo
asserts the request we BUILD, against our reading of the vendor's documentation.
That caught a great deal — a non-existent NetSuite host, a bearer header where
OAuth 1.0a was required, missing pagination — but it cannot disconfirm a wrong
assumption, because the fixture encodes the same assumption as the code.

Odoo is the one ERP in the matrix that is genuinely self-hostable, so here the
server gets a vote. It exercises real authentication, real access-rights errors,
real pagination and a real database.

It is worth more than "one of seven" implies: the shared machinery every connector
depends on — token lifecycle, retry, circuit breaker, rate limiting, the JSON-RPC
transport — is proven against a real server rather than a mock we wrote.

    docker compose -f docker-compose.erp-sandbox.yml up -d
    # wait for healthy, then create the database (scripts/setup_odoo_sandbox.py)
    RUN_ODOO_INTEGRATION=1 pytest tests/test_erp_odoo_integration.py

Skipped unless RUN_ODOO_INTEGRATION=1, matching the SMTP integration test's
convention, so the default suite stays hermetic.
"""

from __future__ import annotations

import os

import pytest

from app.services.erp_connector_base import AuthType, ERPConfig, ERPType
from app.services.erp_connectors.odoo_connector import OdooConnector

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_ODOO_INTEGRATION") != "1",
    reason="needs a live Odoo; set RUN_ODOO_INTEGRATION=1 (see docker-compose.erp-sandbox.yml)",
)

ODOO_URL = os.environ.get("ODOO_URL", "http://localhost:8169")
ODOO_DB = os.environ.get("ODOO_DB", "omniusgrid_test")
ODOO_USER = os.environ.get("ODOO_USER", "admin")
ODOO_PASSWORD = os.environ.get("ODOO_PASSWORD", "admin")


def _connector(**configuration) -> OdooConnector:
    config = ERPConfig(
        erp_type=ERPType.ODOO,
        base_url=ODOO_URL,
        auth_type=AuthType.API_KEY,
        auth_config={"api_key": ODOO_PASSWORD, "username": ODOO_USER},
        rate_limit={"requests_per_minute": 600},
        configuration={
            "db_name": ODOO_DB,
            "api_type": "jsonrpc",
            **configuration,
        },
    )
    return OdooConnector(config, "org-1", "int-1")


class TestAuthentication:
    async def test_authenticates_against_a_real_odoo(self):
        """Proves the credential actually works, not just that we sent something."""
        conn = _connector()
        uid = await conn._rpc_uid()
        assert isinstance(uid, int) and uid > 0

    async def test_wrong_credential_is_rejected(self):
        """A connector that cannot tell a good credential from a bad one would
        report every misconfiguration as an empty result set."""
        conn = _connector()
        conn.config.auth_config["api_key"] = "definitely-wrong"
        conn.invalidate_token()
        with pytest.raises(Exception):
            await conn._rpc_uid()

    async def test_unknown_database_is_reported(self):
        conn = _connector(db_name="no-such-database")
        with pytest.raises(Exception):
            await conn._rpc_uid()


class TestFetching:
    async def test_reads_real_records(self):
        """The demo dataset ships partners; this asserts we get real rows back
        through the connector's own code path, not a fixture."""
        conn = _connector()
        rows = await conn.fetch_data("res.partner", limit=5)
        assert rows, "no records returned from a database seeded with demo data"
        assert len(rows) <= 5
        assert "id" in rows[0]

    async def test_pagination_returns_more_than_one_page(self):
        """Paging is where silent truncation lives. With page_size=2 the connector
        must issue several calls and return their union — the NetSuite defect was
        exactly this, reading page one and stopping."""
        conn = _connector(page_size=2)
        rows = await conn.fetch_data("res.partner", limit=7)
        assert len(rows) > 2, f"paging stopped after the first page: {len(rows)} rows"
        ids = [r["id"] for r in rows]
        assert len(ids) == len(set(ids)), "pagination returned duplicate rows"

    async def test_limit_is_respected_exactly(self):
        conn = _connector(page_size=2)
        rows = await conn.fetch_data("res.partner", limit=3)
        assert len(rows) == 3

    async def test_domain_filter_actually_narrows_the_result(self):
        """Proves the filter reaches Odoo and is understood. A domain Odoo cannot
        parse raises a server-side fault rather than silently returning everything,
        so an unnarrowed result here would mean the filter was dropped."""
        conn = _connector()
        everyone = await conn.fetch_data("res.partner", limit=100)
        companies = await conn.fetch_data("res.partner", filters={"is_company": True}, limit=100)

        assert companies, "filter returned nothing at all"
        assert len(companies) < len(everyone), "the filter did not narrow anything"

    async def test_unknown_model_raises_rather_than_returning_empty(self):
        """THE ASSERTION THIS WHOLE HARNESS EXISTS FOR.

        Odoo reports application errors in the BODY with HTTP 200. A connector
        that treats 200 as success turns an access-rights failure or a typo'd
        model name into an empty result set — a plausible answer that is simply
        wrong, and the exact class of silent failure found throughout this
        codebase. Verified here against a real server, not a fixture.
        """
        conn = _connector()
        with pytest.raises(Exception) as excinfo:
            await conn.fetch_data("no.such.model")
        assert "no.such.model" in str(excinfo.value) or "Object" in str(excinfo.value)


class TestHealthCheck:
    """The three states must be distinguishable, verified against a real server.

    Every connector's health check used to map ANY exception to `unhealthy`, so
    "the credential is wrong", "the host is unreachable" and "that module is not
    installed" were indistinguishable — and a tenant without the probed module had
    a working integration reported as an outage.
    """

    async def test_healthy_against_a_live_server(self):
        health = await _connector().health_check()
        assert health["status"] == "healthy", health

    async def test_missing_module_is_DEGRADED_not_unhealthy(self):
        """`sale.order` needs the Sales module, which this database does not have.
        A monitor must not page for that — the integration is fine."""
        health = await _connector().probe_health("sale.order")
        assert health["status"] == "degraded", health
        assert health["failure"] == "probe_entity"

    async def test_bad_credential_is_UNHEALTHY(self):
        """This is what caught a flaw in the probe's own design: Odoo's API-key path
        returns the key straight from config without contacting anything, so
        `get_auth_token()` "succeeded" and a wrong key was reported DEGRADED. Odoo
        now overrides verify_credentials() with a real round trip."""
        conn = _connector()
        conn.config.auth_config["api_key"] = "definitely-wrong"
        conn.invalidate_token()
        health = await conn.health_check()
        assert health["status"] == "unhealthy", health
        assert health["failure"] == "authentication"

    async def test_unreachable_server_is_UNHEALTHY(self):
        """A health check that cannot go red is not a health check."""
        conn = _connector()
        conn.config.base_url = "http://localhost:1"  # nothing listening
        conn.api_url = "http://localhost:1/api"
        health = await conn.health_check()
        assert health["status"] == "unhealthy", health

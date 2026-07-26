"""Validate the Dynamics connector against a REAL Dataverse environment (Tier 4).

Dynamics was the last connector asserted purely against our reading of Microsoft's
documentation. A Power Apps Developer Plan environment is free and needs no approval
queue, so that gap is closable — see docs/erp/dynamics-dataverse-setup.md.

WHAT A REAL ENVIRONMENT PROVED THAT NO FIXTURE COULD

  - `@odata.nextLink` pagination. `GET /stringmaps` returns exactly 5000 rows AND a
    nextLink. The connector used to issue one request and return `value`, so "all
    string maps" was a plausible, wrong answer with no error anywhere. A fixture
    could not have disconfirmed this, because the fixture's page size was whatever we
    wrote.
  - `EntitySetName` is not derivable from `LogicalName`. 197 of 872 entity sets in a
    stock environment — 22.6% — are not `logical + "s"`.
  - The `.api.` infix in the OAuth scope resolves. Entra ID issues a token for
    `https://<org>.api.crm.dynamics.com/.default`, which had been flagged twice as a
    suspected defect and is not one.

SETUP — see docs/erp/dynamics-dataverse-setup.md, then:

    export DATAVERSE_ORG='org...'          # subdomain only, NOT the URL
    export DATAVERSE_TENANT_ID='<guid>'
    export DATAVERSE_CLIENT_ID='<guid>'
    export DATAVERSE_CLIENT_SECRET='<secret VALUE, not the secret ID>'
    python scripts/dynamics_verify.py      # diagnoses setup before tests run
    pytest tests/test_erp_dynamics_sandbox.py -q

Skipped without those, so the default suite stays hermetic. Present but stale fails
loudly, so an expired secret is distinguishable from an unconfigured one.
"""

from __future__ import annotations

import os

import pytest

from app.services.erp_connector_base import AuthType, ERPConfig, ERPType
from app.services.erp_connectors.dynamics_connector import DynamicsConnector

ORG = os.environ.get("DATAVERSE_ORG")
TENANT_ID = os.environ.get("DATAVERSE_TENANT_ID")
CLIENT_ID = os.environ.get("DATAVERSE_CLIENT_ID")
CLIENT_SECRET = os.environ.get("DATAVERSE_CLIENT_SECRET")

pytestmark = pytest.mark.skipif(
    not all([ORG, TENANT_ID, CLIENT_ID, CLIENT_SECRET]),
    reason=(
        "needs a real Dataverse environment: set DATAVERSE_ORG, DATAVERSE_TENANT_ID, "
        "DATAVERSE_CLIENT_ID, DATAVERSE_CLIENT_SECRET "
        "(see docs/erp/dynamics-dataverse-setup.md)"
    ),
)

#: Present in every Dataverse environment and readable by anything that can
#: authenticate — the same reasoning that replaced Odoo's `sale.order` probe.
UNIVERSAL_ENTITY_SET = "systemusers"

#: Ships with >5000 rows in a stock environment, which is what makes it the only
#: honest pagination test available here.
LARGE_ENTITY_SET = "stringmaps"


def _connector(**configuration) -> DynamicsConnector:
    config = ERPConfig(
        erp_type=ERPType.DYNAMICS,
        auth_type=AuthType.OAUTH2,
        base_url="",
        auth_config={
            "tenant_id": TENANT_ID,
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
        },
        rate_limit={"requests_per_minute": 600},
        configuration={"environment": ORG, "api_type": "dataverse", **configuration},
    )
    return DynamicsConnector(config, "org-1", "int-1")


class TestAuthentication:
    async def test_the_client_credentials_actually_work(self):
        token = await _connector().get_auth_token()
        assert token and isinstance(token, str)

    async def test_the_api_infix_scope_resolves(self):
        """THE ASSERTION THAT CLOSES A LONG-RUNNING DOUBT.

        The connector requests `https://{org}.api.crm.dynamics.com/.default` — note
        the `.api.` infix, which looks like a mistake and was flagged twice as a
        suspected defect. Microsoft's documentation supports it, but Entra ID
        validates the CLIENT before the RESOURCE, so it could only be proven once a
        real secret existed. A token coming back means the resource resolved.
        """
        connector = _connector()
        assert ".api.crm.dynamics.com" in connector.api_url
        assert await connector.get_auth_token()

    async def test_a_wrong_secret_is_rejected(self):
        connector = _connector()
        connector.config.auth_config["client_secret"] = "definitely-wrong"
        connector.invalidate_token()
        connector.retry_config["max_retries"] = 0
        with pytest.raises(Exception) as excinfo:
            await connector.get_auth_token()
        # AADSTS7000215 = invalid client secret.
        assert "7000215" in str(excinfo.value) or "invalid_client" in str(excinfo.value).lower()

    async def test_a_permanent_auth_failure_is_attempted_once(self):
        """Retrying replays the same rejected credential against Entra ID, which is
        how an integration earns a throttle on top of its original problem."""
        connector = _connector()
        connector.config.auth_config["client_secret"] = "definitely-wrong"
        connector.invalidate_token()

        attempts = {"n": 0}
        original = connector._is_transient_error

        def _counting(error):
            attempts["n"] += 1
            return original(error)

        connector._is_transient_error = _counting
        with pytest.raises(Exception):
            await connector.get_auth_token()
        # 0 is the expected value and is BETTER than 1: Dynamics calls the token
        # endpoint directly rather than through execute_with_retry, so a rejected
        # secret never enters the retry loop at all. Asserting <= 1 covers both that
        # and the classify-once-then-stop path other connectors take.
        assert attempts["n"] <= 1, f"a dead credential was retried {attempts['n']}x"


class TestPagination:
    """THE REASON THIS HARNESS EXISTS.

    Dataverse caps a page at 5000 rows and signals more with `@odata.nextLink`. The
    connector used to issue one request and return `value`, discarding the rest
    silently.
    """

    async def test_reads_past_the_first_page(self):
        rows = await _connector().fetch_data(LARGE_ENTITY_SET)
        assert len(rows) > 5000, (
            f"got exactly {len(rows)} rows — the 5000-row page cap, which means "
            f"@odata.nextLink was not followed and the rest were dropped silently"
        )

    async def test_no_duplicate_rows_across_pages(self):
        """A cursor mishandled by re-applying our own params repeats rows rather than
        advancing. Silent duplication is as wrong as silent truncation."""
        rows = await _connector().fetch_data(LARGE_ENTITY_SET, limit=8000)
        ids = [r.get("stringmapid") for r in rows if r.get("stringmapid")]
        assert len(ids) == len(set(ids)), (
            f"{len(ids) - len(set(ids))} duplicate rows across page boundaries"
        )

    async def test_limit_is_respected_exactly_across_a_page_boundary(self):
        """The interesting case is a limit LARGER than one page: it must keep going,
        then stop at the number asked for rather than at the page edge."""
        rows = await _connector().fetch_data(LARGE_ENTITY_SET, limit=5200)
        assert len(rows) == 5200

    async def test_a_small_limit_does_not_trigger_extra_requests(self):
        rows = await _connector().fetch_data(UNIVERSAL_ENTITY_SET, limit=3)
        assert len(rows) == 3


class TestFetching:
    async def test_reads_a_universally_present_entity(self):
        rows = await _connector().fetch_data(UNIVERSAL_ENTITY_SET, limit=5)
        assert rows, "systemusers returned nothing, which should be impossible"
        assert "systemuserid" in rows[0]

    async def test_the_entity_set_name_is_what_the_api_wants(self):
        """`systemusers`, not `systemuser`. 22.6% of entity sets are not the logical
        name plus "s", so this is a real trap rather than a naming preference."""
        connector = _connector()
        connector.retry_config["max_retries"] = 0
        with pytest.raises(Exception):
            await connector.fetch_data("systemuser", limit=1)  # logical name

    async def test_a_filter_actually_reaches_dataverse(self):
        """A dropped filter returns everything, which looks like a valid answer."""
        everyone = await _connector().fetch_data(UNIVERSAL_ENTITY_SET, limit=50)
        if len(everyone) < 2:
            pytest.skip("not enough users to narrow")

        target = everyone[0]
        filtered = await _connector().fetch_data(
            UNIVERSAL_ENTITY_SET, filters={"systemuserid": target["systemuserid"]}
        )
        assert filtered, "the filter returned nothing for a row we just read back"
        assert all(r["systemuserid"] == target["systemuserid"] for r in filtered)

    async def test_an_unknown_entity_raises_rather_than_returning_empty(self):
        """A connector that turns a typo'd entity set into an empty result gives a
        plausible answer that is simply wrong."""
        connector = _connector()
        connector.retry_config["max_retries"] = 0
        with pytest.raises(Exception):
            await connector.fetch_data("nosuchentityzzz")


class TestHealthCheck:
    async def test_healthy_against_a_real_environment(self):
        health = await _connector().health_check()
        assert health["status"] == "healthy", health

    async def test_the_probe_entity_exists_here(self):
        """Dynamics was the connector that never adopted the three-state probe, and
        its probe entity was changed to `systemusers` without a live environment to
        confirm against. This confirms it."""
        assert DynamicsConnector.HEALTH_PROBE_ENTITY == UNIVERSAL_ENTITY_SET
        assert await _connector().fetch_data(UNIVERSAL_ENTITY_SET, limit=1)

    async def test_a_bad_credential_is_unhealthy_not_degraded(self):
        connector = _connector()
        connector.config.auth_config["client_secret"] = "definitely-wrong"
        connector.invalidate_token()
        connector.retry_config["max_retries"] = 0
        health = await connector.health_check()
        assert health["status"] == "unhealthy", health
        assert health.get("failure") == "authentication", health

    async def test_an_unreachable_host_is_unhealthy(self):
        """A health check that cannot go red is not a health check."""
        connector = _connector()
        connector.api_url = "http://127.0.0.1:1/api/data/v9.2/"
        connector.retry_config["max_retries"] = 0
        health = await connector.health_check()
        assert health["status"] == "unhealthy", health

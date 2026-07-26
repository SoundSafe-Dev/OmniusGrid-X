"""Permanent failures must not be retried — for every connector.

`ERPConnectorBase._is_transient_error` decides whether `execute_with_retry` tries
again. It defaulted to "transient" for anything it did not recognise, and the only
auth cases it recognised were `401` and `unauthorized` — while `AUTH_ERROR_MARKERS`,
defined a few lines above it in the same class, already knew about `403`,
`invalid_client` and `access denied`.

So the health probe and the retry loop disagreed about the same error: the probe
called it an authentication failure, the retry loop called it transient and tried
three more times with exponential backoff.

WHY THAT IS WORSE THAN WASTEFUL. The access token is captured in the operation's
closure before the retry loop runs, so every attempt replays the SAME rejected
credential — it cannot succeed. Meanwhile the provider's token endpoint is hit four
times with a credential that will never work, which is how an integration collects a
rate-limit block on top of its original problem.

Found while testing the Intuit connector, where a retired refresh token returns
`invalid_grant`. Intuit rotates refresh tokens on every use, so `invalid_grant` is
both the most likely production failure and the most permanent one.
"""

from __future__ import annotations

import pytest

from app.services.erp_connector_base import AuthType, ERPConfig, ERPType
from app.services.erp_connectors.odoo_connector import OdooConnector


@pytest.fixture
def connector():
    return OdooConnector(
        ERPConfig(
            erp_type=ERPType.ODOO,
            auth_type=AuthType.API_KEY,
            base_url="https://erp.example.com",
            auth_config={"api_key": "k", "username": "u"},
            rate_limit={"requests_per_minute": 60},
            configuration={"db_name": "db", "api_type": "jsonrpc"},
        ),
        "org-1",
        "int-1",
    )


# Errors that can never succeed on a retry.
PERMANENT = [
    "HTTP 401 Unauthorized",
    "Unauthorized",
    "HTTP 403 Forbidden",
    "Forbidden",
    "Access Denied",
    "invalid_grant: refresh token expired",
    "invalid_client",
    "invalid_token",
    "invalid credentials supplied",
    "HTTP 404 Not Found",
]

# Errors that genuinely clear on their own.
TRANSIENT = [
    "429 rate limit exceeded",
    "Rate limit reached, retry later",
    "Request timeout after 30s",
    "503 Service Unavailable",
    "502 Bad Gateway",
    "connection reset by peer",
]


class TestPermanentFailuresAreNotRetried:
    @pytest.mark.parametrize("message", PERMANENT)
    def test_classified_as_permanent(self, connector, message):
        assert connector._is_transient_error(Exception(message)) is False, message

    def test_invalid_grant_specifically(self, connector):
        """The Intuit case. A rotated-away refresh token is as final as it gets, and
        retrying it four times both wastes seven seconds and hammers the token
        endpoint."""
        assert connector._is_transient_error(Exception("invalid_grant")) is False


class TestTransientFailuresAreStillRetried:
    @pytest.mark.parametrize("message", TRANSIENT)
    def test_classified_as_transient(self, connector, message):
        """The other half of the guard. Over-broadly marking things permanent would
        stop retrying failures that do clear — a worse regression than the one being
        fixed, because it turns a momentary blip into a failed sync."""
        assert connector._is_transient_error(Exception(message)) is True, message

    def test_an_unknown_error_still_defaults_to_transient(self, connector):
        assert connector._is_transient_error(Exception("something unfamiliar")) is True


class TestClassificationIsConsistentWithTheHealthProbe:
    def test_every_auth_marker_is_treated_as_permanent(self, connector):
        """THE ROOT CAUSE OF THE ORIGINAL DISAGREEMENT.

        `AUTH_ERROR_MARKERS` is what `probe_health` uses to decide an error is an
        authentication failure rather than a missing entity. Anything on that list
        is, by definition, an auth failure — so the retry loop must not consider it
        transient. Keeping the two in agreement is what stops them drifting apart
        again.

        `expired` and `authentication` are excluded: both appear in messages about
        expiry that a re-authentication does clear, so they are auth-shaped without
        being permanently fatal on their own.
        """
        ambiguous = {"expired", "authentication"}
        for marker in connector.AUTH_ERROR_MARKERS:
            if marker in ambiguous:
                continue
            assert connector._is_transient_error(Exception(f"error: {marker}")) is False, marker


class TestRetryLoopHonoursTheClassification:
    async def test_a_permanent_error_is_attempted_exactly_once(self, connector):
        attempts = []

        async def _op():
            attempts.append(1)
            raise Exception("invalid_grant")

        with pytest.raises(Exception, match="invalid_grant"):
            await connector.execute_with_retry(_op)

        assert len(attempts) == 1, f"a permanently-dead credential was retried {len(attempts)}x"

    async def test_a_transient_error_is_retried(self, connector):
        attempts = []

        async def _op():
            attempts.append(1)
            if len(attempts) < 2:
                raise Exception("503 Service Unavailable")
            return "recovered"

        connector.retry_config["initial_delay"] = 0
        assert await connector.execute_with_retry(_op) == "recovered"
        assert len(attempts) == 2

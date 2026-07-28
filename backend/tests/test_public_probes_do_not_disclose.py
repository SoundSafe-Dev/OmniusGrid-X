"""Public health probes must report status, not internal topology.

THE DISCLOSURE. `_check_message_broker` returns strings like

    "error: KafkaConnectionError: Unable to bootstrap from [('redpanda', 29092, ...)]"

and `/health/ready` and `/health/kafka` returned them verbatim — to an **unauthenticated**
caller. That is the internal broker hostname, its port and the technology in use, handed
to anyone who can reach the endpoint.

WHAT MAKES IT A DEFECT RATHER THAN A CHOICE. The design was already stated, one function
away, on `/health/detailed`:

    Auth-gated for the same reason as /health/system: the per-component report
    (broker/redis/ingestion state, connection error strings) is recon-useful.
    Probes use /health/live|ready, which stay public.

The gating was right and the reasoning explicit. The same strings simply escaped through
the probes that were supposed to be the safe alternative. A rule enforced in one place and
leaked in the neighbouring one is the recurring shape of this whole sweep.

WHAT THE FIX WITHHOLDS, AND FROM WHOM. Nothing, from anyone entitled to it. A probe
consumer needs the STATUS — Kubernetes reads the status code, not the body. An operator
reads the logs or `/health/detailed`, both of which still carry the full exception text.
Only the anonymous caller loses something, and only the part that was never theirs.

Statuses that are already coarse ("ok", "skipped", "degraded") pass through unchanged;
anything carrying a payload after a colon collapses to its first word.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio

#: Substrings that must never appear in a response served without authentication.
#: Hostname and port come from the compose/k8s topology; the exception names disclose
#: which technologies are in play and how they are reached.
FORBIDDEN = (
    "redpanda",
    "29092",
    "KafkaConnectionError",
    "Traceback",
    "asyncpg",
    "psycopg",
    "postgresql://",
)

PUBLIC_PROBES = (
    "/health",
    "/health/live",
    "/health/ready",
    "/health/startup",
    "/health/db",
    "/health/redis",
    "/health/kafka",
)


async def _get(app, path):
    from httpx import ASGITransport, AsyncClient

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        return await client.get(path)


class TestNoInternalDetailEscapes:
    @pytest.mark.parametrize("path", PUBLIC_PROBES)
    async def test_the_response_names_no_internal_host_or_driver(self, app, path):
        """THE ASSERTION THIS FILE EXISTS FOR. /health/kafka and /health/ready both
        returned the broker's hostname and port when the broker was unreachable — which
        is exactly when someone probing would be looking."""
        response = await _get(app, path)
        body = response.text
        for needle in FORBIDDEN:
            assert needle not in body, (
                f"{path} disclosed {needle!r} to an unauthenticated caller:\n"
                f"{body[:400]}"
            )

    @pytest.mark.parametrize("path", PUBLIC_PROBES)
    async def test_the_probe_still_answers(self, app, path):
        """Redaction must not turn a probe into an error. Kubernetes reads the status
        code; 200 and 503 are both valid answers, anything else is a broken probe."""
        response = await _get(app, path)
        assert response.status_code in (200, 503), (
            f"{path} -> {response.status_code}; a probe must answer"
        )


class TestTheStatusIsStillUsable:
    async def test_readiness_still_reports_per_component_status(self, app):
        """Collapsing the strings must not empty the report — an operator watching the
        probe still needs to see WHICH component is unhealthy, just not why."""
        response = await _get(app, "/health/ready")
        body = response.json()
        checks = body.get("checks") or (
            body.get("error", {}).get("details", {}).get("detail", {}).get("checks", {})
        )
        assert checks, f"no per-component checks in the readiness response: {body}"
        assert "database" in checks and "message_broker" in checks

    async def test_an_unhealthy_component_is_still_identifiable(self, app):
        """`error` is a usable signal; `error: <exception with hostnames>` is a leak.
        The distinction is the whole point, so pin that the coarse word survives."""
        response = await _get(app, "/health/ready")
        body = response.json()
        checks = body.get("checks") or (
            body.get("error", {}).get("details", {}).get("detail", {}).get("checks", {})
        )
        for name, value in checks.items():
            assert ":" not in str(value), (
                f"check {name!r} still carries a payload after the colon: {value!r}"
            )


class TestTheDetailedReportKeepsTheFullText:
    """The information is not destroyed, only gated. If `/health/detailed` ever stops
    requiring a user, this suite's premise collapses."""

    async def test_detailed_health_requires_authentication(self, app):
        response = await _get(app, "/health/detailed")
        assert response.status_code in (401, 403), (
            f"/health/detailed answered {response.status_code} without a token — it "
            f"carries the full connection error text that the probes now withhold"
        )

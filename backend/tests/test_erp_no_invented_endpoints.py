"""No connector may claim success for work it did not do.

THE DEFECT THIS GUARDS, PROVEN AGAINST A REAL SERVER

All seven original connectors carried the same copy-pasted `subscribe_to_events`:
POST to a `/webhooks`-shaped URL with a `{name, url, event_type}` body. The payloads
were byte-identical across seven unrelated vendors, so at most one could have been
correct. None was.

Run against the live Odoo container, it returned **True**. `POST /webhooks` is a 404
on Odoo. What actually happened is worse: the connector's URL resolved to
`/xmlrpc/2/webhooks`, Odoo's `/xmlrpc/2/<...>` route matches anything, and it
answered **HTTP 200 with an XML-RPC fault body containing a traceback**. The
connector checked only `status not in (200, 201)`, saw 200, and reported success for
a subscription that was never created.

That is the worst failure shape available: an operator enables real-time ERP events,
the platform confirms it, and no event ever arrives — with no error anywhere to look
at. It is also the same Odoo trap already fixed on the read path (application faults
arrive in the BODY with HTTP 200) surviving in a path nobody had exercised.

These tests are hermetic and source-level, so they hold for the six vendors whose
systems we cannot reach.
"""

from __future__ import annotations

import ast
import inspect
import re
from pathlib import Path
from typing import List
from unittest.mock import patch

import pytest

from app.services.erp_connector_base import AuthType, ERPConfig, ERPConnectorBase, ERPType
from app.services.erp_connector_factory import _REGISTRY, _resolve_class

CONNECTOR_DIR = Path(__file__).resolve().parents[1] / "app" / "services" / "erp_connectors"

ALL_TYPES = sorted(_REGISTRY, key=lambda t: t.value)


def _connector(erp_type: ERPType) -> ERPConnectorBase:
    """Construct any connector with a config generic enough for all of them."""
    cls = _resolve_class(erp_type)
    config = ERPConfig(
        erp_type=erp_type,
        auth_type=AuthType.API_KEY,
        base_url="https://erp.example.com",
        auth_config={
            "api_key": "k", "username": "u", "password": "p",
            "client_id": "c", "client_secret": "s", "refresh_token": "r",
        },
        rate_limit={"requests_per_minute": 60},
        configuration={
            "db_name": "db", "company_id": "co", "tenant_id": "t",
            "realm_id": "123", "environment": "sandbox", "account_id": "a",
            # Deliberately supplied: the old implementations only attempted a
            # subscription when a webhook_url was configured, so omitting it would
            # make these tests pass without exercising anything.
            "webhook_url": "https://example.com/hook",
            "event_mesh_url": "https://mesh.example.com",
        },
    )
    return cls(config, "org-1", "int-1")


class _ForbiddenSession:
    """Any HTTP call through this raises, naming the URL that was attempted."""

    def _forbid(self, method, url, **kw):
        raise AssertionError(f"subscribe_to_events attempted {method} {url}")

    def get(self, url, **kw):
        self._forbid("GET", url, **kw)

    def post(self, url, **kw):
        self._forbid("POST", url, **kw)

    async def close(self):
        return None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class TestNoConnectorClaimsAnUnverifiedSubscription:
    @pytest.mark.parametrize("erp_type", ALL_TYPES, ids=lambda t: t.value)
    async def test_subscribe_to_events_does_not_return_true(self, erp_type):
        """Returning False is not a regression: there was never a working
        subscription to lose. Returning True was the bug."""
        connector = _connector(erp_type)
        with patch("aiohttp.ClientSession", return_value=_ForbiddenSession()):
            result = await connector.subscribe_to_events(["Invoice", "PurchaseOrder"])
        assert result is False, (
            f"{erp_type.value} reports a successful event subscription; if that is now "
            f"genuinely implemented and verified against a real system, set "
            f"EVENT_SUBSCRIPTION_MECHANISM = None and remove it from this guard"
        )

    @pytest.mark.parametrize("erp_type", ALL_TYPES, ids=lambda t: t.value)
    async def test_subscribe_to_events_makes_no_http_request(self, erp_type):
        """The strongest form of the assertion. A connector cannot report a bogus
        success from a response it never received."""
        connector = _connector(erp_type)
        with patch("aiohttp.ClientSession", return_value=_ForbiddenSession()):
            await connector.subscribe_to_events(["Invoice"])

    @pytest.mark.parametrize("erp_type", ALL_TYPES, ids=lambda t: t.value)
    def test_every_connector_declares_how_events_actually_work(self, erp_type):
        """A bare `return False` tells whoever hits this nothing. The declaration is
        the part that saves them an afternoon."""
        connector = _connector(erp_type)
        mechanism = connector.EVENT_SUBSCRIPTION_MECHANISM
        assert mechanism, f"{erp_type.value} declares no event-subscription mechanism"
        assert len(mechanism) > 60, (
            f"{erp_type.value}'s mechanism note is too terse to act on: {mechanism!r}"
        )


class TestNoInventedWebhookEndpointsRemainInSource:
    """Source-level, so it holds for the vendors whose systems we cannot reach."""

    #: URL fragments that were invented. Each was in a real implementation.
    INVENTED = [
        r'["\'`]?/webhooks',
        r'\{self\.api_url\}/?webhooks',
        r'/rest/webhooks/v1',
        r'/eventSubscriptions',
    ]

    @pytest.mark.parametrize("module,_cls", sorted(set(_REGISTRY.values())))
    def test_no_webhook_url_is_constructed(self, module, _cls):
        path = CONNECTOR_DIR / (module.rsplit(".", 1)[-1] + ".py")
        source = path.read_text()

        # Strip comments and docstrings: the declarations deliberately NAME these
        # paths in prose to explain why they are wrong, and that must stay legal.
        tree = ast.parse(source)
        docstrings = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                doc = ast.get_docstring(node, clean=False)
                if doc:
                    docstrings.add(doc)

        code_lines = []
        for line in source.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            code_lines.append(line)
        code = "\n".join(code_lines)
        for doc in docstrings:
            code = code.replace(doc, "")
        # The mechanism declarations are multi-line string literals, not docstrings.
        code = re.sub(r'EVENT_SUBSCRIPTION_MECHANISM\s*=\s*\(.*?\n    \)', '', code, flags=re.S)

        for pattern in self.INVENTED:
            assert not re.search(pattern, code), (
                f"{path.name} constructs an invented webhook endpoint matching "
                f"{pattern!r}. Every vendor's real mechanism is documented in that "
                f"connector's EVENT_SUBSCRIPTION_MECHANISM."
            )


class TestThreeStateHealthIsUniversal:
    """The systemic fix must actually be systemic.

    When `probe_health` was introduced, six of the seven connectors adopted it and
    Dynamics did not — it kept the two-state version mapping ANY exception to
    `unhealthy`. So the fix was claimed for all seven while one still reported a
    permissions gap as an outage. This test is what makes the claim checkable.
    """

    @pytest.mark.parametrize("erp_type", ALL_TYPES, ids=lambda t: t.value)
    def test_health_check_uses_the_shared_probe(self, erp_type):
        source = inspect.getsource(_resolve_class(erp_type).health_check)
        assert "probe_health" in source, (
            f"{erp_type.value}.health_check does not use probe_health, so it cannot "
            f"distinguish an unreachable system from an entity this tenant lacks"
        )

    #: Connectors whose probe entity is still a BUSINESS table, with the reason each
    #: is unresolved. Every one needs a vendor fact we cannot currently verify: which
    #: entity is present and readable in EVERY tenant of that product.
    #:
    #: This is a real remaining weakness, not a style nit. A least-privilege service
    #: account routinely cannot read invoices or orders, so these tenants report
    #: `degraded` forever. The three-state probe means it is no longer a false
    #: OUTAGE -- a missing or unreadable entity is `degraded`, not `unhealthy`, so
    #: nobody is paged -- but a permanently-degraded healthy integration is still
    #: wrong.
    #:
    #: Resolved for the three where the answer is known: Odoo (`res.users`, proven
    #: against a real Odoo), Dynamics (`systemusers`) and Intuit (`CompanyInfo`).
    #:
    #: The list must SHRINK, never grow. Guessing an entity name would just move the
    #: false report to a different tenant, which is why these are recorded rather
    #: than papered over.
    KNOWN_BUSINESS_TABLE_PROBES = {
        "sap": "S/4HANA entity sets are per-service; the right probe is the OData "
               "service document or $metadata, which needs a probe_health variant "
               "that is not a fetch_data call. Needs the sandbox to verify.",
        "oracle": "Oracle Fusion has no documented universally-readable resource; "
                  "the resource-catalog root is the likely answer. Needs a tenant.",
        "netsuite": "metadata-catalog is the likely auth-only probe. Blocked on "
                    "account approval.",
        "infor": "no known universally-present ION entity. Blocked on a tenant.",
        "epicor": "no known universally-present Kinetic BO. Blocked on an "
                  "environment.",
    }

    @pytest.mark.parametrize("erp_type", ALL_TYPES, ids=lambda t: t.value)
    def test_the_probe_entity_is_not_a_business_table(self, erp_type):
        """A least-privilege service account routinely cannot read invoices or
        orders. Probing one reports a permissions gap rather than real health -- the
        defect a real Odoo exposed with `sale.order`."""
        source = inspect.getsource(_resolve_class(erp_type).health_check)
        business = ["invoice", "purchaseorder", "purchase_order", "salesorder",
                    "sale.order", "accounts", "contacts", "workorder"]
        probe_args = re.findall(r'probe_health\(\s*([^,)]+)', source.lower())
        offending = [
            name for arg in probe_args for name in business if name in arg
        ]

        if erp_type.value in self.KNOWN_BUSINESS_TABLE_PROBES:
            # Documented and unresolved -- but it must STILL be a business-table
            # probe, otherwise it was fixed and belongs out of the allowlist.
            assert offending, (
                f"{erp_type.value} no longer probes a business table -- remove it "
                f"from KNOWN_BUSINESS_TABLE_PROBES so the list keeps shrinking"
            )
            return

        assert not offending, (
            f"{erp_type.value} probes the business table(s) {offending}; use an "
            f"entity present and readable in every tenant, or record it in "
            f"KNOWN_BUSINESS_TABLE_PROBES with the vendor fact that is missing"
        )

    def test_the_allowlist_does_not_grow(self):
        """The point of recording these is that the number goes down."""
        assert len(self.KNOWN_BUSINESS_TABLE_PROBES) <= 5, (
            "a new connector was added probing a business table; find the entity "
            "that every tenant of that product has instead"
        )

    def test_every_allowlist_entry_says_what_is_missing(self):
        """An allowlist without reasons becomes permanent."""
        for name, reason in self.KNOWN_BUSINESS_TABLE_PROBES.items():
            assert len(reason) > 40, f"{name}'s reason is too vague to act on"

    def test_the_allowlist_only_names_registered_connectors(self):
        """A stale entry would silently excuse nothing while looking like work."""
        registered = {t.value for t in _REGISTRY}
        stale = set(self.KNOWN_BUSINESS_TABLE_PROBES) - registered
        assert not stale, f"allowlist names connectors that do not exist: {stale}"

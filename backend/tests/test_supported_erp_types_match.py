"""The ERP types the UI offers are exactly the ones the factory can build (FS-486).

THE DEFECT CLASS, in both directions. `ERPIntegrations.tsx` builds its create-form dropdown
from `erpApi.supportedTypes()`, a hand-written array. That array is the entire surface
through which an ERP integration can be created, and it is compared against nothing.

    A type the UI offers that the factory cannot build
        `ERPConnectorFactory.create` raises, so the operator fills in a form, submits
        credentials, and gets a failure with nothing to do about it.

    A type the factory can build that the UI omits
        A shipped capability nobody can reach. This is the one that had happened:
        `intuit` — QuickBooks Online — is a 384-line connector with its own sandbox test
        suite, registered in the factory since it was written, and absent from the seven-item
        dropdown. The connector worked. There was no way to select it.

The second direction is the one no test in this repository would otherwise catch, because
everything else asks whether what the UI does works. Nothing asks what the UI cannot do.

`generic` is in the `ERPType` enum and correctly NOT offered: the factory has no entry for
it, so offering it would be the first failure. That is why this compares against the FACTORY
REGISTRY and not against the enum — the enum says what the codebase has words for, the
registry says what it can actually construct, and only one of those is a promise to a user.

AUTH TYPES TOO, for the same reason and a weaker one: that list is hard-coded in the page
rather than in the client, so it has one fewer place to drift and one more place to be
forgotten. It matches today; this keeps it matching.
"""

from __future__ import annotations

import pathlib
import re

from app.services.erp_connector_base import AuthType
from app.services.erp_connector_factory import _REGISTRY  # type: ignore[attr-defined]

REPO = pathlib.Path(__file__).resolve().parents[2]
ERP_CLIENT = REPO / "frontend" / "src" / "api" / "erp.ts"
ERP_PAGE = REPO / "frontend" / "src" / "pages" / "erp" / "ERPIntegrations.tsx"


def _frontend_supported_types() -> list[str]:
    source = ERP_CLIENT.read_text()
    body = re.search(r"supportedTypes\(\)[^{]*\{\s*return \[([^\]]*)\]", source)
    assert body, (
        "`supportedTypes()` could not be read out of erp.ts. The comparison below would "
        "then run over an empty list and pass, which is the failure mode this file is "
        "guarding something else against."
    )
    return re.findall(r"'([^']+)'", body.group(1))


def _frontend_auth_types() -> list[str]:
    source = ERP_PAGE.read_text()
    body = re.search(r"options=\{\[([^\]]*)\]\.map\(\(t\) => \(\{ value: t, label: t \}\)\)\}", source)
    assert body, "the auth-type option list could not be read out of ERPIntegrations.tsx"
    return re.findall(r"'([^']+)'", body.group(1))


def _registry_types() -> set[str]:
    return {erp_type.value for erp_type in _REGISTRY}


class TestTheReadersAreNotVacuous:
    """Every comparison below is between two lists. Two empty lists are equal."""

    def test_the_frontend_list_parses(self):
        types = _frontend_supported_types()
        assert len(types) >= 5, f"only {types} parsed out of supportedTypes(); the reader is broken"
        assert "sap" in types

    def test_the_registry_is_populated(self):
        registry = _registry_types()
        assert len(registry) >= 5, f"only {registry} in the connector registry; the import is wrong"

    def test_the_auth_list_parses(self):
        assert "oauth2" in _frontend_auth_types()


class TestTheUIOffersWhatTheFactoryCanBuild:
    def test_it_offers_nothing_the_factory_cannot_build(self):
        offered = set(_frontend_supported_types())
        buildable = _registry_types()
        unbuildable = sorted(offered - buildable)
        assert not unbuildable, (
            f"the ERP create form offers {unbuildable}, which ERPConnectorFactory.create "
            f"cannot construct — an operator picks one, fills in credentials, submits, and "
            f"the integration fails with nothing they can do about it"
        )

    def test_it_omits_nothing_the_factory_can_build(self):
        offered = set(_frontend_supported_types())
        buildable = _registry_types()
        unreachable = sorted(buildable - offered)
        assert not unreachable, (
            f"these connectors are registered in the factory and the ERP create form does "
            f"not offer them, so the capability ships and nobody can reach it: {unreachable}. "
            f"`intuit` sat here with a 384-line connector and its own sandbox suite."
        )

    def test_the_auth_types_offered_are_the_ones_declared(self):
        offered = set(_frontend_auth_types())
        declared = {auth.value for auth in AuthType}
        assert offered == declared, (
            f"the auth-type dropdown and `AuthType` disagree — offered but undeclared: "
            f"{sorted(offered - declared)}; declared but not offered: {sorted(declared - offered)}"
        )

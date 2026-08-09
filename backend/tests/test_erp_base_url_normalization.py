"""A trailing slash on `base_url` must not change a single request.

WHY THIS EXISTS. Five connectors build their endpoint by concatenating `base_url`
with a path — `f"{config.base_url}/api/v1"`. A configured value of
`https://host/` therefore produced `https://host//api/v1`. yarl preserves that
empty segment verbatim, so the server received `//api/v1` and answered 404.

That failure is nasty specifically because it is *plausible*: the URL looks right
in the log, and a 404 on `//A_PurchaseOrder` reads as a wrong entity name or an
unactivated OData service — not as a stray character in configuration. Meanwhile a
trailing slash is one of the most common ways a human writes a base URL, and every
one of these values is typed by a human into an integration form.

Found by pointing the SAP connector at a Prism mock generated from real SAP EDMX
(see docs/erp/validating-connectors-without-an-erp.md, Tier 2). The connector's
request arrived as `//A_PurchaseOrder` and matched no route. Normalization now
happens once, in `ERPConfig.__post_init__`, rather than being remembered at six
call sites.

These tests are hermetic — they assert on the URLs built, and construct nothing.
"""

from __future__ import annotations

import pytest

from app.services.erp_connector_base import AuthType, ERPConfig, ERPType

# (module path, class name, the attribute holding the built endpoint)
CONNECTORS = [
    ("app.services.erp_connectors.sap_connector", "SAPConnector", "odata_url"),
    ("app.services.erp_connectors.epicor_connector", "EpicorConnector", "api_url"),
    ("app.services.erp_connectors.infor_connector", "InforConnector", "api_url"),
    ("app.services.erp_connectors.odoo_connector", "OdooConnector", "api_url"),
    ("app.services.erp_connectors.oracle_connector", "OracleConnector", "api_url"),
]

# Every way a human plausibly writes the same host.
EQUIVALENT_BASE_URLS = [
    "https://erp.example.com",
    "https://erp.example.com/",
    "https://erp.example.com///",
    "  https://erp.example.com/  ",
]


def _build(module_path: str, class_name: str, base_url: str):
    import importlib

    cls = getattr(importlib.import_module(module_path), class_name)
    config = ERPConfig(
        erp_type=ERPType.SAP,
        auth_type=AuthType.API_KEY,
        base_url=base_url,
        auth_config={"api_key": "k", "username": "u", "client_id": "c", "client_secret": "s"},
        rate_limit={"requests_per_minute": 60},
        configuration={"db_name": "d", "company_id": "c", "tenant_id": "t"},
    )
    return cls(config, "org-1", "int-1")


class TestConfigNormalizesBaseUrl:
    @pytest.mark.parametrize("raw", EQUIVALENT_BASE_URLS)
    def test_trailing_slashes_and_whitespace_are_stripped(self, raw):
        config = ERPConfig(
            erp_type=ERPType.SAP,
            auth_type=AuthType.API_KEY,
            base_url=raw,
            auth_config={},
            rate_limit={},
        )
        assert config.base_url == "https://erp.example.com"

    def test_a_bare_host_is_left_alone(self):
        """Normalization must not eat a legitimate path prefix."""
        config = ERPConfig(
            erp_type=ERPType.SAP,
            auth_type=AuthType.API_KEY,
            base_url="https://erp.example.com/prefix",
            auth_config={},
            rate_limit={},
        )
        assert config.base_url == "https://erp.example.com/prefix"


class TestNoConnectorEmitsAnEmptyPathSegment:
    @pytest.mark.parametrize("module_path,class_name,attr", CONNECTORS)
    @pytest.mark.parametrize("raw", EQUIVALENT_BASE_URLS)
    def test_endpoint_never_contains_a_double_slash(self, module_path, class_name, attr, raw):
        url = getattr(_build(module_path, class_name, raw), attr)
        # Only the scheme's own "//" is allowed.
        assert "//" not in url.split("://", 1)[1], f"{class_name}.{attr} = {url!r}"

    @pytest.mark.parametrize("module_path,class_name,attr", CONNECTORS)
    def test_all_spellings_of_the_same_host_agree(self, module_path, class_name, attr):
        """The real assertion: configuration that differs only in trailing slashes
        must produce byte-identical endpoints. Anything else means one spelling
        works and another 404s."""
        built = {getattr(_build(module_path, class_name, raw), attr) for raw in EQUIVALENT_BASE_URLS}
        assert len(built) == 1, f"{class_name}.{attr} differs by trailing slash: {built}"


class TestSapEntityUrl:
    """SAP is the one that failed, because it interpolates *two* configured path
    segments before `fetch_data` appends a third."""

    @pytest.mark.parametrize(
        "service_path,service_name",
        [
            ("/sap/opu/odata/sap", "API_PURCHASEORDER_PROCESS_SRV"),
            ("/sap/opu/odata/sap/", "API_PURCHASEORDER_PROCESS_SRV"),
            ("sap/opu/odata/sap", "/API_PURCHASEORDER_PROCESS_SRV/"),
            ("", ""),
        ],
    )
    def test_entity_url_has_no_empty_segment(self, service_path, service_name):
        from app.services.erp_connectors.sap_connector import SAPConnector

        config = ERPConfig(
            erp_type=ERPType.SAP,
            auth_type=AuthType.OAUTH2,
            base_url="https://erp.example.com/",
            auth_config={"client_id": "c", "client_secret": "s"},
            rate_limit={"requests_per_minute": 60},
            configuration={"service_path": service_path, "service_name": service_name},
        )
        connector = SAPConnector(config, "org-1", "int-1")

        # Mirrors how fetch_data composes the request URL.
        entity_url = f"{connector.odata_url}/A_PurchaseOrder"
        assert "//" not in entity_url.split("://", 1)[1], entity_url
        assert entity_url.endswith("/A_PurchaseOrder")

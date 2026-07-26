"""Tests for the ERP connector factory (Phase A, task 1)."""

import pytest

from app.services.erp_connector_base import AuthType, ERPConnectorBase, ERPType
from app.services.erp_connector_factory import (
    ERPConnectorFactory,
    ERPConnectorUnavailable,
    UnsupportedERPType,
    build_erp_config,
    supported_types,
)


def _config(erp_type="netsuite"):
    return {
        "erp_type": erp_type,
        "auth_type": "api_key",
        "base_url": "https://erp.example.com",
        "auth_config": {"api_key": "k"},
        "rate_limit": {"requests_per_minute": 30, "burst_limit": 5},
        "timeout": 20,
        # Per-connector settings live at the TOP LEVEL here, because
        # build_erp_config passes the whole stored dict through as the settings bag
        # (`configuration=configuration`). Nesting them under a "configuration" key
        # would put them one level too deep and the connector would not see them.
        #
        # Harmless to the connectors that ignore these, and required by the ones
        # that refuse to be constructed without them -- Intuit rejects a missing
        # realm_id at construction, since every QuickBooks path is company-scoped
        # and it cannot be inferred later.
        "realm_id": "4620816365",
        "environment": "sandbox",
    }


class _FakeIntegration:
    id = "int-1"
    organization_id = "org-1"
    erp_type = "netsuite"
    configuration = _config()


def test_supported_types_matches_the_registry():
    """Derived from the registry, not hand-listed.

    This was the THIRD hardcoded connector list found in the test suite, all of
    which silently failed to cover a newly added connector. Adding Intuit changed
    nothing in any of them -- which is the same blind spot that let three
    unimportable connectors ship.
    """
    from app.services.erp_connector_factory import _REGISTRY

    assert set(supported_types()) == {t.value for t in _REGISTRY}
    assert "intuit" in supported_types()


def test_build_erp_config_maps_fields():
    cfg = build_erp_config(_config("sap"))
    assert cfg.erp_type == ERPType.SAP
    assert cfg.auth_type == AuthType.API_KEY
    assert cfg.base_url == "https://erp.example.com"
    assert cfg.timeout == 20
    assert cfg.rate_limit["requests_per_minute"] == 30


def test_create_from_orm_row_instantiates_connector():
    connector = ERPConnectorFactory.create(_FakeIntegration())
    assert isinstance(connector, ERPConnectorBase)
    assert connector.integration_id == "int-1"
    assert connector.organization_id == "org-1"


@pytest.mark.parametrize("erp_type", sorted(supported_types()))
def test_every_registered_type_builds(erp_type):
    cfg = build_erp_config(_config(erp_type))
    try:
        connector = ERPConnectorFactory.create_from_config(cfg, "org", "int")
    except ERPConnectorUnavailable:
        pytest.skip(f"{erp_type} vendor SDK not installed in this env")
    assert isinstance(connector, ERPConnectorBase)


def test_unsupported_type_raises():
    cfg = build_erp_config(_config("generic"))
    with pytest.raises(UnsupportedERPType):
        ERPConnectorFactory.create_from_config(cfg, "org", "int")

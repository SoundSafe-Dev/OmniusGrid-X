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
    }


class _FakeIntegration:
    id = "int-1"
    organization_id = "org-1"
    erp_type = "netsuite"
    configuration = _config()


def test_supported_types_covers_seven_connectors():
    assert set(supported_types()) == {
        "sap", "oracle", "dynamics", "netsuite", "odoo", "infor", "epicor"
    }


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


@pytest.mark.parametrize("erp_type", ["sap", "oracle", "dynamics", "netsuite", "odoo", "infor", "epicor"])
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

"""Unit checks for the revived ERP foundation."""

from uuid import uuid4

from app.db.models import IntegrationConfiguration
from app.services.erp_connector_base import AuthType, ERPType, GenericRESTERPConnector
from app.services.erp_connector_factory import build_erp_config, create_erp_connector
from app.services.erp_error_handler import ERPErrorHandler, ErrorCategory


def _integration(**configuration):
    return IntegrationConfiguration(
        id=uuid4(),
        organization_id=uuid4(),
        integration_type="erp",
        integration_name="Test ERP",
        configuration=configuration,
        authentication=configuration.get("auth_config"),
        erp_type=configuration.get("erp_type", "generic"),
    )


def test_build_erp_config_from_integration_configuration():
    integration = _integration(
        erp_type="sap",
        auth_type="api_key",
        base_url="https://erp.example.test",
        auth_config={"api_key": "secret", "header_name": "X-Test-Key"},
        rate_limit={"requests_per_minute": 10, "burst_limit": 2},
        timeout=12,
        health_check_path="/health",
    )

    config = build_erp_config(integration)

    assert config.erp_type == ERPType.SAP
    assert config.auth_type == AuthType.API_KEY
    assert config.base_url == "https://erp.example.test"
    assert config.auth_config["api_key"] == "secret"
    assert config.rate_limit["requests_per_minute"] == 10
    assert config.timeout == 12
    assert config.extra_config["health_check_path"] == "/health"


def test_connector_factory_returns_generic_connector_without_vendor_dependencies():
    integration = _integration(
        erp_type="dynamics",
        auth_type="none",
        base_url="https://erp.example.test",
    )

    connector = create_erp_connector(integration)

    assert isinstance(connector, GenericRESTERPConnector)
    assert connector.validate_config() is True


def test_generic_connector_validates_required_auth_fields():
    integration = _integration(
        erp_type="generic",
        auth_type="api_key",
        base_url="https://erp.example.test",
        auth_config={},
    )

    connector = create_erp_connector(integration)

    assert connector.validate_config() is False


def test_erp_error_handler_categorizes_common_failures():
    handler = ERPErrorHandler(str(uuid4()), str(uuid4()))

    assert handler.categorize_error(TimeoutError("request timeout")) == ErrorCategory.TRANSIENT
    assert handler.categorize_error(RuntimeError("401 unauthorized")) == ErrorCategory.PERMANENT
    assert handler.categorize_error(RuntimeError("503 service unavailable")) == ErrorCategory.TRANSIENT


def test_erp_router_is_mounted():
    from app.main import app

    paths = {route.path for route in app.routes}

    assert "/api/v1/erp/integrations" in paths
    assert "/api/v1/erp/integrations/{integration_id}/test" in paths
    assert "/api/v1/erp/integrations/{integration_id}/sync" in paths

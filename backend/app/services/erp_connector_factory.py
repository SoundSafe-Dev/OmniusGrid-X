"""Factory for ERP connector instances."""

from __future__ import annotations

from typing import Any

from app.db.models import IntegrationConfiguration
from app.services.erp_connector_base import (
    AuthType,
    ERPConfig,
    ERPConnectorBase,
    ERPType,
    GenericRESTERPConnector,
)


def _enum_value(enum_type, raw_value: str | None, default):
    if not raw_value:
        return default
    try:
        return enum_type(str(raw_value).lower())
    except ValueError:
        return default


def build_erp_config(integration: IntegrationConfiguration) -> ERPConfig:
    """Build an ERPConfig from a persisted IntegrationConfiguration row."""

    configuration: dict[str, Any] = dict(integration.configuration or {})
    auth_config = dict(
        configuration.get("auth_config")
        or integration.authentication
        or {}
    )

    erp_type = _enum_value(
        ERPType,
        getattr(integration, "erp_type", None) or configuration.get("erp_type"),
        ERPType.GENERIC,
    )
    auth_type = _enum_value(
        AuthType,
        configuration.get("auth_type"),
        AuthType.NONE,
    )

    return ERPConfig(
        erp_type=erp_type,
        auth_type=auth_type,
        base_url=str(configuration.get("base_url") or ""),
        auth_config=auth_config,
        rate_limit=dict(configuration.get("rate_limit") or {}),
        timeout=int(configuration.get("timeout") or 30),
        retry_config=dict(configuration.get("retry_config") or {}),
        circuit_breaker=dict(configuration.get("circuit_breaker") or {}),
        extra_config={
            key: value
            for key, value in configuration.items()
            if key
            not in {
                "erp_type",
                "auth_type",
                "base_url",
                "auth_config",
                "rate_limit",
                "timeout",
                "retry_config",
                "circuit_breaker",
            }
        },
    )


def create_erp_connector(
    integration: IntegrationConfiguration,
) -> ERPConnectorBase:
    """Create a connector for an ERP integration.

    Vendor-specific connectors can be registered here later. For the first
    revival slice, the generic REST connector gives the API a real health/fetch
    contract without adding new dependencies.
    """

    config = build_erp_config(integration)
    return GenericRESTERPConnector(
        config=config,
        organization_id=str(integration.organization_id),
        integration_id=str(integration.id),
    )

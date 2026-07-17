"""ERP connector factory (Phase A, task 1).

Wires the fully-built connector suite to the API layer: given an
``IntegrationConfiguration`` row (or a raw config dict), it resolves the right
concrete connector by ``erp_type`` and instantiates it with an ``ERPConfig``.
Until now the connectors existed but nothing constructed them — the ``test`` and
``sync`` endpoints were TODO stubs. This is the missing wiring layer.

Connector classes are imported lazily (only the one being created is imported) so
an optional dependency in one connector never breaks constructing another, and so
importing this module is cheap.
"""

import importlib
from typing import Any, Dict, List, Optional

import structlog

from app.services.erp_connector_base import AuthType, ERPConfig, ERPConnectorBase, ERPType

logger = structlog.get_logger()

# ERPType -> (module, class). Lazy so we only import the connector we build.
_REGISTRY: Dict[ERPType, tuple] = {
    ERPType.SAP: ("app.services.erp_connectors.sap_connector", "SAPConnector"),
    ERPType.ORACLE: ("app.services.erp_connectors.oracle_connector", "OracleConnector"),
    ERPType.DYNAMICS: ("app.services.erp_connectors.dynamics_connector", "DynamicsConnector"),
    ERPType.NETSUITE: ("app.services.erp_connectors.netsuite_connector", "NetSuiteConnector"),
    ERPType.ODOO: ("app.services.erp_connectors.odoo_connector", "OdooConnector"),
    ERPType.INFOR: ("app.services.erp_connectors.infor_connector", "InforConnector"),
    ERPType.EPICOR: ("app.services.erp_connectors.epicor_connector", "EpicorConnector"),
}


class UnsupportedERPType(Exception):
    """Raised when no connector is registered for an ERP type."""


class ERPConnectorUnavailable(Exception):
    """Raised when a connector's optional vendor dependency isn't installed."""


def supported_types() -> List[str]:
    """ERP type strings that have a concrete connector."""
    return [t.value for t in _REGISTRY]


def build_erp_config(configuration: Dict[str, Any]) -> ERPConfig:
    """Build an :class:`ERPConfig` from a stored integration ``configuration`` dict.

    Mirrors the keys written by ``create_integration`` (erp_type, auth_type,
    base_url, auth_config, rate_limit, timeout).
    """
    erp_type = ERPType(str(configuration["erp_type"]).lower())
    auth_type = AuthType(str(configuration["auth_type"]).lower())
    return ERPConfig(
        erp_type=erp_type,
        auth_type=auth_type,
        base_url=configuration.get("base_url", ""),
        auth_config=configuration.get("auth_config") or {},
        rate_limit=configuration.get("rate_limit") or {"requests_per_minute": 60, "burst_limit": 10},
        timeout=int(configuration.get("timeout") or 30),
        # Pass the whole stored dict as the connector-specific settings bag; each
        # connector reads the keys it needs (company_id, realm, account_id, ...).
        configuration=configuration,
    )


def _resolve_class(erp_type: ERPType):
    entry = _REGISTRY.get(erp_type)
    if entry is None:
        raise UnsupportedERPType(
            f"no connector for erp_type '{erp_type.value}'; "
            f"supported: {', '.join(supported_types())}"
        )
    module_path, class_name = entry
    try:
        module = importlib.import_module(module_path)
    except ImportError as exc:  # optional vendor SDK not installed
        raise ERPConnectorUnavailable(
            f"connector for '{erp_type.value}' needs an uninstalled dependency: {exc}"
        ) from exc
    return getattr(module, class_name)


class ERPConnectorFactory:
    """Constructs concrete ERP connectors from integration config."""

    @staticmethod
    def create_from_config(
        config: ERPConfig, organization_id: str, integration_id: str
    ) -> ERPConnectorBase:
        connector_cls = _resolve_class(config.erp_type)
        connector = connector_cls(config, organization_id, integration_id)
        logger.info(
            "erp_connector_created",
            erp_type=config.erp_type.value,
            integration_id=integration_id,
        )
        return connector

    @staticmethod
    def create(integration: Any) -> ERPConnectorBase:
        """Build a connector from an ``IntegrationConfiguration`` ORM row.

        Reads the stored ``configuration`` dict (falling back to the top-level
        ``erp_type`` column when the dict is absent).
        """
        configuration = dict(getattr(integration, "configuration", None) or {})
        if "erp_type" not in configuration and getattr(integration, "erp_type", None):
            configuration["erp_type"] = integration.erp_type
        if "auth_type" not in configuration:
            # Fall back to a sane default; most connectors re-auth internally.
            configuration["auth_type"] = configuration.get("auth_type", "api_key")
        config = build_erp_config(configuration)
        return ERPConnectorFactory.create_from_config(
            config, str(getattr(integration, "organization_id", "")), str(integration.id)
        )


# Module-level singleton for convenience.
erp_connector_factory = ERPConnectorFactory()

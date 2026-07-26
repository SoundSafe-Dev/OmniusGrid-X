"""
Microsoft Dynamics 365 Connector

Connector for Microsoft Dynamics 365 using Dataverse API and Graph API:
- Dataverse API for finance, supply chain, projects
- Microsoft Graph API for CRM data
- Azure AD authentication with MSAL
- Power Automate webhook integration
"""

from typing import Dict, Any, Optional, List
import structlog
import aiohttp

from app.services.erp_connector_base import (
    ERPConnectorBase,
    ERPConfig,
)

from app.services.erp_connectors.oauth2 import fetch_client_credentials_token

logger = structlog.get_logger()


class DynamicsConnector(ERPConnectorBase):
    """
    Microsoft Dynamics 365 connector.
    
    Connects to Dynamics 365 via Dataverse API and Graph API to fetch
    financial data, supply chain data, project data, and CRM data.
    """

    #: Dataverse has NO `webhooks` entity set -- the old implementation POSTed to
    #: `/api/data/v9.2/webhooks`, which is not part of the Web API. (Its docstring
    #: said "Power Automate", which is a different mechanism again.) Real webhook
    #: registration means creating a `serviceendpoint` record with contract=Webhook
    #: plus an `sdkmessageprocessingstep`, normally through the Plug-in Registration
    #: Tool. Not implemented here because it is unverified without a Dataverse org.
    EVENT_SUBSCRIPTION_MECHANISM = (
        "Dataverse has no 'webhooks' entity set. Register a serviceendpoint record "
        "(contract=Webhook) plus an sdkmessageprocessingstep -- normally via the "
        "Plug-in Registration Tool -- or use a Power Automate cloud flow."
    )

    #: `systemusers` exists in every Dataverse environment and is readable by
    #: anything that can authenticate, which is what a health probe needs. Probing a
    #: business table (`accounts`, `contacts`) reports a permissions gap as an
    #: outage.
    HEALTH_PROBE_ENTITY = "systemusers"
    
    def __init__(self, config: ERPConfig, organization_id: str, integration_id: str):
        super().__init__(config, organization_id, integration_id)
        
        # Dynamics-specific configuration
        self.environment = config.configuration.get("environment")
        self.api_type = config.configuration.get("api_type", "dataverse")  # dataverse or graph
        
        # Build base URLs
        if self.api_type == "dataverse":
            self.api_url = f"https://{self.environment}.api.crm.dynamics.com/api/data/v9.2/"
        else:
            self.api_url = "https://graph.microsoft.com/v1.0/"
        
        # MSAL application
        
        logger.info(
            "dynamics_connector_initialized",
            api_url=self.api_url,
            api_type=self.api_type,
            environment=self.environment
        )
    
    async def authenticate(self) -> str:
        """Acquire an Azure AD token via the client-credentials grant.

        REPLACES MSAL. `import msal` was never a declared dependency, so this
        module raised ImportError and the Dynamics connector could not be
        constructed — `erp_connector_factory` maps ERPType.DYNAMICS straight at it.

        MSAL is also synchronous: `acquire_token_for_client` blocks, so calling it
        from an async connector stalls the event loop for a full Azure AD round
        trip. Azure AD's v2.0 client-credentials endpoint is a plain form POST, so
        this needs no SDK.
        """
        auth_config = self.config.auth_config
        tenant_id = auth_config.get("tenant_id")
        if not tenant_id:
            raise ValueError("Dynamics requires `tenant_id` in auth_config")

        # `.default` is required for client-credentials: Azure AD grants the app's
        # configured application permissions rather than an ad-hoc scope list.
        if self.api_type == "dataverse":
            scope = f"https://{self.environment}.api.crm.dynamics.com/.default"
        else:
            scope = "https://graph.microsoft.com/.default"

        token, expires_in = await fetch_client_credentials_token(
            token_url=f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token",
            client_id=auth_config.get("client_id"),
            client_secret=auth_config.get("client_secret"),
            scope=scope,
            timeout_seconds=self.config.timeout,
        )

        self._set_token(token, expires_in)

        logger.info(
            "dynamics_authentication_success",
            api_type=self.api_type,
            expires_in=expires_in,
        )
        return token

    async def fetch_data(
        self,
        entity_type: str,
        filters: Optional[Dict[str, Any]] = None,
        limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """Fetch rows for a Dataverse entity set, following pagination to completion.

        `entity_type` is the ENTITY SET NAME (`accounts`), not the logical name
        (`account`). The two differ for 197 of 872 entity sets in a stock
        environment -- 22.6% -- so deriving one from the other by appending "s"
        produces a 404 that reads as a missing table. `activityparty` is
        `activityparties`, `agentmemory` is `agentmemories`, and a long tail take a
        `...set` suffix. Use EntityDefinitions to resolve names; see
        tools/erp-mocks/fetch-spec.sh.

        PAGINATION, AND WHY THIS IS NOT COSMETIC. Dataverse returns at most 5000
        rows per page and signals more with `@odata.nextLink`. This method used to
        issue one request and return `value`, silently discarding everything past
        the first page. Verified against a real environment: `GET /stringmaps`
        returns exactly 5000 rows and a nextLink -- so a caller asking for "all
        string maps" got a plausible, wrong answer with no error anywhere.

        `@odata.nextLink` is an ABSOLUTE URL with its own query string, including an
        opaque skip token. It must be requested verbatim; re-applying our own params
        to it changes the cursor and either repeats or skips rows.
        """
        token = await self.get_auth_token()

        url = f"{self.api_url}{entity_type}"
        params = {}
        if filters:
            params["$filter"] = self._build_filter_string(filters)
        if limit:
            params["$top"] = str(limit)

        rows: List[Dict[str, Any]] = []
        # `params` only on the FIRST request; nextLink already carries them.
        next_params = params

        while url:
            async def _fetch(url=url, next_params=next_params):
                headers = {
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                    "OData-MaxVersion": "4.0",
                    "OData-Version": "4.0"
                }
                async with aiohttp.ClientSession(
                    timeout=aiohttp.ClientTimeout(total=self.config.timeout)
                ) as session:
                    async with session.get(url, headers=headers, params=next_params) as response:
                        if response.status == 401:
                            # The token is dead whatever its stated expiry claimed.
                            self.invalidate_token()
                        if response.status != 200:
                            error_text = await response.text()
                            raise Exception(
                                f"Dynamics API error: {response.status} - {error_text}"
                            )
                        return await response.json()

            payload = await self.execute_with_retry(_fetch)

            page = payload.get("value")
            if page is None:
                # Refuse to report zero rows for a response we do not understand.
                raise Exception(
                    f"Dynamics response has no 'value' array for {entity_type}; "
                    f"keys were {sorted(payload)[:6]}"
                )
            rows.extend(page)

            if limit is not None and len(rows) >= limit:
                rows = rows[:limit]
                break

            url = payload.get("@odata.nextLink")
            next_params = None  # never re-apply params to a cursor URL

        logger.info(
            "dynamics_data_fetched",
            entity_type=entity_type,
            record_count=len(rows),
        )
        return rows

    async def health_check(self) -> Dict[str, Any]:
        """Health check via the shared three-state probe.

        THIS CONNECTOR WAS THE ONE MISSED. When probe_health was introduced, six of
        the seven connectors adopted it; Dynamics kept the old two-state version that
        mapped ANY exception to `unhealthy`. So the systemic fix was not in fact
        systemic, and a Dynamics tenant whose service principal cannot read the
        probed table had a working integration reported as an outage.

        The probe entity matters as much as the states. It used to be `accounts` (or
        `contacts` on the Graph path) -- business tables that a least-privilege
        application user is routinely not granted. `systemusers` is the Dataverse
        analogue of Odoo's `res.users`: present in every environment, and readable by
        anything that can authenticate at all. Same reasoning that replaced Odoo's
        `sale.order` probe after a real Odoo proved it wrong.
        """
        return await self.probe_health(
            self.HEALTH_PROBE_ENTITY,
            details={"environment": self.environment, "api_type": self.api_type},
        )

    def _build_filter_string(self, filters: Dict[str, Any]) -> str:
        """
        Build Dynamics OData filter string.
        
        Args:
            filters: Filter dictionary
            
        Returns:
            str: Filter string
        """
        filter_parts = []
        
        for field, value in filters.items():
            if isinstance(value, str):
                filter_parts.append(f"{field} eq '{value}'")
            elif isinstance(value, int) or isinstance(value, float):
                filter_parts.append(f"{field} eq {value}")
            elif isinstance(value, bool):
                filter_parts.append(f"{field} eq {str(value).lower()}")
            elif isinstance(value, list):
                # IN clause (not directly supported in OData, use or)
                or_parts = [f"{field} eq '{v}'" if isinstance(v, str) else f"{field} eq {v}" for v in value]
                filter_parts.append(f"({' or '.join(or_parts)})")
        
        return " and ".join(filter_parts)
    
    async def fetch_invoices(
        self,
        filters: Optional[Dict[str, Any]] = None,
        limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Fetch invoices from Dynamics.
        
        Args:
            filters: Optional filters
            limit: Optional limit
            
        Returns:
            List of invoices
        """
        return await self.fetch_data("invoices", filters, limit)
    
    async def fetch_payments(
        self,
        filters: Optional[Dict[str, Any]] = None,
        limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Fetch payments from Dynamics.
        
        Args:
            filters: Optional filters
            limit: Optional limit
            
        Returns:
            List of payments
        """
        return await self.fetch_data("payments", filters, limit)
    
    async def fetch_products(
        self,
        filters: Optional[Dict[str, Any]] = None,
        limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Fetch products from Dynamics.
        
        Args:
            filters: Optional filters
            limit: Optional limit
            
        Returns:
            List of products
        """
        return await self.fetch_data("products", filters, limit)
    
    async def fetch_orders(
        self,
        filters: Optional[Dict[str, Any]] = None,
        limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Fetch sales orders from Dynamics.
        
        Args:
            filters: Optional filters
            limit: Optional limit
            
        Returns:
            List of orders
        """
        return await self.fetch_data("salesorders", filters, limit)
    
    async def fetch_accounts(
        self,
        filters: Optional[Dict[str, Any]] = None,
        limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Fetch CRM accounts from Dynamics.
        
        Args:
            filters: Optional filters
            limit: Optional limit
            
        Returns:
            List of accounts
        """
        return await self.fetch_data("accounts", filters, limit)
    
    async def fetch_contacts(
        self,
        filters: Optional[Dict[str, Any]] = None,
        limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Fetch CRM contacts from Dynamics.
        
        Args:
            filters: Optional filters
            limit: Optional limit
            
        Returns:
            List of contacts
        """
        return await self.fetch_data("contacts", filters, limit)
    
    async def fetch_opportunities(
        self,
        filters: Optional[Dict[str, Any]] = None,
        limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Fetch CRM opportunities from Dynamics.
        
        Args:
            filters: Optional filters
            limit: Optional limit
            
        Returns:
            List of opportunities
        """
        return await self.fetch_data("opportunities", filters, limit)
    
    async def fetch_projects(
        self,
        filters: Optional[Dict[str, Any]] = None,
        limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Fetch projects from Dynamics.
        
        Args:
            filters: Optional filters
            limit: Optional limit
            
        Returns:
            List of projects
        """
        return await self.fetch_data("msdyn_project", filters, limit)
    
    async def fetch_tasks(
        self,
        filters: Optional[Dict[str, Any]] = None,
        limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Fetch project tasks from Dynamics.
        
        Args:
            filters: Optional filters
            limit: Optional limit
            
        Returns:
            List of tasks
        """
        return await self.fetch_data("msdyn_projecttask", filters, limit)

"""
Boomi Integration Service

Service for integrating with Dell Boomi AtomSphere:
- AtomSphere API integration
- Process deployment and management
- Connector configuration
"""

from typing import Dict, Any, Optional, List
from datetime import datetime, timezone
import structlog
import aiohttp
import json

from app.services.erp_connector_base import ERPConfig
from app.middleware.request_context import outbound_correlation_headers

logger = structlog.get_logger()


class BoomiIntegrationService:
    """
    Service for integrating with Dell Boomi AtomSphere.
    
    Provides integration with Boomi for process orchestration,
    data transformation, and connector management.
    """
    
    def __init__(self, config: ERPConfig, organization_id: str, integration_id: str):
        self.config = config
        self.organization_id = organization_id
        self.integration_id = integration_id
        
        # Boomi configuration
        self.account_id = config.configuration.get("account_id")
        self.environment = config.configuration.get("environment", "production")
        self.api_url = "https://api.boomi.com/api/rest/v1"
        
        logger.info(
            "boomi_integration_service_initialized",
            account_id=self.account_id,
            environment=self.environment
        )
    

    def _session(self) -> aiohttp.ClientSession:
        """One session factory, so timeouts are set in exactly one place (FS-1008).

        Every `aiohttp.ClientSession()` in this file used to be constructed bare, which
        means aiohttp's default of **no total timeout**: a middleware host that accepts a
        connection and then stops responding holds the coroutine open indefinitely. The
        connector layer next door (`erp_connectors/*`) has always passed an explicit
        `ClientTimeout` built from `config.timeout`; the middleware layer never did, and
        the difference was invisible because both look like a session.

        A hung ERP middleware call is worse than a failed one: it consumes a slot in the
        pool FS-839 sized, it never reaches the retry classifier, and the circuit breaker
        in `erp_connector_base` cannot count a failure that has not happened yet.
        """
        return aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=self.config.timeout),
            # FS-1014. Carries this request's correlation id outbound, so a failing ERP
            # call and the request that caused it can be joined. Empty outside a request
            # (a scheduled sync), because a freshly minted id would look like correlation
            # and correlate nothing.
            headers=outbound_correlation_headers(),
        )

    async def authenticate(self) -> str:
        """
        Authenticate with Boomi using API key.
        
        Returns:
            str: Access token
        """
        auth_config = self.config.auth_config
        
        # Boomi uses API key authentication
        # The API key is passed in the Authorization header
        api_key = auth_config.get("api_key")
        
        logger.info("boomi_authentication_success")
        
        return api_key
    
    async def deploy_process(
        self,
        process_id: str,
        environment_id: str,
        deployment_config: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Deploy a Boomi process to an environment.
        
        Args:
            process_id: Process ID
            environment_id: Environment ID
            deployment_config: Optional deployment configuration
            
        Returns:
            Dict with deployment status
        """
        api_key = await self.authenticate()
        
        # Default deployment configuration
        default_config = {
            "processId": process_id,
            "environmentId": environment_id,
            "notes": f"Deployed by OmniusGrid for organization {self.organization_id}"
        }
        
        if deployment_config:
            default_config.update(deployment_config)
        
        headers = {
            "Authorization": f"Basic {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
        
        async with self._session() as session:
            async with session.post(
                f"{self.api_url}/deploy/{self.account_id}",
                headers=headers,
                json=default_config
            ) as response:
                if response.status in [200, 201]:
                    data = await response.json()
                    logger.info(
                        "boomi_process_deployed",
                        process_id=process_id,
                        environment_id=environment_id
                    )
                    return {
                        "status": "success",
                        "deployment_id": data.get("deploymentId"),
                        "process_id": process_id,
                        "environment_id": environment_id
                    }
                else:
                    error_text = await response.text()
                    raise Exception(f"Boomi process deployment error: {response.status} - {error_text}")
    
    async def execute_process(
        self,
        process_id: str,
        process_data: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Execute a Boomi process.
        
        Args:
            process_id: Process ID
            process_data: Optional process data
            
        Returns:
            Dict with execution status
        """
        api_key = await self.authenticate()
        
        execution_config = {
            "processId": process_id,
            "organizationId": self.organization_id,
            "integrationId": self.integration_id
        }
        
        if process_data:
            execution_config["data"] = process_data
        
        headers = {
            "Authorization": f"Basic {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
        
        async with self._session() as session:
            async with session.post(
                f"{self.api_url}/executeProcess/{self.account_id}",
                headers=headers,
                json=execution_config
            ) as response:
                if response.status in [200, 201]:
                    data = await response.json()
                    logger.info(
                        "boomi_process_executed",
                        process_id=process_id
                    )
                    return {
                        "status": "success",
                        "execution_id": data.get("executionId"),
                        "process_id": process_id
                    }
                else:
                    error_text = await response.text()
                    raise Exception(f"Boomi process execution error: {response.status} - {error_text}")
    
    async def get_execution_status(
        self,
        execution_id: str
    ) -> Dict[str, Any]:
        """
        Get the status of a process execution.
        
        Args:
            execution_id: Execution ID
            
        Returns:
            Dict with execution status
        """
        api_key = await self.authenticate()
        
        headers = {
            "Authorization": f"Basic {api_key}",
            "Accept": "application/json"
        }
        
        async with self._session() as session:
            async with session.get(
                f"{self.api_url}/executionStatus/{self.account_id}/{execution_id}",
                headers=headers
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    return {
                        "status": "success",
                        "execution_id": execution_id,
                        "execution_status": data
                    }
                else:
                    error_text = await response.text()
                    raise Exception(f"Boomi execution status error: {response.status} - {error_text}")
    
    async def get_process_logs(
        self,
        execution_id: str
    ) -> List[Dict[str, Any]]:
        """
        Get logs for a process execution.
        
        Args:
            execution_id: Execution ID
            
        Returns:
            List of log entries
        """
        api_key = await self.authenticate()
        
        headers = {
            "Authorization": f"Basic {api_key}",
            "Accept": "application/json"
        }
        
        async with self._session() as session:
            async with session.get(
                f"{self.api_url}/executionLogs/{self.account_id}/{execution_id}",
                headers=headers
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    return data.get("logs", [])
                else:
                    error_text = await response.text()
                    raise Exception(f"Boomi process logs error: {response.status} - {error_text}")
    
    async def create_connector(
        self,
        connector_type: str,
        connector_config: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Create a Boomi connector.
        
        Args:
            connector_type: Type of connector (e.g., "SAP", "Oracle", "Dynamics")
            connector_config: Connector configuration
            
        Returns:
            Dict with connector creation status
        """
        api_key = await self.authenticate()
        
        connector_data = {
            "type": connector_type,
            "name": f"OmniusGrid_{connector_type}_{self.organization_id}",
            "configuration": connector_config,
            "organizationId": self.organization_id,
            "integrationId": self.integration_id
        }
        
        headers = {
            "Authorization": f"Basic {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
        
        async with self._session() as session:
            async with session.post(
                f"{self.api_url}/connector/{self.account_id}",
                headers=headers,
                json=connector_data
            ) as response:
                if response.status in [200, 201]:
                    data = await response.json()
                    logger.info(
                        "boomi_connector_created",
                        connector_type=connector_type
                    )
                    return {
                        "status": "success",
                        "connector_id": data.get("connectorId"),
                        "connector_type": connector_type
                    }
                else:
                    error_text = await response.text()
                    raise Exception(f"Boomi connector creation error: {response.status} - {error_text}")
    
    async def get_connector_status(
        self,
        connector_id: str
    ) -> Dict[str, Any]:
        """
        Get the status of a connector.
        
        Args:
            connector_id: Connector ID
            
        Returns:
            Dict with connector status
        """
        api_key = await self.authenticate()
        
        headers = {
            "Authorization": f"Basic {api_key}",
            "Accept": "application/json"
        }
        
        async with self._session() as session:
            async with session.get(
                f"{self.api_url}/connectorStatus/{self.account_id}/{connector_id}",
                headers=headers
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    return {
                        "status": "success",
                        "connector_id": connector_id,
                        "connector_status": data
                    }
                else:
                    error_text = await response.text()
                    raise Exception(f"Boomi connector status error: {response.status} - {error_text}")
    
    async def list_processes(
        self,
        filter_config: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """
        List Boomi processes.
        
        Args:
            filter_config: Optional filter configuration
            
        Returns:
            List of processes
        """
        api_key = await self.authenticate()
        
        headers = {
            "Authorization": f"Basic {api_key}",
            "Accept": "application/json"
        }
        
        params = {}
        if filter_config:
            params.update(filter_config)
        
        async with self._session() as session:
            async with session.get(
                f"{self.api_url}/process/{self.account_id}",
                headers=headers,
                params=params
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    return data.get("processes", [])
                else:
                    error_text = await response.text()
                    raise Exception(f"Boomi process list error: {response.status} - {error_text}")
    
    async def health_check(self) -> Dict[str, Any]:
        """
        Perform health check on Boomi connection.
        
        Returns:
            Dict with health status
        """
        try:
            api_key = await self.authenticate()
            
            # Try to list processes as a health check
            processes = await self.list_processes()
            
            return {
                "status": "healthy",
                "message": "Boomi connection successful",
                "account_id": self.account_id,
                "environment": self.environment,
                "process_count": len(processes),
                "checked_at": datetime.now(timezone.utc).isoformat()
            }
        except Exception as e:
            return {
                "status": "unhealthy",
                "message": str(e),
                "account_id": self.account_id,
                "environment": self.environment,
                "checked_at": datetime.now(timezone.utc).isoformat()
            }

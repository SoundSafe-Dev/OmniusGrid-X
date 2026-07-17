"""
Kafka Connect Integration Service

Service for integrating with Kafka Connect for ERP data streaming:
- Kafka Connect source/sink connectors
- Real-time data streaming from ERP systems
- Schema registry integration
"""

from typing import Dict, Any, Optional, List
from datetime import datetime, timezone
import structlog
import aiohttp
import json

from app.services.erp_connector_base import ERPConfig

logger = structlog.get_logger()


class KafkaConnectIntegrationService:
    """
    Service for integrating with Kafka Connect for ERP data streaming.
    
    Provides integration with Kafka Connect for real-time data
    streaming from ERP systems to Kafka topics.
    """
    
    def __init__(self, config: ERPConfig, organization_id: str, integration_id: str):
        self.config = config
        self.organization_id = organization_id
        self.integration_id = integration_id
        
        # Kafka Connect configuration
        self.connect_url = config.configuration.get("connect_url")
        self.bootstrap_servers = config.configuration.get("bootstrap_servers")
        self.schema_registry_url = config.configuration.get("schema_registry_url")
        
        logger.info(
            "kafka_connect_integration_service_initialized",
            connect_url=self.connect_url,
            bootstrap_servers=self.bootstrap_servers
        )
    
    async def create_source_connector(
        self,
        connector_name: str,
        erp_config: Dict[str, Any],
        topic_prefix: str
    ) -> Dict[str, Any]:
        """
        Create a Kafka Connect source connector for ERP data.
        
        Args:
            connector_name: Name of the connector
            erp_config: ERP-specific configuration
            topic_prefix: Prefix for Kafka topics
            
        Returns:
            Dict with connector creation status
        """
        connector_config = {
            "name": connector_name,
            "config": {
                "connector.class": erp_config.get("connector_class"),
                "tasks.max": erp_config.get("tasks_max", 1),
                "bootstrap.servers": self.bootstrap_servers,
                "topic.prefix": topic_prefix,
                "erp.type": erp_config.get("erp_type"),
                "erp.base.url": erp_config.get("base_url"),
                "erp.auth.type": erp_config.get("auth_type"),
                "erp.auth.config": json.dumps(erp_config.get("auth_config", {})),
                "poll.interval.ms": erp_config.get("poll_interval_ms", 60000),
                "batch.size": erp_config.get("batch_size", 100),
                "organization.id": self.organization_id,
                "integration.id": self.integration_id
            }
        }
        
        # Add schema registry config if available
        if self.schema_registry_url:
            connector_config["config"]["value.converter"] = "io.confluent.connect.avro.AvroConverter"
            connector_config["config"]["value.converter.schema.registry.url"] = self.schema_registry_url
        
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{self.connect_url}/connectors",
                headers=headers,
                json=connector_config
            ) as response:
                if response.status in [200, 201]:
                    logger.info(
                        "kafka_connect_source_connector_created",
                        connector_name=connector_name
                    )
                    return {
                        "status": "success",
                        "connector_name": connector_name,
                        "topic_prefix": topic_prefix
                    }
                else:
                    error_text = await response.text()
                    raise Exception(f"Kafka Connect connector creation error: {response.status} - {error_text}")
    
    async def create_sink_connector(
        self,
        connector_name: str,
        topic: str,
        sink_config: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Create a Kafka Connect sink connector for ERP data.
        
        Args:
            connector_name: Name of the connector
            topic: Source Kafka topic
            sink_config: Sink-specific configuration
            
        Returns:
            Dict with connector creation status
        """
        connector_config = {
            "name": connector_name,
            "config": {
                "connector.class": sink_config.get("connector_class"),
                "tasks.max": sink_config.get("tasks_max", 1),
                "topics": topic,
                "bootstrap.servers": self.bootstrap_servers,
                "erp.type": sink_config.get("erp_type"),
                "erp.base.url": sink_config.get("base_url"),
                "erp.auth.type": sink_config.get("auth_type"),
                "erp.auth.config": json.dumps(sink_config.get("auth_config", {})),
                "organization.id": self.organization_id,
                "integration.id": self.integration_id
            }
        }
        
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{self.connect_url}/connectors",
                headers=headers,
                json=connector_config
            ) as response:
                if response.status in [200, 201]:
                    logger.info(
                        "kafka_connect_sink_connector_created",
                        connector_name=connector_name
                    )
                    return {
                        "status": "success",
                        "connector_name": connector_name,
                        "topic": topic
                    }
                else:
                    error_text = await response.text()
                    raise Exception(f"Kafka Connect connector creation error: {response.status} - {error_text}")
    
    async def get_connector_status(
        self,
        connector_name: str
    ) -> Dict[str, Any]:
        """
        Get the status of a Kafka Connect connector.
        
        Args:
            connector_name: Name of the connector
            
        Returns:
            Dict with connector status
        """
        headers = {
            "Accept": "application/json"
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{self.connect_url}/connectors/{connector_name}/status",
                headers=headers
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    return {
                        "status": "success",
                        "connector_name": connector_name,
                        "connector_status": data
                    }
                else:
                    error_text = await response.text()
                    raise Exception(f"Kafka Connect status error: {response.status} - {error_text}")
    
    async def delete_connector(
        self,
        connector_name: str
    ) -> Dict[str, Any]:
        """
        Delete a Kafka Connect connector.
        
        Args:
            connector_name: Name of the connector
            
        Returns:
            Dict with deletion status
        """
        headers = {
            "Accept": "application/json"
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.delete(
                f"{self.connect_url}/connectors/{connector_name}",
                headers=headers
            ) as response:
                if response.status == 204:
                    logger.info(
                        "kafka_connect_connector_deleted",
                        connector_name=connector_name
                    )
                    return {
                        "status": "success",
                        "connector_name": connector_name
                    }
                else:
                    error_text = await response.text()
                    raise Exception(f"Kafka Connect deletion error: {response.status} - {error_text}")
    
    async def list_connectors(self) -> List[str]:
        """
        List all Kafka Connect connectors.
        
        Returns:
            List of connector names
        """
        headers = {
            "Accept": "application/json"
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{self.connect_url}/connectors",
                headers=headers
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    return data
                else:
                    error_text = await response.text()
                    raise Exception(f"Kafka Connect list error: {response.status} - {error_text}")
    
    async def get_connector_config(
        self,
        connector_name: str
    ) -> Dict[str, Any]:
        """
        Get the configuration of a Kafka Connect connector.
        
        Args:
            connector_name: Name of the connector
            
        Returns:
            Dict with connector configuration
        """
        headers = {
            "Accept": "application/json"
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{self.connect_url}/connectors/{connector_name}/config",
                headers=headers
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    return data
                else:
                    error_text = await response.text()
                    raise Exception(f"Kafka Connect config error: {response.status} - {error_text}")
    
    async def restart_connector(
        self,
        connector_name: str
    ) -> Dict[str, Any]:
        """
        Restart a Kafka Connect connector.
        
        Args:
            connector_name: Name of the connector
            
        Returns:
            Dict with restart status
        """
        headers = {
            "Accept": "application/json"
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{self.connect_url}/connectors/{connector_name}/restart",
                headers=headers
            ) as response:
                if response.status in [200, 204]:
                    logger.info(
                        "kafka_connect_connector_restarted",
                        connector_name=connector_name
                    )
                    return {
                        "status": "success",
                        "connector_name": connector_name
                    }
                else:
                    error_text = await response.text()
                    raise Exception(f"Kafka Connect restart error: {response.status} - {error_text}")
    
    async def pause_connector(
        self,
        connector_name: str
    ) -> Dict[str, Any]:
        """
        Pause a Kafka Connect connector.
        
        Args:
            connector_name: Name of the connector
            
        Returns:
            Dict with pause status
        """
        headers = {
            "Accept": "application/json"
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.put(
                f"{self.connect_url}/connectors/{connector_name}/pause",
                headers=headers
            ) as response:
                if response.status in [200, 202]:
                    logger.info(
                        "kafka_connect_connector_paused",
                        connector_name=connector_name
                    )
                    return {
                        "status": "success",
                        "connector_name": connector_name
                    }
                else:
                    error_text = await response.text()
                    raise Exception(f"Kafka Connect pause error: {response.status} - {error_text}")
    
    async def resume_connector(
        self,
        connector_name: str
    ) -> Dict[str, Any]:
        """
        Resume a paused Kafka Connect connector.
        
        Args:
            connector_name: Name of the connector
            
        Returns:
            Dict with resume status
        """
        headers = {
            "Accept": "application/json"
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.put(
                f"{self.connect_url}/connectors/{connector_name}/resume",
                headers=headers
            ) as response:
                if response.status in [200, 202]:
                    logger.info(
                        "kafka_connect_connector_resumed",
                        connector_name=connector_name
                    )
                    return {
                        "status": "success",
                        "connector_name": connector_name
                    }
                else:
                    error_text = await response.text()
                    raise Exception(f"Kafka Connect resume error: {response.status} - {error_text}")
    
    async def health_check(self) -> Dict[str, Any]:
        """
        Perform health check on Kafka Connect.
        
        Returns:
            Dict with health status
        """
        try:
            connectors = await self.list_connectors()
            
            return {
                "status": "healthy",
                "message": "Kafka Connect connection successful",
                "connector_count": len(connectors),
                "connectors": connectors,
                "checked_at": datetime.now(timezone.utc).isoformat()
            }
        except Exception as e:
            return {
                "status": "unhealthy",
                "message": str(e),
                "checked_at": datetime.now(timezone.utc).isoformat()
            }

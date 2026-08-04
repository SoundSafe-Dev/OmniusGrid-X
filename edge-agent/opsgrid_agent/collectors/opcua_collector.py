"""
OPC-UA Collector for industrial PLCs and equipment
Supports subscriptions, browsing, and reading/writing node values
"""

import asyncio
from datetime import datetime, timezone
from typing import Dict, Any, Optional, Callable, List, Set
import structlog
from asyncua import Client, Node, ua
from asyncua.common.subscription import DataChangeNotif

from opsgrid_agent.packml import PackMLStateMapper, create_mapper_for_asset_type

from ..resilience import CircuitBreaker, ExponentialBackoff

logger = structlog.get_logger()


class OPCUACollector:
    """
    OPC-UA collector for industrial equipment.
    Supports subscription-based data collection for real-time updates.

    Reconnect behaviour:
        Connection attempts are guarded by an equal-jittered
        :class:`ExponentialBackoff` (1s -> 60s base curve) and a
        :class:`CircuitBreaker` (opens after 5 consecutive failures, 30s
        initial cooldown up to 5 min). This avoids the previous fixed
        5-second retry that could overload a recovering PLC after a network
        blip.
    """
    
    def __init__(
        self,
        server_url: str,
        asset_id: str,
        asset_type: str = "industrial_plc",
        username: Optional[str] = None,
        password: Optional[str] = None,
        certificate_path: Optional[str] = None,
        private_key_path: Optional[str] = None,
        nodes_to_monitor: Optional[List[str]] = None,
        packml_mappings: Optional[Dict[str, str]] = None,
        on_message_callback: Optional[Callable] = None,
        backoff: Optional[ExponentialBackoff] = None,
        breaker: Optional[CircuitBreaker] = None,
    ):
        self.server_url = server_url
        self.asset_id = asset_id
        self.asset_type = asset_type
        self.username = username
        self.password = password
        self.certificate_path = certificate_path
        self.private_key_path = private_key_path
        self.nodes_to_monitor = nodes_to_monitor or []
        self.on_message_callback = on_message_callback
        
        # PackML state mapper
        self.packml_mapper = create_mapper_for_asset_type(asset_type, packml_mappings)
        
        # OPC-UA client
        self.client: Optional[Client] = None
        self.subscription = None
        self._handler = None
        
        # State tracking
        self._running = False
        self._connected = False
        self._last_values: Dict[str, Any] = {}

        # Node cache
        self._nodes: Dict[str, Node] = {}

        # Reconnect resilience. Defaults intentionally match the MQTT
        # collector so a single agent's collectors behave consistently
        # under broker / PLC outages.
        #
        # TODO(tune): These defaults are a first-pass conservative guess.
        # Adjust the values below once we have production telemetry on real
        # PLC outage patterns, or pass a tuned ExponentialBackoff /
        # CircuitBreaker instance from the coordinator for per-deployment
        # overrides without touching this file.
        self._backoff = backoff or ExponentialBackoff(
            initial=1.0, cap=60.0, multiplier=2.0
        )
        self._breaker = breaker or CircuitBreaker(
            failure_threshold=5,
            initial_cooldown=30.0,
            cooldown_cap=300.0,
            cooldown_multiplier=2.0,
            name=f"opcua:{asset_id}",
        )
    
    async def start(self):
        """Start the OPC-UA collector"""
        logger.info(
            "opcua_collector_starting",
            asset_id=self.asset_id,
            server_url=self.server_url
        )
        
        self._running = True
        
        while self._running:
            # Pause if the breaker has tripped after repeated failures.
            if not self._breaker.allow():
                wait = self._breaker.time_until_retry()
                logger.info(
                    "opcua_circuit_open",
                    asset_id=self.asset_id,
                    wait_seconds=wait,
                )
                await asyncio.sleep(wait)
                continue

            try:
                await self._connect()
                await self._setup_subscription()

                # Connection (and subscription) succeeded — reset backoff so
                # the *next* failure starts from the bottom of the curve.
                self._backoff.reset()
                self._breaker.record_success()

                # Keep connection alive
                while self._running and self._connected:
                    await asyncio.sleep(1)
                    
                    # Check connection health
                    try:
                        await self.client.check_connection()
                    except Exception:
                        logger.warning("opcua_connection_lost")
                        self._connected = False
                        break
                
            except Exception as e:
                logger.error("opcua_collector_error", error=str(e))
                self._breaker.record_failure()
                delay = self._backoff.next_delay()
                logger.info(
                    "opcua_reconnect_backoff",
                    asset_id=self.asset_id,
                    base_delay_seconds=self._backoff.last_base_delay,
                    delay_seconds=delay,
                )
                await asyncio.sleep(delay)
        
        await self._disconnect()
        logger.info("opcua_collector_stopped", asset_id=self.asset_id)
    
    async def _connect(self):
        """Establish OPC-UA connection"""
        # Create client
        self.client = Client(self.server_url)
        
        # Configure security
        if self.certificate_path and self.private_key_path:
            await self.client.set_security(
                ua.SecurityPolicyType.Basic256Sha256_SignAndEncrypt,
                certificate=self.certificate_path,
                private_key=self.private_key_path
            )
        elif self.certificate_path:
            await self.client.set_security(
                ua.SecurityPolicyType.Basic256Sha256_Sign,
                certificate=self.certificate_path,
                private_key=self.private_key_path
            )
        
        # Set session timeout
        self.client.session_timeout = 60000  # 60 seconds
        
        # Connect
        await self.client.connect()
        
        # Authenticate if credentials provided
        if self.username and self.password:
            self.client.set_user(self.username)
            self.client.set_password(self.password)
        
        # Load server namespaces
        await self.client.load_data_type_definitions()
        await self.client.load_enums()
        
        self._connected = True
        
        logger.info(
            "opcua_connected",
            asset_id=self.asset_id,
            server_url=self.server_url
        )
    
    async def _setup_subscription(self):
        """Setup data change subscription for monitored nodes"""
        if not self.nodes_to_monitor:
            logger.warning("opcua_no_nodes_configured", asset_id=self.asset_id)
            return
        
        # Create subscription handler
        self._handler = OPCUASubscriptionHandler(
            asset_id=self.asset_id,
            on_data_change=self._on_data_change,
            packml_mapper=self.packml_mapper,
            on_message_callback=self.on_message_callback
        )
        
        # Create subscription
        self.subscription = await self.client.create_subscription(
            period=1000,  # 1 second publish interval
            handler=self._handler
        )
        
        # Resolve and subscribe to nodes
        for node_id in self.nodes_to_monitor:
            try:
                node = self.client.get_node(node_id)
                
                # Verify node exists
                node_class = await node.read_node_class()
                
                if node_class == ua.NodeClass.Variable:
                    await self.subscription.subscribe_data_change(node)
                    self._nodes[node_id] = node
                    
                    # Read initial value
                    value = await node.read_value()
                    self._last_values[node_id] = value
                    
                    logger.info(
                        "opcua_node_subscribed",
                        asset_id=self.asset_id,
                        node_id=node_id
                    )
                else:
                    logger.warning(
                        "opcua_node_not_variable",
                        asset_id=self.asset_id,
                        node_id=node_id,
                        node_class=node_class
                    )
                    
            except Exception as e:
                logger.error(
                    "opcua_node_subscribe_failed",
                    asset_id=self.asset_id,
                    node_id=node_id,
                    error=str(e)
                )
    
    def _on_data_change(self, node_id: str, datavalue: ua.DataValue):
        """Handle data change notification"""
        try:
            value = datavalue.Value.Value if datavalue.Value else None
            timestamp = datetime.now(timezone.utc)
            
            # Get source timestamp if available
            if datavalue.SourceTimestamp:
                timestamp = datavalue.SourceTimestamp
            
            # Update cached value
            old_value = self._last_values.get(node_id)
            self._last_values[node_id] = value
            
            # Map to PackML state if this is a state node
            packml_state = None
            if 'state' in node_id.lower():
                state_str = str(value) if value else 'IDLE'
                packml_state = self.packml_mapper.map_state(state_str)
            
            # Create message
            message = {
                'timestamp_edge': timestamp.isoformat(),
                'asset_id': self.asset_id,
                'payload': {
                    'node_id': node_id,
                    'value': value,
                    'old_value': old_value,
                    'data_type': type(value).__name__ if value else None,
                    'status_code': datavalue.StatusCode.name if datavalue.StatusCode else None,
                    'packml_state': packml_state.value if packml_state else None,
                },
                'packml_state': packml_state.value if packml_state else None,
                'collector_type': 'opcua'
            }
            
            if self.on_message_callback:
                asyncio.create_task(self.on_message_callback(message))
            
            logger.debug(
                "opcua_data_change",
                asset_id=self.asset_id,
                node_id=node_id,
                value=value
            )
            
        except Exception as e:
            logger.error(
                "opcua_data_change_error",
                asset_id=self.asset_id,
                node_id=node_id,
                error=str(e)
            )
    
    async def _disconnect(self):
        """Disconnect from OPC-UA server"""
        try:
            if self.subscription:
                await self.subscription.delete()
            
            if self.client:
                await self.client.disconnect()
            
            self._connected = False
            logger.info("opcua_disconnected", asset_id=self.asset_id)
            
        except Exception as e:
            logger.error("opcua_disconnect_error", error=str(e))
    
    async def read_node(self, node_id: str) -> Optional[Any]:
        """Read value from a specific node"""
        if not self._connected:
            return None
        
        try:
            node = self.client.get_node(node_id)
            value = await node.read_value()
            return value
        except Exception as e:
            logger.error(
                "opcua_read_failed",
                asset_id=self.asset_id,
                node_id=node_id,
                error=str(e)
            )
            return None
    
    async def write_node(self, node_id: str, value: Any) -> bool:
        """Write value to a specific node (for commands)"""
        if not self._connected:
            return False
        
        try:
            node = self.client.get_node(node_id)
            await node.write_value(value)
            
            logger.info(
                "opcua_write_success",
                asset_id=self.asset_id,
                node_id=node_id,
                value=value
            )
            return True
            
        except Exception as e:
            logger.error(
                "opcua_write_failed",
                asset_id=self.asset_id,
                node_id=node_id,
                error=str(e)
            )
            return False
    
    async def browse_nodes(self, node_id: str = None) -> List[Dict]:
        """Browse available nodes from server"""
        if not self._connected:
            return []
        
        try:
            if node_id:
                node = self.client.get_node(node_id)
            else:
                node = self.client.get_objects_node()
            
            children = await node.get_children()
            
            nodes_info = []
            for child in children:
                try:
                    browse_name = await child.read_browse_name()
                    node_class = await child.read_node_class()
                    
                    nodes_info.append({
                        'node_id': child.nodeid.to_string(),
                        'browse_name': browse_name.Name,
                        'node_class': node_class.name,
                    })
                except:
                    pass
            
            return nodes_info
            
        except Exception as e:
            logger.error("opcua_browse_error", error=str(e))
            return []
    
    async def stop(self):
        """Stop the OPC-UA collector"""
        logger.info("opcua_collector_stopping", asset_id=self.asset_id)
        self._running = False


class OPCUASubscriptionHandler:
    """Handler for OPC-UA subscription data changes"""
    
    def __init__(
        self,
        asset_id: str,
        on_data_change: Callable,
        packml_mapper: PackMLStateMapper,
        on_message_callback: Optional[Callable]
    ):
        self.asset_id = asset_id
        self.on_data_change = on_data_change
        self.packml_mapper = packml_mapper
        self.on_message_callback = on_message_callback
    
    def datachange_notification(self, node: Node, val, data: DataChangeNotif):
        """Called when subscribed data changes"""
        node_id = node.nodeid.to_string()
        self.on_data_change(node_id, data)
    
    def event_notification(self, event):
        """Called when events are received"""
        logger.debug("opcua_event", asset_id=self.asset_id, event=event)
    
    def status_change_notification(self, status):
        """Called when status changes"""
        logger.debug("opcua_status_change", asset_id=self.asset_id, status=status)

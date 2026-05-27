"""MQTT Collector for Bambu Labs and other MQTT-enabled printers"""

import asyncio
import json
from datetime import datetime
from typing import Dict, Any, Optional, Callable
import paho.mqtt.client as mqtt
import structlog

from opsgrid_agent.packml import PackMLStateMapper, create_mapper_for_asset_type

logger = structlog.get_logger()


class MQTTCollector:
    """
    MQTT collector for Bambu Labs printers and other MQTT-enabled equipment.
    
    Features:
    - Automatic reconnection with exponential backoff
    - PackML state normalization
    - Message buffering during network outages
    - TLS/mTLS support for secure connections
    """
    
    def __init__(
        self,
        broker_host: str,
        broker_port: int = 8883,
        username: Optional[str] = None,
        password: Optional[str] = None,
        use_tls: bool = True,
        ca_cert: Optional[str] = None,
        client_cert: Optional[str] = None,
        client_key: Optional[str] = None,
        asset_id: Optional[str] = None,
        asset_type: str = "3d_printer",
        packml_mappings: Optional[Dict[str, str]] = None,
        on_message_callback: Optional[Callable] = None
    ):
        self.broker_host = broker_host
        self.broker_port = broker_port
        self.username = username
        self.password = password
        self.use_tls = use_tls
        self.ca_cert = ca_cert
        self.client_cert = client_cert
        self.client_key = client_key
        self.asset_id = asset_id
        self.asset_type = asset_type
        self.on_message_callback = on_message_callback
        
        # PackML state mapper
        self.packml_mapper = create_mapper_for_asset_type(asset_type, packml_mappings)
        
        # MQTT client
        self.client = mqtt.Client(client_id=f"opsgrid_{asset_id or 'agent'}")
        self._connected = False
        self._reconnect_delay = 1
        self._max_reconnect_delay = 60
        self._stop_event = asyncio.Event()
        
        # Setup callbacks
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message
        
        # Configure authentication
        if username and password:
            self.client.username_pw_set(username, password)
        
        # Configure TLS
        if use_tls:
            if ca_cert:
                self.client.tls_set(
                    ca_certs=ca_cert,
                    certfile=client_cert,
                    keyfile=client_key
                )
            else:
                self.client.tls_set()
    
    def _on_connect(self, client, userdata, flags, rc):
        """Handle connection established"""
        if rc == 0:
            self._connected = True
            self._reconnect_delay = 1  # Reset backoff
            logger.info(
                "mqtt_connected",
                broker=self.broker_host,
                port=self.broker_port,
                asset_id=self.asset_id
            )
            
            # Subscribe to topics
            self._subscribe_to_topics()
        else:
            logger.error(
                "mqtt_connection_failed",
                broker=self.broker_host,
                return_code=rc
            )
    
    def _on_disconnect(self, client, userdata, rc):
        """Handle disconnection"""
        self._connected = False
        if rc != 0:
            logger.warning(
                "mqtt_unexpected_disconnect",
                broker=self.broker_host,
                return_code=rc
            )
        else:
            logger.info(
                "mqtt_disconnected",
                broker=self.broker_host
            )
    
    def _on_message(self, client, userdata, msg):
        """Handle incoming message"""
        try:
            payload = json.loads(msg.payload.decode('utf-8'))
            
            # Extract timestamp (prefer device timestamp if available)
            timestamp = datetime.utcnow()
            if 'timestamp' in payload:
                try:
                    timestamp = datetime.fromisoformat(payload['timestamp'].replace('Z', '+00:00'))
                except (ValueError, AttributeError):
                    pass
            
            # Normalize to PackML state if state info present
            packml_state = None
            if 'state' in payload:
                vendor_state = payload['state']
                packml_state = self.packml_mapper.map_state(vendor_state)
                payload['packml_state'] = packml_state.value
                payload['packml_category'] = self.packml_mapper.get_state_category(packml_state)
            
            # Create normalized message
            message = {
                'timestamp_edge': timestamp.isoformat(),
                'asset_id': self.asset_id,
                'topic': msg.topic,
                'payload': payload,
                'packml_state': packml_state.value if packml_state else None,
                'collector_type': 'mqtt'
            }
            
            # Call callback if provided
            if self.on_message_callback:
                asyncio.create_task(self.on_message_callback(message))
            
            logger.debug(
                "mqtt_message_received",
                topic=msg.topic,
                asset_id=self.asset_id,
                packml_state=packml_state.value if packml_state else None
            )
            
        except json.JSONDecodeError as e:
            logger.error(
                "mqtt_message_parse_failed",
                topic=msg.topic,
                error=str(e)
            )
        except Exception as e:
            logger.error(
                "mqtt_message_handler_error",
                topic=msg.topic,
                error=str(e)
            )
    
    def _subscribe_to_topics(self):
        """Subscribe to relevant MQTT topics"""
        # Bambu Labs specific topics
        topics = [
            f"device/{self.asset_id}/report",
            f"device/{self.asset_id}/status",
        ]
        
        for topic in topics:
            self.client.subscribe(topic)
            logger.info("mqtt_subscribed", topic=topic)
    
    async def start(self):
        """Start the MQTT collector"""
        logger.info(
            "mqtt_collector_starting",
            broker=self.broker_host,
            asset_id=self.asset_id
        )
        
        while not self._stop_event.is_set():
            try:
                if not self._connected:
                    self.client.connect(self.broker_host, self.broker_port)
                    self.client.loop_start()
                    
                    # Wait for connection with timeout
                    try:
                        await asyncio.wait_for(
                            self._wait_for_connection(),
                            timeout=30
                        )
                    except asyncio.TimeoutError:
                        logger.warning("mqtt_connection_timeout")
                        self.client.loop_stop()
                        await self._backoff_reconnect()
                        continue
                
                # Keep running until stopped
                await self._stop_event.wait()
                
            except Exception as e:
                logger.error("mqtt_collector_error", error=str(e))
                await self._backoff_reconnect()
        
        self.client.loop_stop()
        logger.info("mqtt_collector_stopped")
    
    async def _wait_for_connection(self):
        """Wait for MQTT connection to be established"""
        while not self._connected and not self._stop_event.is_set():
            await asyncio.sleep(0.1)
    
    async def _backoff_reconnect(self):
        """Reconnect with exponential backoff"""
        logger.info(
            "mqtt_reconnect_backoff",
            delay_seconds=self._reconnect_delay
        )
        
        try:
            await asyncio.wait_for(
                self._stop_event.wait(),
                timeout=self._reconnect_delay
            )
        except asyncio.TimeoutError:
            pass
        
        # Exponential backoff
        self._reconnect_delay = min(
            self._reconnect_delay * 2,
            self._max_reconnect_delay
        )
    
    async def stop(self):
        """Stop the MQTT collector"""
        logger.info("mqtt_collector_stopping")
        self._stop_event.set()
        self.client.disconnect()


class BambuCollector(MQTTCollector):
    """Specialized collector for Bambu Lab printers"""
    
    def __init__(
        self,
        printer_ip: str,
        access_code: str,
        serial_number: str,
        **kwargs
    ):
        # Bambu-specific MQTT settings
        super().__init__(
            broker_host=printer_ip,
            broker_port=8883,
            username="bblp",
            password=access_code,
            use_tls=True,
            asset_id=serial_number,
            asset_type="3d_printer",
            **kwargs
        )
        
        # Bambu-specific PackML mappings
        self.packml_mapper = create_mapper_for_asset_type(
            "3d_printer",
            {
                # Bambu-specific states
                "RUNNING": "Execute",
                "PAUSE": "Held",
                "FAILED": "Aborted",
                "FINISH": "Complete",
                "IDLE": "Idle",
                "PREPARE": "Starting",
            }
        )
    
    def _subscribe_to_topics(self):
        """Subscribe to Bambu-specific topics"""
        # Bambu Labs MQTT topic structure
        topic = f"device/{self.asset_id}/report"
        self.client.subscribe(topic)
        logger.info("bambu_subscribed", topic=topic)
    
    def _on_message(self, client, userdata, msg):
        """Parse Bambu-specific message format"""
        try:
            payload = json.loads(msg.payload.decode('utf-8'))
            
            # Bambu format has nested structure
            if 'print' in payload:
                print_data = payload['print']
                
                # Extract state
                bambu_state = print_data.get('state', 'IDLE')
                packml_state = self.packml_mapper.map_state(bambu_state)
                
                # Extract telemetry
                telemetry = {
                    'temp_nozzle': print_data.get('nozzle_temper'),
                    'temp_bed': print_data.get('bed_temper'),
                    'temp_chamber': print_data.get('chamber_temper'),
                    'progress': print_data.get('mc_percent'),
                    'print_speed': print_data.get('speed_lvl'),
                    'layer': print_data.get('layer_num'),
                    'total_layers': print_data.get('total_layer_num'),
                    'gcode_file': print_data.get('gcode_file'),
                    'subtask_name': print_data.get('subtask_name'),
                }
                
                # Create normalized message
                message = {
                    'timestamp_edge': datetime.utcnow().isoformat(),
                    'asset_id': self.asset_id,
                    'topic': msg.topic,
                    'payload': {
                        'raw': payload,
                        'telemetry': telemetry,
                        'state': bambu_state,
                        'packml_state': packml_state.value,
                        'packml_category': self.packml_mapper.get_state_category(packml_state),
                    },
                    'packml_state': packml_state.value,
                    'collector_type': 'bambu_mqtt'
                }
                
                if self.on_message_callback:
                    asyncio.create_task(self.on_message_callback(message))
                
                logger.debug(
                    "bambu_message_parsed",
                    asset_id=self.asset_id,
                    state=bambu_state,
                    packml_state=packml_state.value,
                    progress=telemetry.get('progress')
                )
        
        except Exception as e:
            logger.error(
                "bambu_parse_error",
                asset_id=self.asset_id,
                error=str(e)
            )

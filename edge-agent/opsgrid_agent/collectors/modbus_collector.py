"""
Modbus Collector for industrial equipment
Supports Modbus TCP and RTU for PLCs, VFDs, sensors
"""

import asyncio
from datetime import datetime, timezone
from typing import Dict, Any, Optional, Callable, List, Union
import structlog
from pymodbus.client import ModbusTcpClient, ModbusSerialClient
from pymodbus.exceptions import ModbusException

from opsgrid_agent.packml import PackMLStateMapper, create_mapper_for_asset_type

from ..resilience import CircuitBreaker, ExponentialBackoff, ReconnectPolicy

logger = structlog.get_logger()


class ModbusCollector:
    """
    Modbus collector for industrial equipment.
    Supports both Modbus TCP and Modbus RTU.

    Reconnect behaviour:
        Connection attempts are guarded by an :class:`ExponentialBackoff`
        (1s -> 60s) and a :class:`CircuitBreaker` (opens after 5
        consecutive failures, 30s initial cooldown up to 5 min). This
        replaces the previous fixed 5-second retry, which could overload
        a recovering controller after a brief network blip.
    """
    
    def __init__(
        self,
        connection_type: str,  # 'tcp' or 'rtu'
        host: Optional[str] = None,  # For TCP
        port: int = 502,  # For TCP (default Modbus port)
        serial_port: Optional[str] = None,  # For RTU
        baudrate: int = 9600,  # For RTU
        slave_id: int = 1,
        asset_id: str = None,
        asset_type: str = "industrial_plc",
        registers_to_poll: Optional[List[Dict]] = None,
        poll_interval: float = 5.0,  # seconds
        packml_mappings: Optional[Dict[str, str]] = None,
        on_message_callback: Optional[Callable] = None,
        backoff: Optional[ExponentialBackoff] = None,
        breaker: Optional[CircuitBreaker] = None,
        reconnect: Optional[Dict[str, Any]] = None,
    ):
        self.connection_type = connection_type
        self.host = host
        self.port = port
        self.serial_port = serial_port
        self.baudrate = baudrate
        self.slave_id = slave_id
        self.asset_id = asset_id
        self.asset_type = asset_type
        self.registers_to_poll = registers_to_poll or []
        self.poll_interval = poll_interval
        self.on_message_callback = on_message_callback
        
        # PackML state mapper
        self.packml_mapper = create_mapper_for_asset_type(asset_type, packml_mappings)
        
        # Modbus client
        self.client: Union[ModbusTcpClient, ModbusSerialClient, None] = None
        
        # State tracking
        self._running = False
        self._connected = False
        self._last_values: Dict[str, Any] = {}

        # Reconnect resilience. The defaults are shared by every collector — that is now
        # a property of `ReconnectPolicy` rather than three files agreeing by hand.
        #
        # The TODO that lived here moved with the values it was about. Leaving "adjust the
        # values below" above a line that no longer has any values is how a comment starts
        # sending people to the wrong file.
        # ONE POLICY, still injectable (FS-473). These three collectors each wrote the
        # same four constants inline, and FS-472 copied them into five more — sixteen
        # occurrences across eight files of a number this file's own TODO called a
        # first-pass guess. The guess has not changed; it now lives in one place where the
        # person holding production telemetry can change it once.
        #
        # An explicit `backoff=` / `breaker=` still wins, so the coordinator can hand a
        # tuned instrument to one collector without disturbing the rest.
        _policy_backoff, _policy_breaker = ReconnectPolicy.from_settings(reconnect).instruments(
            f"modbus:{asset_id}"
        )
        self._backoff = backoff or _policy_backoff
        self._breaker = breaker or _policy_breaker

    async def start(self):
        """Start the Modbus collector"""
        logger.info(
            "modbus_collector_starting",
            asset_id=self.asset_id,
            connection_type=self.connection_type,
            host=self.host,
            port=self.port
        )
        
        self._running = True
        
        while self._running:
            # Pause if the breaker has tripped after repeated failures.
            if not self._breaker.allow():
                wait = self._breaker.time_until_retry()
                logger.info(
                    "modbus_circuit_open",
                    asset_id=self.asset_id,
                    wait_seconds=wait,
                )
                await asyncio.sleep(wait)
                continue

            try:
                # Connect if not connected
                if not self._connected:
                    await self._connect()
                    # Fresh connection succeeded — reset backoff so the
                    # next failure starts from the bottom of the curve.
                    self._backoff.reset()
                    self._breaker.record_success()

                # Poll registers
                await self._poll_registers()

                # Wait for next poll
                await asyncio.sleep(self.poll_interval)
                
            except Exception as e:
                logger.error("modbus_collector_error", error=str(e))
                self._connected = False
                self._breaker.record_failure()
                delay = self._backoff.next_delay()
                logger.info(
                    "modbus_reconnect_backoff",
                    asset_id=self.asset_id,
                    delay_seconds=delay,
                )
                await asyncio.sleep(delay)
        
        await self._disconnect()
        logger.info("modbus_collector_stopped", asset_id=self.asset_id)
    
    async def _connect(self):
        """Establish Modbus connection"""
        try:
            if self.connection_type == 'tcp':
                self.client = ModbusTcpClient(
                    host=self.host,
                    port=self.port,
                    timeout=10
                )
            elif self.connection_type == 'rtu':
                self.client = ModbusSerialClient(
                    port=self.serial_port,
                    baudrate=self.baudrate,
                    bytesize=8,
                    parity='N',
                    stopbits=1,
                    timeout=10
                )
            else:
                raise ValueError(f"Unsupported connection type: {self.connection_type}")
            
            # Connect
            self.client.connect()
            
            # Test connection with a simple read
            result = self.client.read_holding_registers(
                address=0,
                count=1,
                slave=self.slave_id
            )
            
            if result.isError():
                raise ModbusException("Connection test failed")
            
            self._connected = True
            
            logger.info(
                "modbus_connected",
                asset_id=self.asset_id,
                connection_type=self.connection_type,
                slave_id=self.slave_id
            )
            
        except Exception as e:
            logger.error(
                "modbus_connection_failed",
                asset_id=self.asset_id,
                error=str(e)
            )
            raise
    
    async def _poll_registers(self):
        """Poll configured registers"""
        telemetry = {}
        
        for register_config in self.registers_to_poll:
            try:
                name = register_config['name']
                address = register_config['address']
                register_type = register_config.get('type', 'holding')  # holding, input, coil
                count = register_config.get('count', 1)
                data_type = register_config.get('data_type', 'uint16')  # uint16, int16, uint32, float32
                scale = register_config.get('scale', 1.0)
                
                # Read based on register type
                if register_type == 'holding':
                    result = self.client.read_holding_registers(
                        address=address,
                        count=count,
                        slave=self.slave_id
                    )
                elif register_type == 'input':
                    result = self.client.read_input_registers(
                        address=address,
                        count=count,
                        slave=self.slave_id
                    )
                elif register_type == 'coil':
                    result = self.client.read_coils(
                        address=address,
                        count=count,
                        slave=self.slave_id
                    )
                else:
                    logger.warning("unknown_register_type", type=register_type)
                    continue
                
                if result.isError():
                    logger.warning(
                        "modbus_read_error",
                        asset_id=self.asset_id,
                        name=name,
                        address=address,
                        error=result
                    )
                    continue
                
                # Parse value based on data type
                raw_value = result.registers if hasattr(result, 'registers') else result.bits
                value = self._parse_value(raw_value, data_type, scale)
                
                telemetry[name] = value
                
            except Exception as e:
                logger.error(
                    "modbus_poll_error",
                    asset_id=self.asset_id,
                    register=register_config.get('name'),
                    error=str(e)
                )
        
        # Check for changes and send update
        if telemetry and self._has_changed(telemetry):
            await self._send_telemetry(telemetry)
            self._last_values = telemetry.copy()
    
    def _parse_value(self, raw_value, data_type: str, scale: float) -> float:
        """Parse raw Modbus value to numeric"""
        if isinstance(raw_value, list):
            if len(raw_value) == 1:
                raw = raw_value[0]
            elif len(raw_value) == 2:
                # 32-bit value from two registers
                raw = (raw_value[0] << 16) | raw_value[1]
            else:
                raw = raw_value[0]
        else:
            raw = raw_value
        
        # Apply data type conversion
        if data_type == 'uint16':
            value = raw
        elif data_type == 'int16':
            value = raw if raw < 32768 else raw - 65536
        elif data_type == 'uint32':
            value = raw
        elif data_type == 'int32':
            value = raw if raw < 2147483648 else raw - 4294967296
        elif data_type == 'float32':
            # IEEE 754 float from two registers
            import struct
            packed = struct.pack('>I', raw)
            value = struct.unpack('>f', packed)[0]
        else:
            value = raw
        
        # Apply scaling
        return value * scale
    
    def _has_changed(self, telemetry: Dict) -> bool:
        """Check if telemetry has changed significantly"""
        if not self._last_values:
            return True
        
        for key, value in telemetry.items():
            old_value = self._last_values.get(key)
            if old_value is None:
                return True
            
            # Numeric comparison with tolerance
            if isinstance(value, (int, float)) and isinstance(old_value, (int, float)):
                # 1% change threshold
                if abs(value - old_value) > (abs(old_value) * 0.01 + 0.001):
                    return True
            elif value != old_value:
                return True
        
        return False
    
    async def _send_telemetry(self, telemetry: Dict):
        """Send telemetry message"""
        # Detect state if state register present
        packml_state = None
        state = telemetry.get('state') or telemetry.get('status')
        if state is not None:
            state_str = str(state)
            packml_state = self.packml_mapper.map_state(state_str)
        
        message = {
            'timestamp_edge': datetime.now(timezone.utc).isoformat(),
            'asset_id': self.asset_id,
            'payload': {
                'telemetry': telemetry,
                'state': state,
                'packml_state': packml_state.value if packml_state else None,
                'packml_category': self.packml_mapper.get_state_category(packml_state) if packml_state else None,
            },
            'packml_state': packml_state.value if packml_state else None,
            'collector_type': 'modbus'
        }
        
        if self.on_message_callback:
            await self.on_message_callback(message)
        
        logger.debug(
            "modbus_telemetry",
            asset_id=self.asset_id,
            telemetry_count=len(telemetry)
        )
    
    async def _disconnect(self):
        """Disconnect from Modbus server"""
        try:
            if self.client:
                self.client.close()
            self._connected = False
            logger.info("modbus_disconnected", asset_id=self.asset_id)
        except Exception as e:
            logger.error("modbus_disconnect_error", error=str(e))
    
    async def write_register(self, address: int, value: int, register_type: str = 'holding') -> bool:
        """Write to a Modbus register (for commands)"""
        if not self._connected:
            return False
        
        try:
            if register_type == 'holding':
                result = self.client.write_register(
                    address=address,
                    value=value,
                    slave=self.slave_id
                )
            elif register_type == 'coil':
                result = self.client.write_coil(
                    address=address,
                    value=bool(value),
                    slave=self.slave_id
                )
            else:
                return False
            
            if not result.isError():
                logger.info(
                    "modbus_write_success",
                    asset_id=self.asset_id,
                    address=address,
                    value=value
                )
                return True
            else:
                logger.error(
                    "modbus_write_error",
                    asset_id=self.asset_id,
                    address=address,
                    error=result
                )
                return False
                
        except Exception as e:
            logger.error(
                "modbus_write_exception",
                asset_id=self.asset_id,
                address=address,
                error=str(e)
            )
            return False
    
    async def stop(self):
        """Stop the Modbus collector"""
        logger.info("modbus_collector_stopping", asset_id=self.asset_id)
        self._running = False

"""
Screen Scraper Collector for QIDI and SOVOL printers
Uses OpenCV and Tesseract OCR to extract data from printer display screens
"""

import asyncio
import io
from datetime import datetime
from typing import Dict, Any, Optional, Callable, Tuple
import structlog
import numpy as np
import cv2
import pytesseract
from PIL import Image
import httpx

from opsgrid_agent.packml import PackMLStateMapper, create_mapper_for_asset_type

logger = structlog.get_logger()


class ScreenScraperCollector:
    """
    Generic screen scraper using OCR for printers with video streams.
    Captures screenshots and extracts telemetry data.
    """
    
    def __init__(
        self,
        stream_url: str,
        asset_id: str,
        asset_type: str = "3d_printer",
        packml_mappings: Optional[Dict[str, str]] = None,
        ocr_config: Optional[Dict] = None,
        capture_interval: float = 5.0,  # seconds
        on_message_callback: Optional[Callable] = None
    ):
        self.stream_url = stream_url
        self.asset_id = asset_id
        self.asset_type = asset_type
        self.capture_interval = capture_interval
        self.on_message_callback = on_message_callback
        
        # PackML state mapper
        self.packml_mapper = create_mapper_for_asset_type(asset_type, packml_mappings)
        
        # OCR configuration
        self.ocr_config = ocr_config or {}
        
        # State tracking
        self._running = False
        self._last_state = None
        self._last_telemetry = {}
        self._consecutive_failures = 0
        self._max_failures = 10
        
        # Tesseract config
        self.tesseract_config = '--oem 3 --psm 6 -c tessedit_char_whitelist=0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz.:;/_-%°'
    
    async def start(self):
        """Start the screen scraper"""
        logger.info(
            "screen_scraper_starting",
            asset_id=self.asset_id,
            stream_url=self.stream_url,
            interval=self.capture_interval
        )
        
        self._running = True
        
        while self._running:
            try:
                # Capture and process frame
                await self._capture_and_process()
                
                # Reset failure counter on success
                self._consecutive_failures = 0
                
                # Wait for next capture
                await asyncio.sleep(self.capture_interval)
                
            except Exception as e:
                self._consecutive_failures += 1
                logger.error(
                    "screen_scraper_error",
                    asset_id=self.asset_id,
                    error=str(e),
                    failures=self._consecutive_failures
                )
                
                if self._consecutive_failures >= self._max_failures:
                    logger.error(
                        "screen_scraper_max_failures",
                        asset_id=self.asset_id,
                        stopping=True
                    )
                    self._running = False
                    break
                
                await asyncio.sleep(5)  # Short delay before retry
        
        logger.info("screen_scraper_stopped", asset_id=self.asset_id)
    
    async def _capture_and_process(self):
        """Capture frame from stream and process with OCR"""
        # Download frame from MJPEG stream
        frame = await self._download_frame()
        
        if frame is None:
            raise Exception("Failed to capture frame")
        
        # Extract text regions using OCR
        raw_text = await self._extract_text(frame)
        
        # Parse telemetry from extracted text
        telemetry = self._parse_telemetry(raw_text, frame)
        
        # Detect state from visual indicators
        state = self._detect_state(frame, telemetry)
        
        # PackML mapping
        packml_state = self.packml_mapper.map_state(state)
        
        # Check for significant changes
        if self._has_changed(telemetry, state):
            # Create message
            message = {
                'timestamp_edge': datetime.utcnow().isoformat(),
                'asset_id': self.asset_id,
                'payload': {
                    'raw_text': raw_text,
                    'telemetry': telemetry,
                    'state': state,
                    'packml_state': packml_state.value,
                    'packml_category': self.packml_mapper.get_state_category(packml_state),
                    'ocr_confidence': telemetry.get('_ocr_confidence', 0.5),
                },
                'packml_state': packml_state.value,
                'collector_type': 'screen_scraper'
            }
            
            if self.on_message_callback:
                await self.on_message_callback(message)
            
            logger.debug(
                "screen_scraper_data",
                asset_id=self.asset_id,
                state=state,
                temp_nozzle=telemetry.get('temp_nozzle')
            )
            
            # Update last known state
            self._last_state = state
            self._last_telemetry = telemetry
    
    async def _download_frame(self) -> Optional[np.ndarray]:
        """Download a frame from the MJPEG stream"""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    self.stream_url,
                    headers={'Accept': 'multipart/x-mixed-replace'}
                )
                
                if response.status_code != 200:
                    logger.warning(
                        "stream_download_failed",
                        url=self.stream_url,
                        status=response.status_code
                    )
                    return None
                
                # Parse MJPEG stream
                content = response.content
                
                # Find JPEG frame boundaries
                jpeg_start = content.find(b'\xff\xd8')
                jpeg_end = content.find(b'\xff\xd9', jpeg_start)
                
                if jpeg_start == -1 or jpeg_end == -1:
                    logger.warning("no_jpeg_frame_found")
                    return None
                
                # Extract JPEG data
                jpeg_data = content[jpeg_start:jpeg_end+2]
                
                # Convert to OpenCV format
                image = Image.open(io.BytesIO(jpeg_data))
                frame = cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)
                
                return frame
                
        except Exception as e:
            logger.error("frame_download_error", error=str(e))
            return None
    
    async def _extract_text(self, frame: np.ndarray) -> str:
        """Extract text from frame using OCR"""
        # Preprocess image for better OCR
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        
        # Denoise
        denoised = cv2.fastNlMeansDenoising(gray)
        
        # Threshold
        _, binary = cv2.threshold(denoised, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        
        # Run OCR
        text = pytesseract.image_to_string(binary, config=self.tesseract_config)
        
        return text
    
    def _parse_telemetry(self, raw_text: str, frame: np.ndarray) -> Dict[str, Any]:
        """Parse structured telemetry from OCR text"""
        telemetry = {}
        text_lower = raw_text.lower()
        
        # Extract temperature values
        # Patterns: "Nozzle: 210°C", "210°C", "Temp: 210"
        import re
        
        # Nozzle temperature
        nozzle_patterns = [
            r'nozzle[:\s]*(\d+)[°\s]*c?',
            r'extruder[:\s]*(\d+)[°\s]*c?',
            r'n[:\s]*(\d+)[°\s]*c?',
        ]
        for pattern in nozzle_patterns:
            match = re.search(pattern, text_lower)
            if match:
                telemetry['temp_nozzle'] = float(match.group(1))
                break
        
        # Bed temperature
        bed_patterns = [
            r'bed[:\s]*(\d+)[°\s]*c?',
            r'platform[:\s]*(\d+)[°\s]*c?',
            r'b[:\s]*(\d+)[°\s]*c?',
        ]
        for pattern in bed_patterns:
            match = re.search(pattern, text_lower)
            if match:
                telemetry['temp_bed'] = float(match.group(1))
                break
        
        # Progress percentage
        progress_patterns = [
            r'(\d+)%\s*complete',
            r'progress[:\s]*(\d+)%?',
            r'(\d+)%',
        ]
        for pattern in progress_patterns:
            match = re.search(pattern, text_lower)
            if match:
                telemetry['progress'] = float(match.group(1))
                break
        
        # Print speed
        speed_patterns = [
            r'speed[:\s]*(\d+)%?',
            r'(\d+)%\s*speed',
        ]
        for pattern in speed_patterns:
            match = re.search(pattern, text_lower)
            if match:
                telemetry['print_speed'] = float(match.group(1))
                break
        
        # Layer information
        layer_patterns = [
            r'layer[:\s]*(\d+)\s*/\s*(\d+)',
            r'layer[:\s]*(\d+)\s*of\s*(\d+)',
            r'z[:\s]*(\d+\.?\d*)',
        ]
        for pattern in layer_patterns:
            match = re.search(pattern, text_lower)
            if match:
                if len(match.groups()) >= 2:
                    telemetry['layer'] = int(match.group(1))
                    telemetry['total_layers'] = int(match.group(2))
                else:
                    telemetry['layer'] = int(float(match.group(1)))
                break
        
        # Time remaining
        time_patterns = [
            r'(\d+)h[:\s]*(\d+)m',
            r'(\d+):(\d+):(\d+)',
            r'(\d+)\s*hours?\s*(\d*)\s*min',
        ]
        for pattern in time_patterns:
            match = re.search(pattern, text_lower)
            if match:
                groups = match.groups()
                if len(groups) >= 2 and groups[1]:
                    hours = int(groups[0])
                    minutes = int(groups[1]) if groups[1] else 0
                    telemetry['time_remaining_min'] = hours * 60 + minutes
                break
        
        # OCR confidence estimate
        telemetry['_ocr_confidence'] = self._estimate_ocr_confidence(raw_text)
        
        return telemetry
    
    def _estimate_ocr_confidence(self, raw_text: str) -> float:
        """Estimate OCR confidence based on text quality"""
        if not raw_text:
            return 0.0
        
        # Simple heuristic: presence of numbers and structure
        has_numbers = any(c.isdigit() for c in raw_text)
        has_temp_marker = '°' in raw_text or 'c' in raw_text.lower()
        has_structure = ':' in raw_text or '/' in raw_text
        
        score = 0.3  # Base score
        if has_numbers:
            score += 0.3
        if has_temp_marker:
            score += 0.2
        if has_structure:
            score += 0.2
        
        return min(score, 1.0)
    
    def _detect_state(self, frame: np.ndarray, telemetry: Dict) -> str:
        """Detect printer state from visual indicators"""
        # Check temperature trends
        nozzle_temp = telemetry.get('temp_nozzle', 0)
        bed_temp = telemetry.get('temp_bed', 0)
        progress = telemetry.get('progress', 0)
        
        # Heuristic state detection
        if progress is not None and progress > 0 and progress < 100:
            if nozzle_temp > 180:  # Likely printing
                return "RUNNING"
            else:
                return "PREPARE"
        
        if progress == 100:
            return "FINISH"
        
        if nozzle_temp > 50 or bed_temp > 30:
            return "IDLE"  # Heated but not printing
        
        # Check for error indicators (red colors, error text)
        # This would need more sophisticated image analysis
        
        return "IDLE"
    
    def _has_changed(self, telemetry: Dict, state: str) -> bool:
        """Check if telemetry has changed significantly"""
        if state != self._last_state:
            return True
        
        # Check for significant temperature changes (>2°C)
        for key in ['temp_nozzle', 'temp_bed']:
            new_val = telemetry.get(key)
            old_val = self._last_telemetry.get(key)
            if new_val is not None and old_val is not None:
                if abs(new_val - old_val) > 2:
                    return True
            elif new_val != old_val:
                return True
        
        # Check for progress changes
        new_progress = telemetry.get('progress')
        old_progress = self._last_telemetry.get('progress')
        if new_progress != old_progress:
            return True
        
        return False
    
    async def stop(self):
        """Stop the screen scraper"""
        logger.info("screen_scraper_stopping", asset_id=self.asset_id)
        self._running = False


class QidiCollector(ScreenScraperCollector):
    """Specialized collector for QIDI printers"""
    
    def __init__(
        self,
        printer_ip: str,
        serial_number: str,
        **kwargs
    ):
        # QIDI uses standard MJPEG stream on port 8080
        stream_url = f"http://{printer_ip}:8080/?action=stream"
        
        super().__init__(
            stream_url=stream_url,
            asset_id=serial_number,
            asset_type="3d_printer",
            capture_interval=5.0,
            **kwargs
        )
        
        # QIDI-specific PackML mappings
        self.packml_mapper = create_mapper_for_asset_type(
            "3d_printer",
            {
                "RUNNING": "Execute",
                "PAUSE": "Held",
                "FAILED": "Aborted",
                "FINISH": "Complete",
                "IDLE": "Idle",
                "PREPARING": "Starting",
                "HEATING": "Starting",
            }
        )
        
        logger.info("qidi_collector_initialized", asset_id=serial_number)


class SovolCollector(ScreenScraperCollector):
    """Specialized collector for SOVOL printers"""
    
    def __init__(
        self,
        printer_ip: str,
        serial_number: str,
        **kwargs
    ):
        # SOVOL uses port 80 for stream
        stream_url = f"http://{printer_ip}/webcam/?action=stream"
        
        super().__init__(
            stream_url=stream_url,
            asset_id=serial_number,
            asset_type="3d_printer",
            capture_interval=5.0,
            **kwargs
        )
        
        # SOVOL-specific mappings (similar to QIDI)
        self.packml_mapper = create_mapper_for_asset_type(
            "3d_printer",
            {
                "Printing": "Execute",
                "Paused": "Held",
                "Error": "Aborted",
                "Completed": "Complete",
                "Standby": "Idle",
                "Heating": "Starting",
            }
        )
        
        logger.info("sovol_collector_initialized", asset_id=serial_number)

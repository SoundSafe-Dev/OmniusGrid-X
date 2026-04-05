"""
File System Watcher for ORCA Slicer and other file-based data sources
Monitors directories for new G-code files and extracts metadata
"""

import asyncio
import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional, Callable, Set
import structlog
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileCreatedEvent, FileModifiedEvent

from omniusgrid_agent.packml import PackMLStateMapper, create_mapper_for_asset_type

logger = structlog.get_logger()


class OrcaSlicerHandler(FileSystemEventHandler):
    """Watchdog handler for ORCA Slicer output files"""
    
    def __init__(
        self,
        asset_id: str,
        watch_path: Path,
        on_file_callback: Callable,
        packml_mapper: PackMLStateMapper
    ):
        self.asset_id = asset_id
        self.watch_path = watch_path
        self.on_file_callback = on_file_callback
        self.packml_mapper = packml_mapper
        self._processed_files: Set[str] = set()
        
    def on_created(self, event):
        """Handle new file creation"""
        if not event.is_directory and event.src_path.endswith('.gcode'):
            asyncio.create_task(self._process_gcode(event.src_path))
    
    def on_modified(self, event):
        """Handle file modification (ORCA updates files during slicing)"""
        if not event.is_directory and event.src_path.endswith('.gcode'):
            # Only process if not already processed
            if event.src_path not in self._processed_files:
                asyncio.create_task(self._process_gcode(event.src_path))
    
    async def _process_gcode(self, file_path: str):
        """Parse G-code file and extract metadata"""
        try:
            path = Path(file_path)
            
            # Wait for file to be fully written
            await self._wait_for_file_stable(path)
            
            # Parse G-code header comments
            metadata = self._parse_gcode_metadata(path)
            
            # Calculate file stats
            stat = path.stat()
            
            # Estimate print time from G-code analysis
            print_time_seconds = self._estimate_print_time(path)
            
            # Create message
            packml_state = self.packml_mapper.map_state("IDLE")
            
            message = {
                'timestamp_edge': datetime.utcnow().isoformat(),
                'asset_id': self.asset_id,
                'payload': {
                    'file_path': str(file_path),
                    'file_name': path.name,
                    'file_size': stat.st_size,
                    'created_at': datetime.fromtimestamp(stat.st_ctime).isoformat(),
                    'metadata': metadata,
                    'estimated_print_time_seconds': print_time_seconds,
                    'state': 'IDLE',
                    'packml_state': packml_state.value,
                    'packml_category': self.packml_mapper.get_state_category(packml_state),
                },
                'packml_state': packml_state.value,
                'collector_type': 'orca_slicer'
            }
            
            await self.on_file_callback(message)
            
            self._processed_files.add(file_path)
            
            logger.info(
                "gcode_file_processed",
                asset_id=self.asset_id,
                file=path.name,
                print_time=print_time_seconds
            )
            
        except Exception as e:
            logger.error(
                "gcode_process_error",
                asset_id=self.asset_id,
                file=file_path,
                error=str(e)
            )
    
    async def _wait_for_file_stable(self, path: Path, timeout: int = 30):
        """Wait for file to stop changing (fully written)"""
        start_time = asyncio.get_event_loop().time()
        last_size = -1
        stable_count = 0
        
        while asyncio.get_event_loop().time() - start_time < timeout:
            try:
                current_size = path.stat().st_size
                
                if current_size == last_size:
                    stable_count += 1
                    if stable_count >= 3:  # Stable for 3 checks
                        return
                else:
                    stable_count = 0
                
                last_size = current_size
                await asyncio.sleep(0.5)
                
            except FileNotFoundError:
                await asyncio.sleep(0.5)
        
        logger.warning("file_stable_timeout", path=str(path))
    
    def _parse_gcode_metadata(self, path: Path) -> Dict[str, Any]:
        """Extract metadata from G-code header comments"""
        metadata = {}
        
        try:
            with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                # Read first 100 lines (metadata is in header)
                for i, line in enumerate(f):
                    if i > 100:
                        break
                    
                    line = line.strip()
                    if not line.startswith(';'):
                        continue
                    
                    # ORCA Slicer format: ; key = value
                    match = re.match(r'^;\s*(\w+)\s*=\s*(.+)$', line)
                    if match:
                        key = match.group(1).strip()
                        value = match.group(2).strip()
                        
                        # Try to convert to appropriate type
                        try:
                            if '.' in value:
                                value = float(value)
                            else:
                                value = int(value)
                        except ValueError:
                            pass  # Keep as string
                        
                        metadata[key] = value
                    
                    # Cura/PrusaSlicer format: ;key:value
                    match = re.match(r'^;(\w+):(.+)$', line)
                    if match:
                        key = match.group(1).strip()
                        value = match.group(2).strip()
                        metadata[key] = value
                        
        except Exception as e:
            logger.error("metadata_parse_error", path=str(path), error=str(e))
        
        return metadata
    
    def _estimate_print_time(self, path: Path) -> int:
        """Estimate print time from G-code analysis"""
        total_seconds = 0
        
        try:
            with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
                
                # Method 1: Look for time estimate in header
                time_match = re.search(r'[Tt]ime:\s*(\d+):(\d+):(\d+)', content)
                if time_match:
                    hours, minutes, seconds = map(int, time_match.groups())
                    return hours * 3600 + minutes * 60 + seconds
                
                # Method 2: Estimate from layer count and typical layer time
                layer_matches = re.findall(r';LAYER:\d+', content)
                if layer_matches:
                    layer_count = len(layer_matches)
                    # Rough estimate: 2 minutes per layer average
                    return int(layer_count * 120)
                
                # Method 3: Count G1 moves and estimate
                g1_count = content.count('G1 ')
                # Rough: 0.5 seconds per move on average
                return int(g1_count * 0.5)
                
        except Exception as e:
            logger.error("print_time_estimate_error", path=str(path), error=str(e))
        
        return 0


class OrcaSlicerCollector:
    """
    File system collector for ORCA Slicer and other slicer software.
    Watches output directories for new G-code files.
    """
    
    def __init__(
        self,
        watch_path: str,
        asset_id: str,
        asset_type: str = "3d_printer",
        packml_mappings: Optional[Dict[str, str]] = None,
        on_message_callback: Optional[Callable] = None
    ):
        self.watch_path = Path(watch_path)
        self.asset_id = asset_id
        self.asset_type = asset_type
        self.on_message_callback = on_message_callback
        
        # PackML state mapper
        self.packml_mapper = create_mapper_for_asset_type(asset_type, packml_mappings)
        
        # Watchdog components
        self.observer: Optional[Observer] = None
        self.handler: Optional[OrcaSlicerHandler] = None
        
        # Ensure watch path exists
        self.watch_path.mkdir(parents=True, exist_ok=True)
    
    async def start(self):
        """Start the file system watcher"""
        logger.info(
            "orca_collector_starting",
            asset_id=self.asset_id,
            watch_path=str(self.watch_path)
        )
        
        # Create handler
        self.handler = OrcaSlicerHandler(
            asset_id=self.asset_id,
            watch_path=self.watch_path,
            on_file_callback=self.on_message_callback or self._default_callback,
            packml_mapper=self.packml_mapper
        )
        
        # Create observer
        self.observer = Observer()
        self.observer.schedule(self.handler, str(self.watch_path), recursive=False)
        self.observer.start()
        
        # Process existing files
        await self._process_existing_files()
        
        logger.info("orca_collector_started", asset_id=self.asset_id)
        
        # Keep running
        try:
            while True:
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            pass
    
    async def _process_existing_files(self):
        """Process any G-code files already in the directory"""
        gcode_files = list(self.watch_path.glob('*.gcode'))
        
        if gcode_files:
            logger.info(
                "processing_existing_files",
                asset_id=self.asset_id,
                count=len(gcode_files)
            )
            
            for file_path in gcode_files:
                await self.handler._process_gcode(str(file_path))
    
    async def _default_callback(self, message: Dict):
        """Default callback if none provided"""
        logger.debug("orca_message", message=message)
    
    async def stop(self):
        """Stop the file system watcher"""
        logger.info("orca_collector_stopping", asset_id=self.asset_id)
        
        if self.observer:
            self.observer.stop()
            self.observer.join()
        
        logger.info("orca_collector_stopped", asset_id=self.asset_id)

"""
MLOps Pipeline - Model syncing from cloud to edge
Handles model artifact download, validation, and hot-swapping
"""

import asyncio
import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, Any
import structlog
import aiohttp

from app.core.config import settings
from app.services.tactical_engine import tactical_engine

logger = structlog.get_logger()


class ModelArtifactRegistry:
    """Interface to cloud model registry (S3-compatible or Mlflow)"""
    
    def __init__(self):
        self.registry_url = settings.MODEL_REGISTRY_URL or 'https://models.opsgrid.io'
        self.api_key = settings.MODEL_REGISTRY_API_KEY
        self.local_model_dir = Path(settings.LOCAL_MODEL_DIR or './models')
        try:
            self.local_model_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            # Fallback to temp directory if default location is not writable
            import tempfile
            self.local_model_dir = Path(tempfile.gettempdir()) / 'opsgrid_models'
            self.local_model_dir.mkdir(parents=True, exist_ok=True)
    
    async def check_for_updates(self, current_version: str) -> Optional[Dict]:
        """Check if newer model version available"""
        try:
            async with aiohttp.ClientSession() as session:
                headers = {'Authorization': f'Bearer {self.api_key}'}
                
                async with session.get(
                    f"{self.registry_url}/api/models/tactical-engine/latest",
                    headers=headers,
                    ssl=False  # Use proper SSL in production
                ) as response:
                    if response.status == 200:
                        latest = await response.json()
                        
                        if latest['version'] != current_version:
                            logger.info("new_model_available",
                                       current=current_version,
                                       latest=latest['version'])
                            return latest
                    else:
                        logger.warning("registry_check_failed", 
                                     status=response.status)
                        
        except Exception as e:
            logger.error("registry_check_error", error=str(e))
        
        return None
    
    async def download_model(self, model_info: Dict) -> Path:
        """Download model artifact from registry"""
        version = model_info['version']
        download_url = model_info['download_url']
        expected_hash = model_info['sha256_hash']
        
        local_path = self.local_model_dir / f"tactical_{version}.pt"
        
        # Skip if already cached
        if local_path.exists():
            if await self._verify_hash(local_path, expected_hash):
                logger.info("model_cached", version=version, path=str(local_path))
                return local_path
            else:
                logger.warning("cached_model_hash_mismatch", version=version)
        
        # Download
        logger.info("downloading_model", version=version, url=download_url)
        
        try:
            async with aiohttp.ClientSession() as session:
                headers = {'Authorization': f'Bearer {self.api_key}'}
                
                async with session.get(
                    download_url,
                    headers=headers,
                    ssl=False
                ) as response:
                    if response.status == 200:
                        content = await response.read()
                        
                        # Verify hash
                        actual_hash = hashlib.sha256(content).hexdigest()
                        if actual_hash != expected_hash:
                            raise ValueError(
                                f"Hash mismatch: expected {expected_hash}, got {actual_hash}"
                            )
                        
                        # Write to disk
                        local_path.write_bytes(content)
                        logger.info("model_downloaded", 
                                   version=version, 
                                   size_mb=len(content)/(1024*1024))
                        
                        return local_path
                    else:
                        raise RuntimeError(f"Download failed: {response.status}")
                        
        except Exception as e:
            logger.error("model_download_failed", 
                        version=version,
                        error=str(e))
            raise
    
    async def _verify_hash(self, file_path: Path, expected_hash: str) -> bool:
        """Verify file SHA256 hash"""
        sha256 = hashlib.sha256()
        sha256.update(file_path.read_bytes())
        return sha256.hexdigest() == expected_hash
    
    def list_local_models(self) -> Dict[str, Path]:
        """List cached models in local directory"""
        models = {}
        for model_file in self.local_model_dir.glob("tactical_*.pt"):
            version = model_file.stem.replace("tactical_", "")
            models[version] = model_file
        return models
    
    async def cleanup_old_models(self, keep_versions: int = 3):
        """Remove old model versions, keeping N most recent"""
        models = self.list_local_models()
        
        if len(models) <= keep_versions:
            return
        
        # Sort by modification time
        sorted_models = sorted(
            models.items(),
            key=lambda x: x[1].stat().st_mtime,
            reverse=True
        )
        
        # Delete old versions
        for version, path in sorted_models[keep_versions:]:
            path.unlink()
            logger.info("old_model_cleaned", version=version)


class MLOpsPipeline:
    """
    MLOps pipeline for edge model management.
    
    Flow:
    1. Poll registry for model updates
    2. Download new model artifact (ONNX/TorchScript)
    3. Validate model (test inference)
    4. Hot-swap into tactical engine
    5. Report deployment status to cloud
    """
    
    def __init__(self):
        self.registry = ModelArtifactRegistry()
        self.poll_interval = settings.MODEL_POLL_INTERVAL or 300  # 5 minutes
        self._running = False
        self._current_model_info: Optional[Dict] = None
    
    async def start(self):
        """Start the MLOps pipeline"""
        logger.info("mlops_pipeline_starting", 
                   poll_interval=self.poll_interval)
        self._running = True
        
        # Initial sync
        await self._sync_model()
        
        # Start polling loop
        asyncio.create_task(self._poll_loop())
    
    async def _poll_loop(self):
        """Continuously poll for model updates"""
        while self._running:
            try:
                await asyncio.sleep(self.poll_interval)
                await self._sync_model()
                
            except Exception as e:
                logger.error("poll_loop_error", error=str(e))
    
    async def _sync_model(self):
        """Sync model with registry"""
        current_version = tactical_engine.model_version
        
        # Check for updates
        latest = await self.registry.check_for_updates(current_version)
        
        if not latest:
            logger.debug("no_model_update_available", 
                      current_version=current_version)
            return
        
        try:
            # Download
            model_path = await self.registry.download_model(latest)
            
            # Validate
            if await self._validate_model(model_path):
                # Hot-swap
                await tactical_engine.hot_swap_model(str(model_path))
                
                # Update current info
                self._current_model_info = latest
                
                # Report deployment
                await self._report_deployment(latest, success=True)
                
                # Cleanup old versions
                await self.registry.cleanup_old_models(keep_versions=3)
                
                logger.info("model_sync_complete", 
                           new_version=latest['version'])
            else:
                logger.error("model_validation_failed", 
                            version=latest['version'])
                await self._report_deployment(latest, success=False, 
                                             error="Validation failed")
                
        except Exception as e:
            logger.error("model_sync_failed", error=str(e))
            await self._report_deployment(latest, success=False, error=str(e))
    
    async def _validate_model(self, model_path: Path) -> bool:
        """
        Validate model before deployment.
        Runs test inference to ensure model loads and produces valid output.
        """
        try:
            import torch
            
            # Load model
            model = torch.jit.load(str(model_path), map_location='cpu')
            model.eval()
            
            # Test inference with dummy input
            dummy_input = torch.randn(1, 8)  # 8 features
            
            with torch.no_grad():
                output = model(dummy_input)
            
            # Verify output shape
            if len(output) < 2:
                logger.error("validation_failed", reason="invalid_output_shape")
                return False
            
            logger.info("model_validation_passed", path=str(model_path))
            return True
            
        except Exception as e:
            logger.error("model_validation_error", error=str(e))
            return False
    
    async def _report_deployment(self, model_info: Dict, 
                                   success: bool, 
                                   error: Optional[str] = None):
        """Report deployment status to cloud"""
        from app.services.cloud_gateway import cloud_gateway
        
        report = {
            'type': 'model_deployment',
            'model_version': model_info['version'],
            'timestamp': datetime.utcnow().isoformat(),
            'success': success,
            'edge_node_id': settings.EDGE_NODE_ID or 'edge-001',
            'error': error,
        }
        
        await cloud_gateway.queue_discrete_event('mlops_deployment', report)
    
    async def manual_deploy(self, version: str) -> bool:
        """Manually trigger deployment of specific version"""
        logger.info("manual_deploy_requested", version=version)
        
        # Check if already cached
        models = self.registry.list_local_models()
        if version in models:
            model_path = models[version]
            
            if await self._validate_model(model_path):
                await tactical_engine.hot_swap_model(str(model_path))
                logger.info("manual_deploy_complete", version=version)
                return True
        
        logger.error("manual_deploy_failed", 
                    version=version,
                    reason="model_not_cached")
        return False
    
    async def rollback(self) -> bool:
        """Rollback to previous model version"""
        models = self.registry.list_local_models()
        
        if len(models) < 2:
            logger.error("rollback_failed", reason="no_previous_version")
            return False
        
        # Sort by mtime (oldest first)
        sorted_models = sorted(
            models.items(),
            key=lambda x: x[1].stat().st_mtime
        )
        
        # Get second most recent (previous version)
        previous_version, previous_path = sorted_models[-2]
        
        logger.info("rolling_back", 
                   from_version=tactical_engine.model_version,
                   to_version=previous_version)
        
        await tactical_engine.hot_swap_model(str(previous_path))
        return True
    
    def get_status(self) -> Dict:
        """Get pipeline status"""
        return {
            'current_model': tactical_engine.model_version,
            'current_model_info': self._current_model_info,
            'cached_models': list(self.registry.list_local_models().keys()),
            'poll_interval_seconds': self.poll_interval,
        }
    
    async def stop(self):
        """Stop the pipeline"""
        logger.info("mlops_pipeline_stopping")
        self._running = False


# Global instance
mlops_pipeline = MLOpsPipeline()

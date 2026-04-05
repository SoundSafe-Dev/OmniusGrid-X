"""
Local Tactical Engine API - Sub-second inference for real-time control
Handles immediate adjustments without cloud latency
"""

import asyncio
import json
from datetime import datetime
from typing import Dict, List, Any, Optional, Callable
from dataclasses import dataclass
import structlog
import numpy as np

from app.core.config import settings
from app.services.cloud_gateway import cloud_gateway

logger = structlog.get_logger()


@dataclass
class TacticalDecision:
    """Decision from local tactical engine"""
    asset_id: str
    timestamp: datetime
    action_type: str  # 'adjust_speed', 'pause_job', 'adjust_temp', etc.
    parameters: Dict[str, Any]
    confidence: float
    reasoning: str
    model_version: str
    latency_ms: float


class LocalTacticalEngine:
    """
    Local PyTorch-based inference engine for sub-second decisions.
    
    Responsibilities:
    - Real-time anomaly detection
    - Immediate parameter adjustments (spindle speed, feed rate)
    - Safety-critical decisions (emergency stops)
    - Latency < 100ms for control loops
    """
    
    def __init__(self):
        self.model_path = settings.TACTICAL_MODEL_PATH or '/models/tactical_v1.pt'
        self.model = None
        self.model_version = "unknown"
        self._decision_handlers: List[Callable] = []
        self._inference_queue: asyncio.Queue = asyncio.Queue(maxsize=1000)
        self._running = False
        self._max_latency_ms = 100  # Target latency
        
        # Safety thresholds (hard limits)
        self.safety_thresholds = {
            'temp_nozzle_max': 300,  # °C
            'temp_bed_max': 120,      # °C
            'vibration_max': 10,       # g-force
            'spindle_rpm_max': 10000,
        }
    
    async def load_model(self, model_path: Optional[str] = None):
        """Load PyTorch model for inference"""
        try:
            import torch
            import torch.jit
            
            path = model_path or self.model_path
            
            # Load TorchScript model (optimized for inference)
            self.model = torch.jit.load(path, map_location='cpu')
            self.model.eval()
            
            # Extract version from filename
            self.model_version = path.split('/')[-1].replace('.pt', '')
            
            logger.info("tactical_model_loaded", 
                       path=path,
                       version=self.model_version)
            
        except Exception as e:
            logger.error("tactical_model_load_failed", error=str(e))
            raise
    
    async def hot_swap_model(self, new_model_path: str):
        """Hot-swap model with zero downtime"""
        logger.info("model_hot_swap_starting", new_path=new_model_path)
        
        # Load new model
        old_model = self.model
        await self.load_model(new_model_path)
        
        # Atomic swap
        self.model_path = new_model_path
        del old_model  # Free memory
        
        logger.info("model_hot_swap_complete", version=self.model_version)
    
    async def infer(self, feature_vector: Dict) -> Optional[TacticalDecision]:
        """
        Run inference on feature vector.
        Target latency: < 100ms
        """
        import torch
        
        start_time = datetime.utcnow()
        
        try:
            # Check safety thresholds first (hard rules)
            safety_action = self._check_safety_thresholds(feature_vector)
            if safety_action:
                return safety_action
            
            # Prepare input tensor
            features = self._vector_to_tensor(feature_vector)
            
            # Run inference
            with torch.no_grad():
                output = self.model(features)
            
            # Parse output
            decision = self._parse_model_output(
                output, 
                feature_vector.get('asset_id'),
                start_time
            )
            
            return decision
            
        except Exception as e:
            logger.error("tactical_inference_failed", 
                      error=str(e),
                      asset_id=feature_vector.get('asset_id'))
            return None
    
    def _check_safety_thresholds(self, vector: Dict) -> Optional[TacticalDecision]:
        """Check hard safety limits - immediate action required"""
        features = vector.get('features', {})
        asset_id = vector.get('asset_id', 'unknown')
        
        # Temperature checks
        if features.get('temp_nozzle_mean', 0) > self.safety_thresholds['temp_nozzle_max']:
            return TacticalDecision(
                asset_id=asset_id,
                timestamp=datetime.utcnow(),
                action_type='emergency_stop',
                parameters={'reason': 'nozzle_temperature_critical'},
                confidence=1.0,
                reasoning=f"Nozzle temp {features['temp_nozzle_mean']}°C exceeds safety limit",
                model_version='safety_rule',
                latency_ms=0
            )
        
        if features.get('vibration_mean', 0) > self.safety_thresholds['vibration_max']:
            return TacticalDecision(
                asset_id=asset_id,
                timestamp=datetime.utcnow(),
                action_type='reduce_feed_rate',
                parameters={'reduction_percent': 50, 'reason': 'excessive_vibration'},
                confidence=0.95,
                reasoning=f"Vibration {features['vibration_mean']}g exceeds threshold",
                model_version='safety_rule',
                latency_ms=0
            )
        
        return None
    
    def _vector_to_tensor(self, vector: Dict) -> Any:
        """Convert feature vector to PyTorch tensor"""
        import torch
        
        features = vector.get('features', {})
        
        # Extract ordered feature list
        feature_list = [
            features.get('temp_nozzle_mean', 0),
            features.get('temp_nozzle_std', 0),
            features.get('temp_bed_mean', 0),
            features.get('print_speed_mean', 0),
            features.get('progress_velocity', 0),
            features.get('execute_time_ratio', 0),
            features.get('temp_stability_score', 0),
            features.get('state_transition_count', 0),
        ]
        
        # Normalize (simple min-max scaling)
        # In production, use proper normalization from training
        normalized = [(f - 0.5) / 0.5 for f in feature_list]
        
        return torch.tensor([normalized], dtype=torch.float32)
    
    def _parse_model_output(self, output: Any, asset_id: str, start_time: datetime) -> TacticalDecision:
        """Parse model output into actionable decision"""
        import torch
        
        # Calculate latency
        latency_ms = (datetime.utcnow() - start_time).total_seconds() * 1000
        
        # Model output format: [action_probs, parameter_adjustments]
        action_probs = output[0].softmax(dim=-1)
        param_adjusts = output[1]
        
        # Get highest probability action
        action_idx = torch.argmax(action_probs).item()
        confidence = action_probs[action_idx].item()
        
        # Action mapping
        actions = ['no_change', 'reduce_speed', 'increase_speed', 'pause', 'adjust_temp']
        action_type = actions[action_idx] if action_idx < len(actions) else 'no_change'
        
        # Build parameters
        parameters = {}
        if action_type in ['reduce_speed', 'increase_speed']:
            speed_adjust = param_adjusts[0].item()
            parameters['speed_delta_percent'] = speed_adjust * 10
        
        return TacticalDecision(
            asset_id=asset_id,
            timestamp=datetime.utcnow(),
            action_type=action_type,
            parameters=parameters,
            confidence=confidence,
            reasoning=f"Model inference with {confidence:.2f} confidence",
            model_version=self.model_version,
            latency_ms=latency_ms
        )
    
    async def execute_decision(self, decision: TacticalDecision) -> bool:
        """
        Execute a tactical decision.
        Returns True if executed, False if blocked.
        """
        # Check maintenance mode (blocks automated actions)
        if await self._is_maintenance_mode(decision.asset_id):
            logger.info("decision_blocked_maintenance", 
                       asset_id=decision.asset_id,
                       action=decision.action_type)
            return False
        
        # Check confidence threshold
        if decision.confidence < 0.7:
            logger.info("decision_blocked_low_confidence",
                       asset_id=decision.asset_id,
                       confidence=decision.confidence)
            return False
        
        # Execute via command queue
        await self._send_command(decision)
        
        # Log to cloud for training feedback
        await cloud_gateway.queue_discrete_event(
            'tactical_decision',
            {
                'asset_id': decision.asset_id,
                'action_type': decision.action_type,
                'parameters': decision.parameters,
                'confidence': decision.confidence,
                'model_version': decision.model_version,
                'latency_ms': decision.latency_ms,
            }
        )
        
        logger.info("tactical_decision_executed",
                   asset_id=decision.asset_id,
                   action=decision.action_type,
                   latency_ms=decision.latency_ms)
        
        return True
    
    async def _is_maintenance_mode(self, asset_id: str) -> bool:
        """Check if asset is in maintenance mode"""
        from sqlalchemy import text
        from app.db.database import AsyncSessionLocal
        
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                text(f"""
                    SELECT maintenance_mode 
                    FROM assets 
                    WHERE id = '{asset_id}'
                """)
            )
            row = result.fetchone()
            return row and row[0]
    
    async def _send_command(self, decision: TacticalDecision):
        """Send command to asset via command queue"""
        # Queue in commands topic
        command = {
            'asset_id': decision.asset_id,
            'command_type': 'tactical',
            'action': decision.action_type,
            'parameters': decision.parameters,
            'timestamp': decision.timestamp.isoformat(),
            'model_version': decision.model_version,
        }
        
        # Publish to command queue (Redpanda)
        # Implementation depends on messaging setup
        logger.debug("command_queued", command=command)
    
    async def start(self):
        """Start the inference loop"""
        logger.info("tactical_engine_starting")
        self._running = True
        
        # Load initial model
        await self.load_model()
        
        # Start inference worker
        asyncio.create_task(self._inference_loop())
    
    async def _inference_loop(self):
        """Continuous inference on incoming feature vectors"""
        while self._running:
            try:
                # Get next feature vector from queue
                vector = await asyncio.wait_for(
                    self._inference_queue.get(),
                    timeout=1.0
                )
                
                # Run inference
                decision = await self.infer(vector)
                
                if decision:
                    await self.execute_decision(decision)
                    
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                logger.error("inference_loop_error", error=str(e))
    
    async def queue_inference(self, feature_vector: Dict):
        """Queue a feature vector for inference"""
        try:
            self._inference_queue.put_nowait(feature_vector)
        except asyncio.QueueFull:
            logger.warning("inference_queue_full")
    
    async def stop(self):
        """Stop the engine"""
        logger.info("tactical_engine_stopping")
        self._running = False


# Global instance
tactical_engine = LocalTacticalEngine()

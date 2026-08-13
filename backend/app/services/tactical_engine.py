"""
Local Tactical Engine API - Sub-second inference for real-time control
Handles immediate adjustments without cloud latency
"""

import asyncio
import json
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional, Callable
from dataclasses import dataclass
import structlog
import numpy as np

from app.core.config import settings
from app.services.cloud_gateway import cloud_gateway
from app.core.tasks import spawn

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
    # Optional, and defaulted, because nothing upstream carries a tenant today: the
    # feature vector is asset_id-keyed all the way from the edge. Without it the
    # maintenance check cannot see the row and suppresses — see _is_maintenance_mode.
    organization_id: Optional[str] = None


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
        self._model_loaded = False
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
            self._model_loaded = True
            
            logger.info("tactical_model_loaded", 
                       path=path,
                       version=self.model_version)
            
        except FileNotFoundError:
            logger.warning(
                "tactical_model_not_found",
                path=model_path or self.model_path,
                message="Model file not found, operating in simulation mode"
            )
            self._model_loaded = False
            self.model_version = "simulation"
        except Exception as e:
            logger.error("tactical_model_load_failed", error=str(e))
            self._model_loaded = False
            self.model_version = "simulation"
    
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
        
        start_time = datetime.now(timezone.utc)
        
        try:
            # Check safety thresholds first (hard rules)
            safety_action = self._check_safety_thresholds(feature_vector)
            if safety_action:
                return safety_action
            
            # If model not loaded, use simulation mode
            if not self._model_loaded:
                return self._simulate_decision(feature_vector, start_time)
            
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
                timestamp=datetime.now(timezone.utc),
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
                timestamp=datetime.now(timezone.utc),
                action_type='reduce_feed_rate',
                parameters={'reduction_percent': 50, 'reason': 'excessive_vibration'},
                confidence=0.95,
                reasoning=f"Vibration {features['vibration_mean']}g exceeds threshold",
                model_version='safety_rule',
                latency_ms=0
            )
        
        return None
    
    def _simulate_decision(self, feature_vector: Dict, start_time: datetime) -> TacticalDecision:
        """
        Generate simulated decision when model is not loaded.
        Uses rule-based heuristics based on feature values.
        """
        features = feature_vector.get('features', {})
        asset_id = feature_vector.get('asset_id', 'unknown')
        
        # Calculate latency
        latency_ms = (datetime.now(timezone.utc) - start_time).total_seconds() * 1000
        
        # Rule-based decision logic
        action_type = 'no_change'
        parameters = {}
        confidence = 0.7
        reasoning = "Simulation mode - rule-based decision"
        
        # Check for concerning patterns
        temp_nozzle = features.get('temp_nozzle_mean', 0)
        vibration = features.get('vibration_mean', 0)
        print_speed = features.get('print_speed_mean', 0)
        
        if temp_nozzle > 250:  # Approaching max
            action_type = 'reduce_speed'
            parameters = {'speed_delta_percent': -10, 'reason': 'high_temperature'}
            confidence = 0.8
            reasoning = f"Nozzle temp {temp_nozzle}°C high, reducing speed"
        elif vibration > 5:  # Elevated vibration
            action_type = 'reduce_speed'
            parameters = {'speed_delta_percent': -15, 'reason': 'elevated_vibration'}
            confidence = 0.85
            reasoning = f"Vibration {vibration}g elevated, reducing speed"
        elif print_speed > 100:  # Very high speed
            action_type = 'reduce_speed'
            parameters = {'speed_delta_percent': -5, 'reason': 'speed_optimization'}
            confidence = 0.6
            reasoning = "Optimizing speed for quality"
        
        return TacticalDecision(
            asset_id=asset_id,
            timestamp=datetime.now(timezone.utc),
            action_type=action_type,
            parameters=parameters,
            confidence=confidence,
            reasoning=reasoning,
            model_version=self.model_version,
            latency_ms=latency_ms
        )
    
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
        latency_ms = (datetime.now(timezone.utc) - start_time).total_seconds() * 1000
        
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
            timestamp=datetime.now(timezone.utc),
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
        if await self._is_maintenance_mode(
            decision.asset_id, decision.organization_id
        ):
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
        
        # Execute via command queue. This CAN fail to dispatch — see
        # _dispatch_command — and the result decides what we return and what we
        # tell the training loop.
        dispatched = await self._dispatch_command(decision)

        # Log to cloud for training feedback.
        #
        # `dispatched` is part of the payload on purpose. This event is training
        # feedback: a decision that never reached the asset produced no effect to
        # learn from, and feeding it in as though it had actuated teaches the model
        # from an outcome that never happened.
        await cloud_gateway.queue_discrete_event(
            'tactical_decision',
            {
                'asset_id': decision.asset_id,
                'action_type': decision.action_type,
                'parameters': decision.parameters,
                'confidence': decision.confidence,
                'model_version': decision.model_version,
                'latency_ms': decision.latency_ms,
                'dispatched': dispatched,
            }
        )

        if not dispatched:
            logger.warning("tactical_decision_not_dispatched",
                           asset_id=decision.asset_id,
                           action=decision.action_type,
                           reason="no command sink configured")
            return False

        logger.info("tactical_decision_executed",
                   asset_id=decision.asset_id,
                   action=decision.action_type,
                   latency_ms=decision.latency_ms)

        return True
    
    async def _is_maintenance_mode(
        self, asset_id: str, organization_id: Optional[str] = None
    ) -> bool:
        """True when the asset must not be commanded — INCLUDING when we cannot tell.

        Bound parameter, never f-string interpolation: `asset_id` originates from the
        feature vector (edge/ingestion data), so `' OR '1'='1` used to match every row.

        THE ROW IS NORMALLY INVISIBLE HERE, and that used to read as clearance.
        `assets` is FORCE ROW LEVEL SECURITY and the app connects as `tenant_user`, a
        non-owner, so the policy

            USING (organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid)

        evaluates to NULL on a session with no GUC and filters every row. `AsyncSessionLocal`
        sets no GUC — nothing here runs behind a request. The old body was

            return bool(row and row[0])

        which turned "no row I am allowed to see" into False, *not in maintenance*: an
        asset an operator had explicitly locked out would have been commanded anyway.

        That was masked for as long as the schema had no `maintenance_mode` column at
        all — the query raised, the except branch returned True, and every asset looked
        suppressed. Adding the column (migration 053) would have flipped the whole
        engine from suppress-everything to suppress-nothing in one step, which is why
        the read had to be fixed in the same change as the write.

        Three outcomes now, not two: in maintenance / not in maintenance / **could not
        determine**, the last folded into "do not command" and logged as itself. Pass
        `organization_id` to get a real answer; a caller that cannot name the tenant
        gets a suppression, deliberately.
        """
        from sqlalchemy import text
        from app.db.database import AsyncSessionLocal

        try:
            async with AsyncSessionLocal() as session:
                if organization_id and session.bind is not None and (
                    session.bind.dialect.name == "postgresql"
                ):
                    await session.execute(
                        text("SELECT set_config('app.current_org_id', :org, true)"),
                        {"org": str(organization_id)},
                    )
                result = await session.execute(
                    text("SELECT maintenance_mode FROM assets WHERE id = :asset_id"),
                    {"asset_id": asset_id},
                )
                row = result.fetchone()
                if row is None:
                    # Deleted, mistyped, or — far more often — filtered by RLS because
                    # no tenant was named. Suppressing is the safe reading; saying so is
                    # what stops it being mistaken for a clean asset.
                    logger.warning(
                        "maintenance_mode_asset_not_visible",
                        asset_id=asset_id,
                        organization_id=organization_id,
                        detail=(
                            "no readable assets row; suppressing the command rather "
                            "than treating an invisible asset as available"
                        ),
                    )
                    return True
                return bool(row[0])
        except Exception as exc:
            logger.warning(
                "maintenance_mode_check_failed", asset_id=asset_id, error=str(exc)
            )
            return True

    async def _dispatch_command(self, decision: TacticalDecision) -> bool:
        """Dispatch a decision to the asset. Returns True only if it was actually sent.

        NOT WIRED, AND SAYING SO IS THE POINT. This was `_send_command`, returning
        nothing, whose entire body built a `command` dict and then logged
        ``command_queued`` at DEBUG under the comment *"Implementation depends on
        messaging setup"*. Nothing was ever published. `execute_decision` then logged
        ``tactical_decision_executed`` and returned **True** — its docstring promises
        "True if executed" — for a control command that reached no asset.

        That made it the most consequential shape of this defect in the codebase: the
        two safety gates immediately above it, maintenance-mode and the 0.7 confidence
        floor, are implemented properly and carefully. The maintenance check even fails
        SAFE, with a comment reading *"a broken control command is worse than a skipped
        one."* Anyone reading that had every reason to assume the dispatch below it was
        equally real.

        It is currently unreachable — `execute_decision` is only called from
        `_inference_loop`, and `start()` is absent from `main.py`'s startup list. That
        is the only reason this has never mattered. It is one line away from mattering:
        the other seven engines are all started there.

        WHY THIS REFUSES RATHER THAN DISPATCHES. The real sink exists and is already
        running — `command_executor` (started in `main.py`), backed by the `Command`
        model, and `api/commands.py` already documents ``"tactical"`` as a command type,
        so this was clearly meant to feed it. Wiring it would switch on autonomous
        actuation of industrial assets, which is a deliberate decision with a safety
        review attached, not a side effect of a naming fix. So the honest state is to
        refuse and report it, exactly as `erp_database_replication.start_replication`
        does for its stubbed CDC helpers.

        To wire it: submit through `command_executor` with `command_type="tactical"`
        and return its accepted/rejected result, then delete this note.
        """
        logger.warning(
            "tactical_command_not_dispatched",
            asset_id=decision.asset_id,
            action=decision.action_type,
            detail=(
                "the tactical engine has no command sink; the decision was computed "
                "but not sent to the asset"
            ),
        )
        return False
    
    async def start(self):
        """Start the inference loop"""
        logger.info("tactical_engine_starting")
        self._running = True
        
        # Load initial model
        await self.load_model()
        
        # Start inference worker
        spawn(self._inference_loop(), name="tactical_engine.inference_loop")
    
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

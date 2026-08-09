"""
OEE (Overall Equipment Effectiveness) Calculator
Automated from telemetry data using PackML state machine
"""

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional, Any, List
from dataclasses import dataclass, field
from enum import Enum
import structlog
from sqlalchemy import select

from app.core.datetime_utils import aware_utc
from app.db.database import AsyncSessionLocal
from app.db.models import Asset, Telemetry, PackMLState
from app.services.websocket_manager import websocket_manager

logger = structlog.get_logger()


class OEEStateCategory(Enum):
    """PackML state categories for OEE calculation"""
    PRODUCTION = "production"  # Execute, Running
    PLANNED_STOP = "planned_stop"  # Idle, Stopped, Complete
    UNPLANNED_STOP = "unplanned_stop"  # Aborted, Held, Suspended


@dataclass
class OEEMetrics:
    """OEE metrics for a time period"""
    availability: float = 0.0  # % (Run Time / Planned Production Time)
    performance: float = 0.0   # % (Ideal Cycle Time / Actual Cycle Time)
    quality: float = 0.0       # % (Good Parts / Total Parts)
    oee: float = 0.0           # % (Availability × Performance × Quality)
    
    # Supporting metrics
    runtime_minutes: float = 0.0
    planned_downtime_minutes: float = 0.0
    unplanned_downtime_minutes: float = 0.0
    total_parts: int = 0
    good_parts: int = 0
    rejected_parts: int = 0
    ideal_cycle_time_seconds: float = 0.0
    # Which factors were actually MEASURABLE (FS-234). Quality falls back to 1.0
    # when there are no part counters, because it has to be a neutral multiplier
    # for OEE — but reporting "Quality 100%" for a line with no quality
    # instrumentation is a fabricated figure on a dashboard tile. These flags let
    # a consumer render "—" instead of a number nobody measured.
    quality_measured: bool = True
    performance_measured: bool = True
    actual_cycle_time_seconds: float = 0.0


@dataclass
class StateTransition:
    """Record of a state transition"""
    timestamp: datetime
    from_state: str
    to_state: str
    duration_seconds: Optional[float] = None


# Canonical definition now lives in app.core.datetime_utils so workers can share
# it. Kept as a module-level alias: this name is referenced throughout the file
# and in tests.
_aware_utc = aware_utc


class OEECalculator:
    """
    Automated OEE calculation from telemetry and PackML states.

    Monitors asset state transitions to calculate:
    - Availability: Production time vs planned time
    - Performance: Actual vs ideal cycle time
    - Quality: Good parts vs total parts

    Uses telemetry counters for automatic part counting.
    """
    
    # PackML state to category mapping
    STATE_CATEGORIES = {
        'Execute': OEEStateCategory.PRODUCTION,
        'Running': OEEStateCategory.PRODUCTION,
        'Processing': OEEStateCategory.PRODUCTION,
        'Idle': OEEStateCategory.PLANNED_STOP,
        'Stopped': OEEStateCategory.PLANNED_STOP,
        'Complete': OEEStateCategory.PLANNED_STOP,
        'Aborted': OEEStateCategory.UNPLANNED_STOP,
        'Held': OEEStateCategory.UNPLANNED_STOP,
        'Suspended': OEEStateCategory.UNPLANNED_STOP,
        'Starting': OEEStateCategory.PLANNED_STOP,
        'Clearing': OEEStateCategory.PLANNED_STOP,
        'Stopping': OEEStateCategory.PLANNED_STOP,
        'Aborting': OEEStateCategory.UNPLANNED_STOP,
        'Holding': OEEStateCategory.UNPLANNED_STOP,
        'Unholding': OEEStateCategory.PLANNED_STOP,
        'Suspending': OEEStateCategory.UNPLANNED_STOP,
        'Unsuspending': OEEStateCategory.PLANNED_STOP,
        'Resetting': OEEStateCategory.PLANNED_STOP,
        'Completing': OEEStateCategory.PLANNED_STOP,
    }
    
    def __init__(
        self,
        calculation_interval_minutes: int = 15,
        min_state_duration_seconds: float = 5.0
    ):
        self.calculation_interval = calculation_interval_minutes
        self.min_state_duration = min_state_duration_seconds
        
        # Asset state tracking
        self._asset_states: Dict[str, Dict] = {}
        self._state_history: Dict[str, List[StateTransition]] = {}
        
        # Running flag
        self._running = False
        self._calculation_task: Optional[asyncio.Task] = None
    
    async def start(self):
        """Start the OEE calculator"""
        logger.info("oee_calculator_starting")
        self._running = True
        
        # Start periodic calculation
        self._calculation_task = asyncio.create_task(self._calculation_loop())
        
        logger.info("oee_calculator_started")
    
    async def stop(self):
        """Stop the OEE calculator"""
        logger.info("oee_calculator_stopping")
        self._running = False
        
        if self._calculation_task:
            self._calculation_task.cancel()
            try:
                await self._calculation_task
            except asyncio.CancelledError:
                pass
        
        logger.info("oee_calculator_stopped")
    
    async def process_state_change(
        self,
        asset_id: str,
        organization_id: str,
        previous_state: str,
        new_state: str,
        timestamp: Optional[datetime] = None
    ):
        """
        Process a PackML state change for OEE tracking.
        Called by ingestion worker on state transitions.
        """
        if timestamp is None:
            timestamp = datetime.now(timezone.utc)
        elif timestamp.tzinfo is None:
            # Boundary coercion: callers (edge ingest payloads, SQLite-loaded
            # values, tests) may pass naive datetimes; internal comparisons are
            # timezone-aware since the FS-96 sweep, so treat naive as UTC here
            # instead of exploding at every downstream `>` / `-`.
            timestamp = timestamp.replace(tzinfo=timezone.utc)

        # Initialize asset tracking if needed
        if asset_id not in self._asset_states:
            self._asset_states[asset_id] = {
                'current_state': new_state,
                'state_start_time': timestamp,
                'organization_id': organization_id
            }
            self._state_history[asset_id] = []
            return
        
        asset_state = self._asset_states[asset_id]
        
        # Calculate duration of previous state
        duration = (timestamp - _aware_utc(asset_state['state_start_time'])).total_seconds()
        
        # Record transition
        transition = StateTransition(
            timestamp=asset_state['state_start_time'],
            from_state=asset_state['current_state'],
            to_state=new_state,
            duration_seconds=duration
        )
        
        self._state_history[asset_id].append(transition)
        
        # Trim history (keep last 24 hours)
        cutoff = timestamp - timedelta(hours=24)
        self._state_history[asset_id] = [
            t for t in self._state_history[asset_id]
            if _aware_utc(t.timestamp) > cutoff
        ]
        
        # Update current state
        asset_state['current_state'] = new_state
        asset_state['state_start_time'] = timestamp
        
        logger.debug(
            "oee_state_transition",
            asset_id=asset_id,
            from_state=previous_state,
            to_state=new_state,
            duration=duration
        )
    
    async def process_telemetry(
        self,
        asset_id: str,
        organization_id: str,
        telemetry: Dict[str, Any]
    ):
        """
        Process telemetry for part counting.
        Called by ingestion worker on telemetry updates.
        """
        # Look for part counter metrics
        part_counters = self._extract_part_counters(telemetry)
        
        if part_counters:
            logger.debug(
                "oee_part_counters",
                asset_id=asset_id,
                counters=part_counters
            )
    
    def _extract_part_counters(self, telemetry: Dict) -> Dict[str, int]:
        """Extract part counter values from telemetry"""
        counters = {}
        
        # Common counter metric names
        counter_names = [
            'parts_produced', 'parts_count', 'total_parts',
            'good_parts', 'parts_ok',
            'rejected_parts', 'parts_ng', 'reject_count',
            'cycle_count', 'batch_count'
        ]
        
        for name in counter_names:
            if name in telemetry:
                try:
                    value = telemetry[name]
                    if isinstance(value, (int, float)):
                        counters[name] = int(value)
                except (ValueError, TypeError):
                    pass
        
        return counters
    
    async def _calculation_loop(self):
        """Periodic OEE calculation loop"""
        while self._running:
            try:
                await asyncio.sleep(self.calculation_interval * 60)
                
                # Calculate OEE for all tracked assets
                for asset_id in self._asset_states:
                    try:
                        oee = await self.calculate_oee(asset_id)
                        
                        # Store in database
                        # NOT PERSISTED, and there is nothing here to persist it to.
                        # This called `_store_oee_metrics`, which passed the STRING
                        # "oee_metrics" to `insert()` — SQLAlchemy cannot make a table
                        # out of that — and swallowed the failure in a broad `except`
                        # that logged `oee_store_error`. No migration creates an
                        # `oee_metrics` table either, so the write could never have
                        # landed. Since this loop runs (main.py starts oee_calculator),
                        # it produced that error for every asset on every pass.
                        #
                        # Nothing is lost. OEE here is DERIVED from `packml_states` and
                        # `telemetry`, both already persisted, and `get_historical_oee`
                        # recomputes it from them. A metrics table would be a cache, and
                        # it was never built. The method is gone rather than left as a
                        # no-op named `_store_*`: a helper that claims a side effect must
                        # produce it (`test_helper_names_match_behaviour.py` fails
                        # otherwise, which is how this note came to be written).
                        #
                        # If a rollup is wanted later it needs a migration, an ORM model,
                        # tenant scoping under RLS and a retention policy.
                        
                        # Broadcast via WebSocket
                        org_id = self._asset_states[asset_id].get('organization_id')
                        if org_id:
                            await self._broadcast_oee(org_id, asset_id, oee)
                    
                    except Exception as e:
                        logger.error(
                            "oee_calculation_error",
                            asset_id=asset_id,
                            error=str(e)
                        )
            
            except Exception as e:
                logger.error("oee_calculation_loop_error", error=str(e))
    
    async def calculate_oee(
        self,
        asset_id: str,
        time_window_hours: float = 1.0
    ) -> OEEMetrics:
        """
        Calculate OEE metrics for an asset.
        
        Args:
            asset_id: Asset to calculate for
            time_window_hours: Time window for calculation (default 1 hour)
        """
        if asset_id not in self._state_history:
            return OEEMetrics()
        
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(hours=time_window_hours)
        
        # Get relevant state transitions
        transitions = [
            t for t in self._state_history[asset_id]
            if _aware_utc(t.timestamp) > cutoff
        ]
        
        # Include current state
        asset_state = self._asset_states.get(asset_id, {})
        if asset_state:
            current_duration = (now - asset_state['state_start_time']).total_seconds()
            transitions.append(StateTransition(
                timestamp=asset_state['state_start_time'],
                from_state=asset_state['current_state'],
                to_state=asset_state['current_state'],
                duration_seconds=current_duration
            ))
        
        # Calculate time in each category
        total_seconds = time_window_hours * 3600
        production_seconds = 0.0
        planned_stop_seconds = 0.0
        unplanned_stop_seconds = 0.0
        
        for transition in transitions:
            if not transition.duration_seconds:
                continue
            
            # Filter out very short states (noise)
            if transition.duration_seconds < self.min_state_duration:
                continue
            
            category = self._get_state_category(transition.from_state)
            
            if category == OEEStateCategory.PRODUCTION:
                production_seconds += transition.duration_seconds
            elif category == OEEStateCategory.PLANNED_STOP:
                planned_stop_seconds += transition.duration_seconds
            else:
                unplanned_stop_seconds += transition.duration_seconds
        
        # Normalize to total time
        actual_total = production_seconds + planned_stop_seconds + unplanned_stop_seconds
        if actual_total > 0:
            scale_factor = total_seconds / actual_total
            production_seconds *= scale_factor
            planned_stop_seconds *= scale_factor
            unplanned_stop_seconds *= scale_factor
        
        # Calculate Availability
        run_time = production_seconds
        planned_production_time = total_seconds - planned_stop_seconds
        availability = run_time / planned_production_time if planned_production_time > 0 else 0.0
        
        # Get part counts from database
        part_counts = await self._get_part_counts(asset_id, cutoff, now)
        
        # Calculate Performance (requires ideal cycle time from asset config)
        ideal_cycle_time = await self._get_ideal_cycle_time(asset_id)
        actual_cycle_time = self._calculate_actual_cycle_time(
            production_seconds, part_counts['total']
        )
        
        performance_measured = actual_cycle_time > 0
        performance = (
            ideal_cycle_time / actual_cycle_time
            if performance_measured else 0.0
        )

        # Calculate Quality
        total_parts = part_counts['total']
        good_parts = part_counts['good']
        # 1.0 when there is no part data: quality has to stay a neutral multiplier
        # so OEE is not zeroed by missing instrumentation. But the flag records
        # that nothing was measured, because "Quality 100%" on a line with no
        # part counters is a number the platform invented.
        quality_measured = total_parts > 0
        quality = good_parts / total_parts if quality_measured else 1.0

        # Calculate OEE
        oee = availability * performance * quality
        
        return OEEMetrics(
            availability=round(availability * 100, 2),
            performance=round(performance * 100, 2),
            quality=round(quality * 100, 2),
            oee=round(oee * 100, 2),
            runtime_minutes=round(production_seconds / 60, 2),
            planned_downtime_minutes=round(planned_stop_seconds / 60, 2),
            unplanned_downtime_minutes=round(unplanned_stop_seconds / 60, 2),
            total_parts=total_parts,
            good_parts=good_parts,
            rejected_parts=part_counts['rejected'],
            ideal_cycle_time_seconds=ideal_cycle_time,
            actual_cycle_time_seconds=round(actual_cycle_time, 2),
            quality_measured=quality_measured,
            performance_measured=performance_measured,
        )
    
    def _get_state_category(self, state: str) -> OEEStateCategory:
        """Get OEE category for a PackML state"""
        return self.STATE_CATEGORIES.get(state, OEEStateCategory.PLANNED_STOP)
    
    async def _get_part_counts(
        self,
        asset_id: str,
        start_time: datetime,
        end_time: datetime
    ) -> Dict[str, int]:
        """Get part counts from telemetry data"""
        async with AsyncSessionLocal() as session:
            # Query for counter metrics in time window
            result = await session.execute(
                select(Telemetry).where(
                    Telemetry.asset_id == asset_id,
                    Telemetry.timestamp >= start_time,
                    Telemetry.timestamp <= end_time,
                    Telemetry.metric_name.in_([
                        'parts_produced', 'parts_count', 'total_parts',
                        'good_parts', 'parts_ok',
                        'rejected_parts', 'parts_ng'
                    ])
                ).order_by(Telemetry.timestamp.desc())
            )
            
            records = result.scalars().all()
            
            if not records:
                return {'total': 0, 'good': 0, 'rejected': 0}
            
            # Get latest values for each counter type
            latest_values = {}
            for record in records:
                if record.metric_name not in latest_values:
                    latest_values[record.metric_name] = record.value
            
            # Calculate totals
            total = int(latest_values.get('parts_produced',
                latest_values.get('parts_count',
                    latest_values.get('total_parts', 0))))
            
            good = int(latest_values.get('good_parts',
                latest_values.get('parts_ok', total)))
            
            rejected = int(latest_values.get('rejected_parts',
                latest_values.get('parts_ng', 0)))
            
            return {
                'total': total,
                'good': good,
                'rejected': rejected
            }
    
    async def _get_ideal_cycle_time(self, asset_id: str) -> float:
        """Get ideal cycle time from asset configuration"""
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(Asset).where(Asset.id == asset_id)
            )
            asset = result.scalar_one_or_none()
            
            if asset and asset.connection_config:
                return float(asset.connection_config.get('ideal_cycle_time_seconds', 60.0))
            
            return 60.0  # Default 1 minute
    
    def _calculate_actual_cycle_time(
        self,
        production_seconds: float,
        total_parts: int
    ) -> float:
        """Calculate actual cycle time from runtime and parts produced"""
        if total_parts > 0:
            return production_seconds / total_parts
        return 0.0
    
    async def _broadcast_oee(
        self,
        organization_id: str,
        asset_id: str,
        oee: OEEMetrics
    ):
        """Broadcast OEE metrics via WebSocket"""
        try:
            await websocket_manager.publish_telemetry(
                organization_id=organization_id,
                asset_id=asset_id,
                telemetry_data={
                    'oee': oee.oee,
                    'availability': oee.availability,
                    'performance': oee.performance,
                    'quality': oee.quality,
                    'runtime_minutes': oee.runtime_minutes,
                    'total_parts': oee.total_parts,
                    'good_parts': oee.good_parts
                },
                packml_state=None
            )
        except Exception as e:
            logger.warning("oee_broadcast_error", asset_id=asset_id, error=str(e))
    
    #: PackML states that count as producing. Kept local rather than imported from
    #: dashboard_analytics so the service layer does not depend on an API module.
    _RUNNING_STATES = ("Execute", "EXECUTE", "execute")

    async def get_historical_oee(
        self,
        asset_id: str,
        start_time: datetime,
        end_time: datetime,
        aggregation: str = 'hourly'  # 'hourly', 'daily'
    ) -> List[Dict]:
        """Availability per time bucket for one asset, from recorded PackML states.

        WHAT THIS REPLACED, AND WHY NOTHING NOTICED. Every column reference in the old
        query was a PYTHON STRING rather than a mapped column:

            func.avg("oee_metrics.availability")           # averages a string literal
            "oee_metrics.asset_id" == asset_id             # a str == uuid -> False
            "oee_metrics.timestamp" >= start_time          # str >= datetime -> TypeError

        The third raised before the statement was ever compiled, so this function had
        never returned a row. `health_index` calls it inside a broad `except` and logged
        `health_index_oee_unavailable` on every asset, every time; `/api/v1/oee/historical/
        {asset_id}` has no such handler and returned a 500.

        And it could not have worked regardless: **there is no `oee_metrics` table** in
        any migration. Its writer, `_store_oee_metrics`, passed the same string to
        `insert()` and swallowed the failure, so the reader was querying a table nothing
        had ever created and nothing had ever written.

        The replacement uses `packml_states`, which is real, populated, and already the
        basis of `/api/v1/dashboard/oee/trend`. That means AVAILABILITY only: performance
        needs a per-asset ideal cycle time and quality needs part counters, and neither
        can be resolved in one GROUP BY. Each row says so rather than reporting 1.0 for
        the two factors it cannot measure — the same distinction the dashboard endpoint
        and the per-asset OEE panel already make.
        """
        seconds = 86400 if aggregation == "daily" else 3600

        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(
                    PackMLState.state_entered_at,
                    PackMLState.duration_seconds,
                ).where(
                    PackMLState.asset_id == asset_id,
                    PackMLState.state.in_(self._RUNNING_STATES),
                    PackMLState.state_entered_at >= start_time,
                    PackMLState.state_entered_at <= end_time,
                )
            )
            rows = result.all()

        # Bucketed in Python rather than SQL: `date_trunc` is Postgres-only and this
        # service also runs against the SQLite offline demo path.
        run_seconds: Dict[datetime, float] = {}
        for entered_at, duration in rows:
            entered_at = aware_utc(entered_at)
            if entered_at is None:
                continue
            epoch = int(entered_at.timestamp())
            bucket = datetime.fromtimestamp(
                epoch - (epoch % seconds), tz=timezone.utc
            )
            run_seconds[bucket] = run_seconds.get(bucket, 0.0) + float(duration or 0)

        return [
            {
                'period': bucket.isoformat(),
                'availability': round(min(1.0, total / seconds), 4),
                # None, not 1.0. A neutral multiplier is the right arithmetic for an OEE
                # product and the wrong thing to report as a measurement.
                'performance': None,
                'quality': None,
                'oee': None,
                'availability_only': True,
            }
            for bucket, total in sorted(run_seconds.items())
        ]


# Global instance
oee_calculator = OEECalculator()

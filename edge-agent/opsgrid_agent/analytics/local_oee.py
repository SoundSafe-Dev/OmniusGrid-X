"""Local OEE Calculation Module for Edge Agent"""

from typing import Dict, Any, Optional
from datetime import datetime, timedelta
from collections import defaultdict
import structlog

logger = structlog.get_logger()


class LocalOEECalculator:
    """
    Calculate Overall Equipment Effectiveness (OEE) locally at the edge.
    
    OEE = Availability × Performance × Quality
    
    Availability = Operating Time / Planned Production Time
    Performance = (Total Parts × Ideal Cycle Time) / Operating Time
    Quality = Good Parts / Total Parts
    """
    
    def __init__(self, asset_id: str):
        self.asset_id = asset_id
        self.state_history: list[Dict[str, Any]] = []
        self.production_count: int = 0
        self.good_count: int = 0
        self.ideal_cycle_time: float = 60.0  # seconds (default)
        self.planned_production_time: float = 8 * 3600  # 8 hours in seconds
    
    def add_state_change(
        self,
        state: str,
        previous_state: str,
        timestamp: datetime,
        duration_seconds: Optional[float] = None
    ) -> None:
        """
        Add a PackML state change to history.
        
        Args:
            state: New PackML state
            previous_state: Previous PackML state
            timestamp: When the state change occurred
            duration_seconds: Duration of previous state (if known)
        """
        self.state_history.append({
            "state": state,
            "previous_state": previous_state,
            "timestamp": timestamp,
            "duration_seconds": duration_seconds
        })
        
        # Keep only last 24 hours of history
        cutoff = datetime.now() - timedelta(hours=24)
        self.state_history = [
            s for s in self.state_history
            if s["timestamp"] > cutoff
        ]
        
        logger.debug(
            "state_change_added",
            asset_id=self.asset_id,
            state=state,
            previous_state=previous_state
        )
    
    def add_production_count(self, count: int, good_count: int) -> None:
        """
        Add production count data.
        
        Args:
            count: Total parts produced
            good_count: Good parts (no defects)
        """
        self.production_count = count
        self.good_count = good_count
        
        logger.debug(
            "production_count_added",
            asset_id=self.asset_id,
            total=count,
            good=good_count
        )
    
    def calculate_availability(self, time_window_hours: float = 8) -> float:
        """
        Calculate availability percentage.
        
        Availability = Operating Time / Planned Production Time
        
        Args:
            time_window_hours: Time window for calculation (default 8 hours)
            
        Returns:
            Availability as a percentage (0-100)
        """
        cutoff = datetime.now() - timedelta(hours=time_window_hours)
        
        # Calculate operating time (Execute state)
        operating_time = 0.0
        for i, state_change in enumerate(self.state_history):
            if state_change["timestamp"] < cutoff:
                continue
            
            if state_change["previous_state"] == "Execute" and state_change["duration_seconds"]:
                operating_time += state_change["duration_seconds"]
        
        # If currently in Execute state, add time since last state change
        if self.state_history and self.state_history[-1]["state"] == "Execute":
            last_change = self.state_history[-1]["timestamp"]
            operating_time += (datetime.now() - last_change).total_seconds()
        
        planned_time = time_window_hours * 3600
        availability = (operating_time / planned_time) * 100 if planned_time > 0 else 0.0
        
        logger.debug(
            "availability_calculated",
            asset_id=self.asset_id,
            operating_time=operating_time,
            planned_time=planned_time,
            availability=availability
        )
        
        return min(availability, 100.0)
    
    def calculate_performance(self, time_window_hours: float = 8) -> float:
        """
        Calculate performance percentage.
        
        Performance = (Total Parts × Ideal Cycle Time) / Operating Time
        
        Args:
            time_window_hours: Time window for calculation (default 8 hours)
            
        Returns:
            Performance as a percentage (0-100)
        """
        cutoff = datetime.now() - timedelta(hours=time_window_hours)
        
        # Calculate operating time (Execute state)
        operating_time = 0.0
        for i, state_change in enumerate(self.state_history):
            if state_change["timestamp"] < cutoff:
                continue
            
            if state_change["previous_state"] == "Execute" and state_change["duration_seconds"]:
                operating_time += state_change["duration_seconds"]
        
        # If currently in Execute state, add time since last state change
        if self.state_history and self.state_history[-1]["state"] == "Execute":
            last_change = self.state_history[-1]["timestamp"]
            operating_time += (datetime.now() - last_change).total_seconds()
        
        if operating_time == 0:
            return 0.0
        
        # Calculate performance
        total_parts = self.production_count
        ideal_time = total_parts * self.ideal_cycle_time
        performance = (ideal_time / operating_time) * 100 if operating_time > 0 else 0.0
        
        logger.debug(
            "performance_calculated",
            asset_id=self.asset_id,
            total_parts=total_parts,
            ideal_time=ideal_time,
            operating_time=operating_time,
            performance=performance
        )
        
        return min(performance, 100.0)
    
    def calculate_quality(self) -> float:
        """
        Calculate quality percentage.
        
        Quality = Good Parts / Total Parts
        
        Returns:
            Quality as a percentage (0-100)
        """
        if self.production_count == 0:
            return 0.0
        
        quality = (self.good_count / self.production_count) * 100
        
        logger.debug(
            "quality_calculated",
            asset_id=self.asset_id,
            good_count=self.good_count,
            total_count=self.production_count,
            quality=quality
        )
        
        return quality
    
    def calculate_oee(self, time_window_hours: float = 8) -> Dict[str, float]:
        """
        Calculate overall OEE.
        
        OEE = Availability × Performance × Quality
        
        Args:
            time_window_hours: Time window for calculation (default 8 hours)
            
        Returns:
            Dictionary with availability, performance, quality, and oee
        """
        availability = self.calculate_availability(time_window_hours)
        performance = self.calculate_performance(time_window_hours)
        quality = self.calculate_quality()
        
        oee = (availability / 100) * (performance / 100) * (quality / 100) * 100
        
        result = {
            "availability": round(availability, 2),
            "performance": round(performance, 2),
            "quality": round(quality, 2),
            "oee": round(oee, 2),
            "timestamp": datetime.now().isoformat()
        }
        
        logger.info(
            "oee_calculated",
            asset_id=self.asset_id,
            result=result
        )
        
        return result
    
    def get_state_distribution(self, time_window_hours: float = 8) -> Dict[str, float]:
        """
        Get distribution of time spent in each PackML state.
        
        Args:
            time_window_hours: Time window for analysis (default 8 hours)
            
        Returns:
            Dictionary mapping state to percentage of time
        """
        cutoff = datetime.now() - timedelta(hours=time_window_hours)
        
        state_durations = defaultdict(float)
        
        for state_change in self.state_history:
            if state_change["timestamp"] < cutoff:
                continue
            
            if state_change["duration_seconds"]:
                state_durations[state_change["previous_state"]] += state_change["duration_seconds"]
        
        # Add current state duration
        if self.state_history:
            last_change = self.state_history[-1]
            current_duration = (datetime.now() - last_change["timestamp"]).total_seconds()
            state_durations[last_change["state"]] += current_duration
        
        # Calculate percentages
        total_time = sum(state_durations.values())
        state_percentages = {
            state: (duration / total_time * 100) if total_time > 0 else 0.0
            for state, duration in state_durations.items()
        }
        
        return state_percentages
    
    def reset(self) -> None:
        """Reset all counters and history."""
        self.state_history.clear()
        self.production_count = 0
        self.good_count = 0
        
        logger.info("oee_calculator_reset", asset_id=self.asset_id)

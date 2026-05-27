"""Local Anomaly Detection Module for Edge Agent"""

from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
from collections import deque
import statistics
import structlog

logger = structlog.get_logger()


class AnomalyDetector:
    """
    Detect anomalies in telemetry data using statistical methods.
    
    Uses Z-score based anomaly detection for real-time anomaly detection.
    """
    
    def __init__(self, asset_id: str, window_size: int = 100, z_threshold: float = 3.0):
        self.asset_id = asset_id
        self.window_size = window_size
        self.z_threshold = z_threshold
        self.data_windows: Dict[str, deque] = {}
        self.anomalies: List[Dict[str, Any]] = []
    
    def add_telemetry(self, metric_name: str, value: float, timestamp: datetime) -> Optional[Dict[str, Any]]:
        """
        Add telemetry data and check for anomalies.
        
        Args:
            metric_name: Name of the metric (e.g., 'temp_nozzle')
            value: Metric value
            timestamp: When the value was recorded
            
        Returns:
            Anomaly data if detected, None otherwise
        """
        # Initialize window if needed
        if metric_name not in self.data_windows:
            self.data_windows[metric_name] = deque(maxlen=self.window_size)
        
        # Add value to window
        self.data_windows[metric_name].append({
            "value": value,
            "timestamp": timestamp
        })
        
        # Check for anomaly if we have enough data
        if len(self.data_windows[metric_name]) >= 20:  # Minimum samples
            anomaly = self._check_anomaly(metric_name, value, timestamp)
            if anomaly:
                self.anomalies.append(anomaly)
                # Keep only last 1000 anomalies
                if len(self.anomalies) > 1000:
                    self.anomalies = self.anomalies[-1000:]
                
                logger.warning(
                    "anomaly_detected",
                    asset_id=self.asset_id,
                    metric_name=metric_name,
                    value=value,
                    z_score=anomaly["z_score"]
                )
                
                return anomaly
        
        return None
    
    def _check_anomaly(
        self,
        metric_name: str,
        value: float,
        timestamp: datetime
    ) -> Optional[Dict[str, Any]]:
        """
        Check if value is anomalous using Z-score.
        
        Args:
            metric_name: Name of the metric
            value: Current value
            timestamp: Timestamp of value
            
        Returns:
            Anomaly data if anomalous, None otherwise
        """
        window = self.data_windows[metric_name]
        values = [item["value"] for item in window]
        
        # Calculate statistics
        mean = statistics.mean(values)
        stdev = statistics.stdev(values) if len(values) > 1 else 0.0
        
        # Skip if no variance
        if stdev == 0:
            return None
        
        # Calculate Z-score
        z_score = abs((value - mean) / stdev)
        
        # Check if anomalous
        if z_score > self.z_threshold:
            return {
                "asset_id": self.asset_id,
                "metric_name": metric_name,
                "value": value,
                "mean": mean,
                "stdev": stdev,
                "z_score": z_score,
                "threshold": self.z_threshold,
                "timestamp": timestamp.isoformat(),
                "severity": self._get_severity(z_score)
            }
        
        return None
    
    def _get_severity(self, z_score: float) -> str:
        """Determine severity based on Z-score."""
        if z_score > 5:
            return "critical"
        elif z_score > 4:
            return "high"
        elif z_score > 3:
            return "medium"
        else:
            return "low"
    
    def get_recent_anomalies(self, hours: int = 24) -> List[Dict[str, Any]]:
        """
        Get anomalies from the last N hours.
        
        Args:
            hours: Number of hours to look back
            
        Returns:
            List of recent anomalies
        """
        cutoff = datetime.now() - timedelta(hours=hours)
        
        return [
            anomaly for anomaly in self.anomalies
            if datetime.fromisoformat(anomaly["timestamp"]) > cutoff
        ]
    
    def get_anomaly_count(self, hours: int = 24) -> Dict[str, int]:
        """
        Get count of anomalies by severity in the last N hours.
        
        Args:
            hours: Number of hours to look back
            
        Returns:
            Dictionary mapping severity to count
        """
        recent_anomalies = self.get_recent_anomalies(hours)
        
        counts = {"critical": 0, "high": 0, "medium": 0, "low": 0}
        for anomaly in recent_anomalies:
            severity = anomaly["severity"]
            if severity in counts:
                counts[severity] += 1
        
        return counts
    
    def reset(self) -> None:
        """Reset all data windows and anomalies."""
        self.data_windows.clear()
        self.anomalies.clear()
        
        logger.info("anomaly_detector_reset", asset_id=self.asset_id)


class TrendAnalyzer:
    """
    Analyze trends in telemetry data.
    
    Uses moving averages and rate of change to identify trends.
    """
    
    def __init__(self, asset_id: str, window_size: int = 20):
        self.asset_id = asset_id
        self.window_size = window_size
        self.data_windows: Dict[str, deque] = {}
    
    def add_telemetry(self, metric_name: str, value: float, timestamp: datetime) -> Dict[str, Any]:
        """
        Add telemetry data and analyze trend.
        
        Args:
            metric_name: Name of the metric
            value: Metric value
            timestamp: When the value was recorded
            
        Returns:
            Trend analysis data
        """
        # Initialize window if needed
        if metric_name not in self.data_windows:
            self.data_windows[metric_name] = deque(maxlen=self.window_size)
        
        # Add value to window
        self.data_windows[metric_name].append({
            "value": value,
            "timestamp": timestamp
        })
        
        # Analyze trend if we have enough data
        if len(self.data_windows[metric_name]) >= 5:
            return self._analyze_trend(metric_name)
        
        return {
            "metric_name": metric_name,
            "trend": "insufficient_data",
            "current_value": value,
            "moving_average": value,
            "rate_of_change": 0.0
        }
    
    def _analyze_trend(self, metric_name: str) -> Dict[str, Any]:
        """Analyze trend for a metric."""
        window = self.data_windows[metric_name]
        values = [item["value"] for item in window]
        
        # Calculate moving average
        moving_average = statistics.mean(values)
        
        # Calculate rate of change (slope)
        if len(values) >= 2:
            rate_of_change = (values[-1] - values[0]) / len(values)
        else:
            rate_of_change = 0.0
        
        # Determine trend direction
        if abs(rate_of_change) < 0.01:
            trend = "stable"
        elif rate_of_change > 0:
            trend = "increasing"
        else:
            trend = "decreasing"
        
        return {
            "metric_name": metric_name,
            "trend": trend,
            "current_value": values[-1],
            "moving_average": moving_average,
            "rate_of_change": rate_of_change,
            "min_value": min(values),
            "max_value": max(values),
            "std_dev": statistics.stdev(values) if len(values) > 1 else 0.0
        }
    
    def get_all_trends(self) -> Dict[str, Dict[str, Any]]:
        """
        Get trends for all metrics.
        
        Returns:
            Dictionary mapping metric name to trend data
        """
        trends = {}
        for metric_name in self.data_windows:
            if len(self.data_windows[metric_name]) >= 5:
                trends[metric_name] = self._analyze_trend(metric_name)
        
        return trends
    
    def reset(self) -> None:
        """Reset all data windows."""
        self.data_windows.clear()
        
        logger.info("trend_analyzer_reset", asset_id=self.asset_id)

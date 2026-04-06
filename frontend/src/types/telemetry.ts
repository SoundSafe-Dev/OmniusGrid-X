export interface TelemetryPoint {
  timestamp: string;
  metricName: string;
  value: number;
  unit?: string;
  packmlState?: string;
  metadata?: Record<string, any>;
}

export interface LatestTelemetry {
  assetId: string;
  timestamp: string;
  metricName: string;
  value: number;
  unit?: string;
  packmlState?: string;
  metadata?: Record<string, any>;
}

export interface TelemetryHistoryRequest {
  assetId: string;
  metricName?: string;
  startTime?: string;
  endTime?: string;
  aggregation?: '1min' | '5min' | '1hour';
  skip?: number;
  limit?: number;
}

export interface AvailableMetrics {
  assetId: string;
  metrics: string[];
}

export interface TelemetryFilters {
  metricName?: string;
  startTime?: string;
  endTime?: string;
  aggregation?: '1min' | '5min' | '1hour';
}

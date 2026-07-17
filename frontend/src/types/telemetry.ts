export interface TelemetryPoint {
  timestamp: string;
  metricName: string;
  value: number;
  unit?: string;
  packmlState?: string;
  metadata?: Record<string, any>;
}

// Time-series pagination envelope (FS-89). No total (a count over a telemetry
// window is expensive); has_more + oldest/newest cursors instead. Fetch the next
// older page with end_time = meta.oldest.
export interface TelemetryHistoryMeta {
  count: number;
  skip: number;
  limit: number;
  hasMore: boolean;
  startTime?: string;
  endTime?: string;
  newest: string | null;
  oldest: string | null;
}

export interface TelemetryHistoryPage {
  items: TelemetryPoint[];
  meta: TelemetryHistoryMeta;
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

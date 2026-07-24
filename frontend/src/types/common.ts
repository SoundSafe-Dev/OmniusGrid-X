export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  skip: number;
  limit: number;
  hasMore: boolean;
}

export interface ApiError {
  status: number;
  message: string;
  details?: Record<string, string[]>;
}

export interface DashboardOverview {
  totalAssets: number;
  activeAssets: number;
  assetsByState: Record<string, number>;
  activeAlarms: number;
  criticalAlarms: number;
}

export interface OEEMetrics {
  assetId: string;
  assetName: string;
  timeRange: string;
  availability: number;
  performance: number;
  quality: number;
  oee: number;
  stateDurations: Record<string, number>;
  totalPlannedTimeSeconds: number;
}

/** Fleet-wide AVAILABILITY, not full OEE.
 *
 * The endpoint used to return availability under the name `oee` (performance and
 * quality were hardcoded to 1.0 server-side), so anything labelled "OEE" from
 * this shape was overstated. `availabilityOnly` is returned by the API to make
 * that explicit. For real three-factor OEE use the per-asset
 * `/dashboard/assets/{id}/oee`, which delegates to the OEE calculator.
 */
export interface FleetOEE {
  timeRange: string;
  assetCount: number;
  fleetAverageAvailability: number;
  availabilityOnly: boolean;
  assets: Array<{
    assetId: string;
    assetName: string;
    availability: number;
    availabilityOnly: boolean;
  }>;
}

export interface TimeRange {
  label: string;
  hours: number;
}

export const TIME_RANGES: TimeRange[] = [
  { label: 'Last 1 Hour', hours: 1 },
  { label: 'Last 6 Hours', hours: 6 },
  { label: 'Last 24 Hours', hours: 24 },
  { label: 'Last 7 Days', hours: 168 },
];

export interface WebSocketMessage {
  type:
    // server -> client data events
    | 'telemetry' | 'alarm' | 'state_change' | 'system_status' | 'engine_decision'
    | 'connection_status' | 'command_status'
    // control / heartbeat / subscription protocol (see api/websocket.ts, backend/app/api/websocket.py)
    | 'ping' | 'pong' | 'subscribe' | 'unsubscribe' | 'subscription_updated' | 'unsubscribed' | 'error';
  timestamp: string;
  payload: any;
}

export type Theme = 'dark' | 'light';

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
  /** Whether each factor was MEASURED, or stood in for.
   *
   * `quality` reads 1.0 when an asset has no part counters and `performance` reads 1.0
   * without an ideal cycle time. 1.0 is the neutral multiplier for OEE, which is the
   * right arithmetic and the wrong thing to print: "100%" is a measurement, and this
   * is the absence of one. The server has sent these flags since FS-234 — its own
   * comment says a consumer "should render '—' rather than '100%' when this is false"
   * — and nothing read them, so every unmeasured factor showed as perfect.
   *
   * OEE inherits it: with either factor unmeasured the product is an upper bound, not
   * a result.
   */
  qualityMeasured?: boolean;
  performanceMeasured?: boolean;
  totalParts?: number;
  goodParts?: number;
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
  /** `null` when the fleet has no assets to average. The API stopped reporting 0 for
   *  an unmeasured fleet — 0% availability reads as a fleet-wide outage — so callers
   *  must render the absence rather than coercing it back into a number. */
  fleetAverageAvailability: number | null;
  /** How many assets the average rests on. */
  assetsMeasured?: number;
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

// Types for the Error Triage admin feature. Mirrors the response models in
// backend/app/api/error_tracking.py.

export type ErrorStatus = 'open' | 'acknowledged' | 'resolved';
export type ErrorRange = '24h' | '7d' | '30d' | 'all';
export type ErrorStatusFilter = ErrorStatus | 'active' | 'all';
export type ErrorSort = 'count' | 'last_seen' | 'first_seen';
export type SortOrder = 'asc' | 'desc';

export interface ErrorEventSummary {
  fingerprint: string;
  exception_type: string;
  route: string;
  method: string;
  status_code: number;
  status: ErrorStatus;
  total_count: number;
  count_in_range: number;
  regression_count: number;
  first_seen: string;
  last_seen: string;
}

export interface ErrorListResponse {
  items: ErrorEventSummary[];
  total: number;
}

export interface HourlyPoint {
  hour: string;
  count: number;
}

export interface TopError {
  fingerprint: string;
  exception_type: string;
  route: string;
  count_in_range: number;
}

export interface ErrorSummary {
  range: string;
  open_count: number;
  acknowledged_count: number;
  events_in_range: number;
  regressions_in_range: number;
  top_error: TopError | null;
  series: HourlyPoint[];
}

export interface ErrorEventDetail {
  fingerprint: string;
  exception_type: string;
  route: string;
  method: string;
  status_code: number;
  status: ErrorStatus;
  total_count: number;
  count_in_range: number;
  regression_count: number;
  message_sample: string | null;
  traceback_sample: string | null;
  organization_id: string | null;
  status_changed_by: string | null;
  status_changed_at: string | null;
  first_seen: string;
  last_seen: string;
  series: HourlyPoint[];
}

export interface ErrorListParams {
  status?: ErrorStatusFilter;
  q?: string;
  sort?: ErrorSort;
  order?: SortOrder;
  range?: ErrorRange;
  limit?: number;
  offset?: number;
}

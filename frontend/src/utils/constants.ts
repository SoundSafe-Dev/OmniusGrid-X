import { AlarmSeverity, PackMLState } from '../types';

export const STATUS_COLORS: Record<AlarmSeverity | PackMLState | 'default', string> = {
  // Alarm severities
  critical: 'bg-status-alarm text-white',
  high: 'bg-status-warning text-opsgrid-bg',
  medium: 'bg-packml-held text-opsgrid-bg',
  low: 'bg-opsgrid-text-secondary text-opsgrid-bg',
  // `text-opsgrid-bg`, not `text-white`. `bg-opsgrid-primary` is `var(--color-primary)`,
  // which is #fafafa in the DEFAULT dark theme — so white-on-white rendered every
  // `info` badge in the app as a blank pill: the ERP type column, the admin user
  // roles, the NLP domain/priority chips, the fleet vehicle count. Legible in light
  // theme only, which is why it survived. Every other entry here already pairs a
  // theme-variable background with `text-opsgrid-bg` for exactly this reason.
  info: 'bg-opsgrid-primary text-opsgrid-bg',

  // PackML states
  Idle: 'bg-packml-idle text-white',
  Starting: 'bg-packml-starting text-opsgrid-bg',
  Execute: 'bg-packml-execute text-white',
  Held: 'bg-packml-held text-opsgrid-bg',
  Suspended: 'bg-packml-suspended text-white',
  Aborted: 'bg-packml-aborted text-white',
  Stopped: 'bg-packml-stopped text-white',
  Completing: 'bg-packml-starting text-opsgrid-bg',
  Complete: 'bg-packml-execute text-white',
  Clearing: 'bg-packml-starting text-opsgrid-bg',
  Resetting: 'bg-packml-starting text-opsgrid-bg',
  Unholding: 'bg-packml-held text-opsgrid-bg',
  Suspending: 'bg-packml-suspended text-white',
  Aborting: 'bg-packml-aborted text-white',
  Stopping: 'bg-packml-stopped text-white',

  default: 'bg-opsgrid-text-secondary text-opsgrid-bg',
};

export const STATUS_TEXT_COLORS: Record<AlarmSeverity | PackMLState | 'default', string> = {
  critical: 'text-status-alarm',
  high: 'text-status-warning',
  medium: 'text-packml-held',
  low: 'text-opsgrid-text-secondary',
  info: 'text-opsgrid-primary',

  Idle: 'text-packml-idle',
  Starting: 'text-packml-starting',
  Execute: 'text-packml-execute',
  Held: 'text-packml-held',
  Suspended: 'text-packml-suspended',
  Aborted: 'text-packml-aborted',
  Stopped: 'text-packml-stopped',
  Completing: 'text-packml-starting',
  Complete: 'text-packml-execute',
  Clearing: 'text-packml-starting',
  Resetting: 'text-packml-starting',
  Unholding: 'text-packml-held',
  Suspending: 'text-packml-suspended',
  Aborting: 'text-packml-aborted',
  Stopping: 'text-packml-stopped',

  default: 'text-opsgrid-text-secondary',
};

export const CHART_COLORS = [
  '#0ea5e9', // Sky 500
  '#22c55e', // Green 500
  '#eab308', // Yellow 500
  '#ef4444', // Red 500
  '#6366f1', // Indigo 500
  '#f97316', // Orange 500
  '#8b5cf6', // Violet 500
  '#ec4899', // Pink 500
];

export const DEFAULT_PAGE_SIZE = 20;
export const MAX_PAGE_SIZE = 100;

// FS-900. Four pages fetch "the whole fleet" for a client-side aggregate (a KPI tile,
// an org tree, a chart) rather than a paginated table, and all four used a bare `500`
// with no shared name and no link to what actually bounds it: the backend's
// `GET /api/v1/assets` ceiling is `le=1000` (app/api/assets.py). MAX_PAGE_SIZE (100) is
// the wrong constant for this — clamping a fleet-overview fetch to it would make
// FS-967's truncation bug worse, not fix it, by lowering the cutoff from 500 to 100 assets.
//
// 500 is kept rather than raised to the 1000 ceiling: raising it does not fix FS-967 (a
// large enough fleet still exceeds any fixed number silently), and moving the actual fix
// to real pagination or a server-computed total is that item's job, not this constant's.
// Named so every call site says the same thing about why, instead of four copies of a
// number nobody could trace.
export const FLEET_OVERVIEW_FETCH_LIMIT = 500;

export const REFRESH_INTERVALS = {
  dashboard: 30000, // 30 seconds
  telemetry: 5000, // 5 seconds
  alarms: 10000, // 10 seconds
  oee: 60000, // 1 minute
  engines: 30000, // 30 seconds
};

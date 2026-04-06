import { AlarmSeverity, PackMLState } from '../types';

export const STATUS_COLORS: Record<AlarmSeverity | PackMLState | 'default', string> = {
  // Alarm severities
  critical: 'bg-status-alarm text-white',
  high: 'bg-status-warning text-opsgrid-bg',
  medium: 'bg-packml-held text-opsgrid-bg',
  low: 'bg-opsgrid-text-secondary text-opsgrid-bg',
  info: 'bg-opsgrid-primary text-white',

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

export const REFRESH_INTERVALS = {
  dashboard: 30000, // 30 seconds
  telemetry: 5000, // 5 seconds
  alarms: 10000, // 10 seconds
  oee: 60000, // 1 minute
  engines: 30000, // 30 seconds
};

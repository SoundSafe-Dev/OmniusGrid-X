export type AlarmSeverity = 'critical' | 'high' | 'medium' | 'low' | 'info';

export interface Alarm {
  id: string;
  assetId: string;
  assetName?: string;
  alarmCode: string;
  message: string;
  severity: AlarmSeverity;
  isActive: boolean;
  isAcknowledged: boolean;
  occurredAt: string;
  clearedAt?: string;
  acknowledgedAt?: string;
  acknowledgedBy?: string;
  acknowledgedComment?: string;
  metadata?: Record<string, any>;
  /* `createdAt` and `updatedAt` are GONE (FS-436). The `alarms` table has neither column —
   * an alarm's timeline is `occurredAt`, `acknowledgedAt` and `clearedAt` — so nothing
   * could ever have sent them. Both were declared REQUIRED, which meant TypeScript
   * entitled every consumer to `new Date(alarm.createdAt)` without a guard, on a value
   * that is `undefined` at runtime. Nothing read them, which is the only reason this was
   * a trap for the next page rather than a crash on the current one. */
}

export interface AlarmAcknowledge {
  comment?: string;
}

export interface ActiveAlarmsResponse {
  count: number;
  bySeverity: {
    critical: number;
    high: number;
    medium: number;
    low: number;
  };
  alarms: Alarm[];
}

export interface AlarmFilters {
  assetId?: string;
  isActive?: boolean;
  severity?: AlarmSeverity;
  acknowledged?: boolean;
  startTime?: string;
  endTime?: string;
  // FS-127: page through the FS-82 envelope.
  skip?: number;
  limit?: number;
}

// Alarm rules (FS-218/219). Operator-defined thresholds evaluated server-side
// against incoming telemetry — before these existed, severity was whatever the
// edge agent sent and nothing evaluated telemetry at all.
export type AlarmComparator = 'gt' | 'gte' | 'lt' | 'lte' | 'eq' | 'ne';
// AlarmSeverity is declared at the top of this file and reused here deliberately:
// a rule must not be able to request a severity that an Alarm cannot hold.

export interface AlarmRule {
  id: string;
  organizationId: string;
  name: string;
  description?: string | null;
  metricName: string;
  comparator: AlarmComparator;
  threshold: number;
  /** Breach must persist this long before firing. 0 = fire on first sample. */
  durationSeconds: number;
  /** Clear band, in the metric's units, to stop flapping on the threshold. */
  hysteresis: number;
  severity: AlarmSeverity;
  alarmCode: string;
  messageTemplate?: string | null;
  /** Targeting: all three null = every asset in the organization. */
  assetId?: string | null;
  assetTypeId?: string | null;
  workcellId?: string | null;
  isEnabled: boolean;
  createdBy?: string | null;
  createdAt: string;
  updatedAt: string;
}

export type AlarmRuleCreate = Omit<
  AlarmRule,
  'id' | 'organizationId' | 'createdBy' | 'createdAt' | 'updatedAt'
>;

export type AlarmRuleUpdate = Partial<AlarmRuleCreate>;

export interface AlarmRuleFilters {
  metricName?: string;
  severity?: AlarmSeverity;
  isEnabled?: boolean;
  skip?: number;
  limit?: number;
}

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
  createdAt: string;
  updatedAt: string;
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
}

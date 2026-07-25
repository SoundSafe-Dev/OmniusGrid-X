/**
 * Fleet-aggregate dashboard endpoints (FS-192).
 *
 * These sit under `/api/v1/dashboard`, which is already registered in the
 * transform registry (see api/assets.ts), so responses arrive camelCased —
 * `availability_only` -> `availabilityOnly`, `health_score` -> `healthScore`.
 * Severity names are object KEYS in the alarm series and stay as the backend
 * spells them (`critical`, `high`, …), which is why the series is typed as an
 * index signature rather than a fixed shape.
 */
import { api } from './client';
import { USE_MOCK } from './mockMode';
import { mockDashboardAnalytics } from './mocks/dashboardAnalytics';

export type BucketName = '5min' | '15min' | '1hour' | '6hour' | '1day';

export interface AlarmTrendPoint {
  timestamp: string;
  total: number;
  [severity: string]: string | number;
}

export interface AlarmTrend {
  bucket: BucketName;
  hours: number;
  severities: string[];
  series: AlarmTrendPoint[];
}

export interface ThroughputPoint {
  timestamp: string;
  totalParts: number;
  goodParts: number;
}

export interface Throughput {
  bucket: BucketName;
  hours: number;
  series: ThroughputPoint[];
  totals: {
    totalParts: number;
    goodParts: number;
    /** null when no part counters were reported — NOT 0% quality. */
    qualityPct: number | null;
  };
}

export interface AvailabilityPoint {
  timestamp: string;
  availabilityPct: number | null;
}

export interface AvailabilityTrend {
  bucket: BucketName;
  hours: number;
  /** Always true: this is run-time/elapsed, not three-factor OEE. */
  availabilityOnly: boolean;
  assetCount: number;
  series: AvailabilityPoint[];
  averageAvailabilityPct: number;
}

export interface HealthBand {
  band: 'critical' | 'at_risk' | 'fair' | 'healthy';
  min: number;
  max: number;
  count: number;
}

export interface HealthDistribution {
  hours: number;
  assetCount: number;
  bands: HealthBand[];
  averageHealth: number | null;
}

export interface AtRiskAsset {
  assetId: string;
  assetName: string;
  healthScore: number;
  confidence: number;
  availabilityPct: number;
  alarmRatePerHour: number;
  drivers: Array<{ factor: string; impact: number; detail: string }>;
}

export interface AssetsAtRisk {
  hours: number;
  assetCount: number;
  items: AtRiskAsset[];
}

export const dashboardAnalyticsApi = {
  getAlarmTrend: async (hours = 24, bucket: BucketName = '1hour'): Promise<AlarmTrend> => {
    if (USE_MOCK) return mockDashboardAnalytics.alarmTrend(hours, bucket);
    const { data } = await api.get<AlarmTrend>('/api/v1/dashboard/alarms/trend', {
      params: { hours, bucket },
    });
    return data;
  },

  getThroughput: async (hours = 24, bucket: BucketName = '1hour'): Promise<Throughput> => {
    if (USE_MOCK) return mockDashboardAnalytics.throughput(hours, bucket);
    const { data } = await api.get<Throughput>('/api/v1/dashboard/throughput', {
      params: { hours, bucket },
    });
    return data;
  },

  getAvailabilityTrend: async (
    hours = 24,
    bucket: BucketName = '1hour',
  ): Promise<AvailabilityTrend> => {
    if (USE_MOCK) return mockDashboardAnalytics.availabilityTrend(hours, bucket);
    const { data } = await api.get<AvailabilityTrend>('/api/v1/dashboard/oee/trend', {
      params: { hours, bucket },
    });
    return data;
  },

  getHealthDistribution: async (hours = 24): Promise<HealthDistribution> => {
    if (USE_MOCK) return mockDashboardAnalytics.healthDistribution(hours);
    const { data } = await api.get<HealthDistribution>(
      '/api/v1/dashboard/health/distribution',
      { params: { hours } },
    );
    return data;
  },

  getAssetsAtRisk: async (hours = 24, limit = 5): Promise<AssetsAtRisk> => {
    if (USE_MOCK) return mockDashboardAnalytics.assetsAtRisk(hours, limit);
    const { data } = await api.get<AssetsAtRisk>('/api/v1/dashboard/assets/at-risk', {
      params: { hours, limit },
    });
    return data;
  },
};

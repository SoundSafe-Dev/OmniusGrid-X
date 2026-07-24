/**
 * Mock fixtures for the fleet-aggregate dashboard endpoints.
 *
 * Series are generated across the requested window so the mock exercises the
 * same dense-series shape the API returns (every bucket present, gaps as zeros
 * rather than missing points) — a mock that returned only non-empty buckets
 * would hide chart bugs that appear on sparse real data.
 */
import type {
  AlarmTrend,
  AssetsAtRisk,
  AvailabilityTrend,
  BucketName,
  HealthDistribution,
  Throughput,
} from '../dashboardAnalytics';

const BUCKET_SECONDS: Record<BucketName, number> = {
  '5min': 300,
  '15min': 900,
  '1hour': 3600,
  '6hour': 21600,
  '1day': 86400,
};

/** Epoch-aligned bucket starts across the window, oldest first (matches the API). */
function timestamps(hours: number, bucket: BucketName): string[] {
  const seconds = BUCKET_SECONDS[bucket];
  const now = Math.floor(Date.now() / 1000);
  const end = now - (now % seconds);
  const start = end - hours * 3600;
  const out: string[] = [];
  for (let t = start - (start % seconds); t <= end; t += seconds) {
    out.push(new Date(t * 1000).toISOString());
  }
  return out;
}

/** Deterministic pseudo-random so mock charts don't reshuffle every render. */
function wave(i: number, base: number, amplitude: number): number {
  return Math.max(0, Math.round(base + Math.sin(i / 2.5) * amplitude));
}

export const mockDashboardAnalytics = {
  alarmTrend: (hours: number, bucket: BucketName): AlarmTrend => {
    const severities = ['critical', 'high', 'medium', 'low'];
    const series = timestamps(hours, bucket).map((timestamp, i) => {
      const critical = i % 7 === 0 ? 1 : 0;
      const high = wave(i, 1, 1);
      const medium = wave(i, 2, 2);
      const low = wave(i, 3, 2);
      return {
        timestamp,
        critical,
        high,
        medium,
        low,
        total: critical + high + medium + low,
      };
    });
    return { bucket, hours, severities, series };
  },

  throughput: (hours: number, bucket: BucketName): Throughput => {
    const series = timestamps(hours, bucket).map((timestamp, i) => {
      const totalParts = wave(i, 120, 35);
      return { timestamp, totalParts, goodParts: Math.round(totalParts * 0.94) };
    });
    const totalParts = series.reduce((a, p) => a + p.totalParts, 0);
    const goodParts = series.reduce((a, p) => a + p.goodParts, 0);
    return {
      bucket,
      hours,
      series,
      totals: {
        totalParts,
        goodParts,
        qualityPct: totalParts > 0 ? Math.round((goodParts / totalParts) * 1000) / 10 : null,
      },
    };
  },

  availabilityTrend: (hours: number, bucket: BucketName): AvailabilityTrend => {
    const series = timestamps(hours, bucket).map((timestamp, i) => ({
      timestamp,
      availabilityPct: Math.min(100, wave(i, 78, 12)),
    }));
    const measured = series.map((p) => p.availabilityPct ?? 0);
    return {
      bucket,
      hours,
      availabilityOnly: true,
      assetCount: 8,
      series,
      averageAvailabilityPct:
        Math.round((measured.reduce((a, v) => a + v, 0) / measured.length) * 10) / 10,
    };
  },

  healthDistribution: (hours: number): HealthDistribution => ({
    hours,
    assetCount: 8,
    bands: [
      { band: 'critical', min: 0, max: 40, count: 1 },
      { band: 'at_risk', min: 40, max: 60, count: 2 },
      { band: 'fair', min: 60, max: 80, count: 3 },
      { band: 'healthy', min: 80, max: 100.01, count: 2 },
    ],
    averageHealth: 67.4,
  }),

  assetsAtRisk: (hours: number, limit: number): AssetsAtRisk => {
    const items = [
      {
        assetId: 'asset-5',
        assetName: 'CNC Mill #1',
        healthScore: 38.5,
        confidence: 0.2,
        availabilityPct: 62.1,
        alarmRatePerHour: 1.4,
        drivers: [{ factor: 'alarm_rate', impact: -7, detail: '1.4 alarms/hr' }],
      },
      {
        assetId: 'asset-8',
        assetName: 'Vibration Sensor — CNC Spindle',
        healthScore: 46.2,
        confidence: 0.2,
        availabilityPct: 55.0,
        alarmRatePerHour: 0.8,
        drivers: [{ factor: 'low_availability', impact: -4.5, detail: 'availability 55.0%' }],
      },
      {
        assetId: 'asset-3',
        assetName: 'Printer #3 (QIDI X-Max 3)',
        healthScore: 58.9,
        confidence: 0.2,
        availabilityPct: 71.3,
        alarmRatePerHour: 0.3,
        drivers: [],
      },
    ];
    return { hours, assetCount: items.length, items: items.slice(0, limit) };
  },
};

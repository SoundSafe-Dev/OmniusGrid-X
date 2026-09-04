import { api } from './client';
import { mockApi } from './mockApi';
import { TelemetryPoint, TelemetryHistoryPage, LatestTelemetry, AvailableMetrics, TelemetryFilters } from '../types';

import { USE_MOCK } from './mockMode';
import { registerTransform } from './transformRegistry';

// FS-61: casing handled by the axios seam — no per-call toCamel/toSnake.
registerTransform('/api/v1/telemetry');

export const telemetryApi = {
  getLatest: async (assetId: string, metricName?: string): Promise<LatestTelemetry | Record<string, LatestTelemetry>> => {
    if (USE_MOCK) {
      const mockTelemetry = await mockApi.getLatestTelemetry(assetId);
      
      if (metricName) {
        // Return single metric in LatestTelemetry format
        const latestMetric = mockTelemetry[metricName];
        return {
          assetId,
          timestamp: latestMetric?.timestamp || new Date().toISOString(),
          metricName: latestMetric?.metricName || metricName,
          value: latestMetric?.value || 0,
          unit: latestMetric?.unit,
          packmlState: 'Execute',
          metadata: {}
        };
      } else {
        // Return all metrics as a record
        const allTelemetry: Record<string, LatestTelemetry> = {};
        Object.entries(mockTelemetry).forEach(([key, telemetry]) => {
          allTelemetry[key] = {
            assetId,
            timestamp: telemetry.timestamp,
            metricName: telemetry.metricName,
            value: telemetry.value,
            unit: telemetry.unit,
            packmlState: 'Execute',
            metadata: {}
          };
        });
        return allTelemetry;
      }
    }
    const response = await api.get<LatestTelemetry>(`/api/v1/telemetry/${assetId}/latest`, {
      params: metricName ? { metric_name: metricName } : undefined,
    });
    return response.data;
  },

  getHistory: async (assetId: string, filters?: TelemetryFilters): Promise<TelemetryPoint[]> => {
    if (USE_MOCK) {
      // Synthesize a demo series over the last ~2h from the latest values.
      const latest = await mockApi.getLatestTelemetry(assetId);
      const metrics = filters?.metricName
        ? [filters.metricName]
        : Object.keys(latest);
      const points = 60;
      const now = Date.now();
      const out: TelemetryPoint[] = [];
      metrics.forEach((m) => {
        const base = latest[m]?.value ?? 50;
        const unit = latest[m]?.unit;
        for (let i = points - 1; i >= 0; i--) {
          const wobble = base * 0.08 * Math.sin(i / 5) + (base * 0.03 * (i % 3 - 1));
          out.push({
            timestamp: new Date(now - i * 120_000).toISOString(),
            metricName: m,
            value: Math.round((base + wobble) * 100) / 100,
            unit,
          });
        }
      });
      return out;
    }
    const params: Record<string, any> = {};
    if (filters?.metricName) params.metric_name = filters.metricName;
    if (filters?.startTime) params.start_time = filters.startTime;
    if (filters?.endTime) params.end_time = filters.endTime;
    if (filters?.aggregation) params.aggregation = filters.aggregation;

    // Backend now returns a {items, meta} time-series envelope (FS-89). getHistory
    // stays a plain point array for existing chart consumers; use getHistoryPage
    // when you need the has_more / cursor metadata to page through a large range.
    // Typed as the real envelope (not a narrowed `{ items }` literal) since FS-908
    // gave the route a declared response_model -- the actual JSON always carries
    // `meta` alongside `items`, and typing only the field this call reads is an
    // accurate-but-incomplete assertion the shape guard can no longer distinguish
    // from a genuine array/envelope mismatch.
    const response = await api.get<TelemetryHistoryPage>(`/api/v1/telemetry/${assetId}/history`, { params });
    return response.data.items;
  },

  getHistoryPage: async (
    assetId: string,
    filters?: TelemetryFilters,
  ): Promise<TelemetryHistoryPage> => {
    if (USE_MOCK) {
      const items = await telemetryApi.getHistory(assetId, filters);
      return {
        items,
        meta: {
          count: items.length,
          skip: 0,
          limit: items.length,
          hasMore: false,
          newest: items[0]?.timestamp ?? null,
          oldest: items[items.length - 1]?.timestamp ?? null,
        },
      };
    }
    const params: Record<string, any> = {};
    if (filters?.metricName) params.metric_name = filters.metricName;
    if (filters?.startTime) params.start_time = filters.startTime;
    if (filters?.endTime) params.end_time = filters.endTime;
    if (filters?.aggregation) params.aggregation = filters.aggregation;
    const response = await api.get<TelemetryHistoryPage>(
      `/api/v1/telemetry/${assetId}/history`,
      { params },
    );
    return response.data;
  },

  getAvailableMetrics: async (assetId: string): Promise<AvailableMetrics> => {
    if (USE_MOCK) {
      const latest = await mockApi.getLatestTelemetry(assetId);
      return { assetId, metrics: Object.keys(latest) };
    }
    const response = await api.get<AvailableMetrics>(`/api/v1/telemetry/${assetId}/metrics`);
    return response.data;
  },
};

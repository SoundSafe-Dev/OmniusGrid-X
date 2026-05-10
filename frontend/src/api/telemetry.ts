import { api } from './client';
import { mockApi } from './mockApi';
import { TelemetryPoint, LatestTelemetry, AvailableMetrics, TelemetryFilters } from '../types';

const USE_MOCK = true; // Set to false to use real backend

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
    const params: Record<string, any> = {};
    if (filters?.metricName) params.metric_name = filters.metricName;
    if (filters?.startTime) params.start_time = filters.startTime;
    if (filters?.endTime) params.end_time = filters.endTime;
    if (filters?.aggregation) params.aggregation = filters.aggregation;

    const response = await api.get<TelemetryPoint[]>(`/api/v1/telemetry/${assetId}/history`, { params });
    return response.data;
  },

  getAvailableMetrics: async (assetId: string): Promise<AvailableMetrics> => {
    const response = await api.get<AvailableMetrics>(`/api/v1/telemetry/${assetId}/metrics`);
    return response.data;
  },
};

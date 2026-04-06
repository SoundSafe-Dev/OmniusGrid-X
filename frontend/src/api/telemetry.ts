import { api } from './client';
import { TelemetryPoint, LatestTelemetry, AvailableMetrics, TelemetryFilters } from '../types';

export const telemetryApi = {
  getLatest: async (assetId: string, metricName?: string): Promise<LatestTelemetry> => {
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

import { useQuery, UseQueryOptions } from '@tanstack/react-query';
import { telemetryApi } from '../api';
import {
  TelemetryPoint,
  LatestTelemetry,
  AvailableMetrics,
  TelemetryFilters,
} from '../types';

const TELEMETRY_QUERY_KEY = 'telemetry';

export function useLatestTelemetry(assetId: string, metricName?: string) {
  // Without a metricName the API returns a record of all metrics.
  return useQuery<LatestTelemetry | Record<string, LatestTelemetry>, Error>({
    queryKey: [TELEMETRY_QUERY_KEY, 'latest', assetId, metricName],
    queryFn: () => telemetryApi.getLatest(assetId, metricName),
    refetchInterval: 5000, // Refresh every 5 seconds
    enabled: !!assetId,
  });
}

export function useTelemetryHistory(
  assetId: string,
  filters?: TelemetryFilters,
  options?: UseQueryOptions<TelemetryPoint[], Error>
) {
  return useQuery<TelemetryPoint[], Error>({
    queryKey: [TELEMETRY_QUERY_KEY, 'history', assetId, filters],
    queryFn: () => telemetryApi.getHistory(assetId, filters),
    enabled: !!assetId,
    ...options,
  });
}

export function useAvailableMetrics(assetId: string) {
  return useQuery<AvailableMetrics, Error>({
    queryKey: [TELEMETRY_QUERY_KEY, 'metrics', assetId],
    queryFn: () => telemetryApi.getAvailableMetrics(assetId),
    enabled: !!assetId,
  });
}

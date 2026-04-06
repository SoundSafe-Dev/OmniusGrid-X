import { useQuery, useMutation, useQueryClient, UseQueryOptions } from 'react-query';
import { telemetryApi } from '../api';
import {
  TelemetryPoint,
  LatestTelemetry,
  AvailableMetrics,
  TelemetryFilters,
} from '../types';

const TELEMETRY_QUERY_KEY = 'telemetry';

export function useLatestTelemetry(assetId: string, metricName?: string) {
  return useQuery<LatestTelemetry, Error>(
    [TELEMETRY_QUERY_KEY, 'latest', assetId, metricName],
    () => telemetryApi.getLatest(assetId, metricName),
    {
      refetchInterval: 5000, // Refresh every 5 seconds
      enabled: !!assetId,
    }
  );
}

export function useTelemetryHistory(
  assetId: string,
  filters?: TelemetryFilters,
  options?: UseQueryOptions<TelemetryPoint[], Error>
) {
  return useQuery<TelemetryPoint[], Error>(
    [TELEMETRY_QUERY_KEY, 'history', assetId, filters],
    () => telemetryApi.getHistory(assetId, filters),
    {
      enabled: !!assetId,
      ...options,
    }
  );
}

export function useAvailableMetrics(assetId: string) {
  return useQuery<AvailableMetrics, Error>(
    [TELEMETRY_QUERY_KEY, 'metrics', assetId],
    () => telemetryApi.getAvailableMetrics(assetId),
    {
      enabled: !!assetId,
    }
  );
}

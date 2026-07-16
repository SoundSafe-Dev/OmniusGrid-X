import { useQuery, useMutation, useQueryClient, UseQueryOptions } from '@tanstack/react-query';
import { alarmsApi } from '../api';
import { Alarm, AlarmFilters, ActiveAlarmsResponse, PaginatedResponse } from '../types';

const ALARMS_QUERY_KEY = 'alarms';

export function useAlarms(filters?: AlarmFilters, options?: UseQueryOptions<PaginatedResponse<Alarm>, Error>) {
  return useQuery<PaginatedResponse<Alarm>, Error>({
    queryKey: [ALARMS_QUERY_KEY, 'list', filters],
    queryFn: () => alarmsApi.list(filters),
    ...options,
  });
}

export function useActiveAlarms(organizationId?: string, severity?: string) {
  return useQuery<ActiveAlarmsResponse, Error>({
    queryKey: [ALARMS_QUERY_KEY, 'active', organizationId, severity],
    queryFn: () => alarmsApi.getActive(organizationId, severity),
    refetchInterval: 10000, // Refresh every 10 seconds
  });
}

export function useAlarm(alarmId: string) {
  return useQuery<Alarm, Error>({
    queryKey: [ALARMS_QUERY_KEY, 'detail', alarmId],
    queryFn: () => alarmsApi.get(alarmId),
    enabled: !!alarmId,
  });
}

export function useAcknowledgeAlarm() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ alarmId, comment }: { alarmId: string; comment?: string }) =>
      alarmsApi.acknowledge(alarmId, { comment }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: [ALARMS_QUERY_KEY] });
    },
  });
}

export function useClearAlarm() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (alarmId: string) => alarmsApi.clear(alarmId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: [ALARMS_QUERY_KEY] });
    },
  });
}

export function useAcknowledgeAllAlarms() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (params?: { assetId?: string; severity?: string }) => alarmsApi.acknowledgeAll(params),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: [ALARMS_QUERY_KEY] });
    },
  });
}

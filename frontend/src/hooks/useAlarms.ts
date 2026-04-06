import { useQuery, useMutation, useQueryClient, UseQueryOptions } from 'react-query';
import { alarmsApi } from '../api';
import { Alarm, AlarmFilters, ActiveAlarmsResponse, PaginatedResponse } from '../types';

const ALARMS_QUERY_KEY = 'alarms';

export function useAlarms(filters?: AlarmFilters, options?: UseQueryOptions<PaginatedResponse<Alarm>, Error>) {
  return useQuery<PaginatedResponse<Alarm>, Error>(
    [ALARMS_QUERY_KEY, 'list', filters],
    () => alarmsApi.list(filters),
    options
  );
}

export function useActiveAlarms(organizationId?: string, severity?: string) {
  return useQuery<ActiveAlarmsResponse, Error>(
    [ALARMS_QUERY_KEY, 'active', organizationId, severity],
    () => alarmsApi.getActive(organizationId, severity),
    {
      refetchInterval: 10000, // Refresh every 10 seconds
    }
  );
}

export function useAlarm(alarmId: string) {
  return useQuery<Alarm, Error>(
    [ALARMS_QUERY_KEY, 'detail', alarmId],
    () => alarmsApi.get(alarmId),
    {
      enabled: !!alarmId,
    }
  );
}

export function useAcknowledgeAlarm() {
  const queryClient = useQueryClient();

  return useMutation(
    ({ alarmId, comment }: { alarmId: string; comment?: string }) =>
      alarmsApi.acknowledge(alarmId, { comment }),
    {
      onSuccess: () => {
        queryClient.invalidateQueries([ALARMS_QUERY_KEY]);
      },
    }
  );
}

export function useClearAlarm() {
  const queryClient = useQueryClient();

  return useMutation((alarmId: string) => alarmsApi.clear(alarmId), {
    onSuccess: () => {
      queryClient.invalidateQueries([ALARMS_QUERY_KEY]);
    },
  });
}

export function useAcknowledgeAllAlarms() {
  const queryClient = useQueryClient();

  return useMutation(
    (params?: { assetId?: string; severity?: string }) => alarmsApi.acknowledgeAll(params),
    {
      onSuccess: () => {
        queryClient.invalidateQueries([ALARMS_QUERY_KEY]);
      },
    }
  );
}

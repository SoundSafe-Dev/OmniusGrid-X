import { api } from './client';
import { mockApi } from './mockApi';
import { USE_MOCK } from './mockMode';
import { Alarm, AlarmFilters, ActiveAlarmsResponse, AlarmAcknowledge, PaginatedResponse } from '../types';

export const alarmsApi = {
  list: async (filters?: AlarmFilters): Promise<PaginatedResponse<Alarm>> => {
    if (USE_MOCK) {
      const alarms = await mockApi.getAlarms();
      return {
        items: alarms.items,
        total: alarms.total,
        skip: 0,
        limit: alarms.total,
        hasMore: false,
      };
    }
    const params: Record<string, any> = {};
    if (filters?.assetId) params.asset_id = filters.assetId;
    if (filters?.isActive !== undefined) params.is_active = filters.isActive;
    if (filters?.severity) params.severity = filters.severity;
    if (filters?.acknowledged !== undefined) params.acknowledged = filters.acknowledged;
    if (filters?.startTime) params.start_time = filters.startTime;
    if (filters?.endTime) params.end_time = filters.endTime;

    const response = await api.get<Alarm[]>('/api/v1/alarms/', { params });
    return {
      items: response.data,
      total: response.data.length,
      skip: 0,
      limit: response.data.length,
      hasMore: false,
    };
  },

  getActive: async (organizationId?: string, severity?: string): Promise<ActiveAlarmsResponse> => {
    if (USE_MOCK) return mockApi.getActiveAlarms();
    const response = await api.get<ActiveAlarmsResponse>('/api/v1/alarms/active', {
      params: { organization_id: organizationId, severity },
    });
    return response.data;
  },

  get: async (alarmId: string): Promise<Alarm> => {
    const response = await api.get<Alarm>(`/api/v1/alarms/${alarmId}`);
    return response.data;
  },

  acknowledge: async (alarmId: string, data?: AlarmAcknowledge): Promise<Alarm> => {
    if (USE_MOCK) {
      await mockApi.acknowledgeAlarm(alarmId);
      return {} as Alarm;
    }
    const response = await api.post<Alarm>(`/api/v1/alarms/${alarmId}/acknowledge`, data || {});
    return response.data;
  },

  clear: async (alarmId: string): Promise<Alarm> => {
    const response = await api.post<Alarm>(`/api/v1/alarms/${alarmId}/clear`, {});
    return response.data;
  },

  acknowledgeAll: async (params?: { assetId?: string; severity?: string }): Promise<{ acknowledgedCount: number }> => {
    const response = await api.post<{ acknowledged_count: number }>('/api/v1/alarms/acknowledge-all', params || {});
    return { acknowledgedCount: response.data.acknowledged_count };
  },
};

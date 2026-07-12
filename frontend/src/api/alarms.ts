import { api } from './client';
import { mockApi } from './mockApi';
import { USE_MOCK } from './mockMode';
import { registerTransform } from './transformRegistry';
import { Alarm, AlarmFilters, ActiveAlarmsResponse, AlarmAcknowledge, PaginatedResponse } from '../types';

// FS-61: casing handled by the axios seam — no per-call toCamel/toSnake.
registerTransform('/api/v1/alarms');

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
    const items = response.data;
    return {
      items,
      total: items.length,
      skip: 0,
      limit: items.length,
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
    // The backend reads these as QUERY params, not a body — sending them in the
    // body silently drops the filters and acknowledges every active alarm.
    const query: Record<string, string> = {};
    if (params?.assetId) query.asset_id = params.assetId;
    if (params?.severity) query.severity = params.severity;
    // Response is camelized by the transform seam (acknowledged_count -> acknowledgedCount).
    const response = await api.post<{ acknowledgedCount: number }>('/api/v1/alarms/acknowledge-all', null, { params: query });
    return response.data;
  },
};

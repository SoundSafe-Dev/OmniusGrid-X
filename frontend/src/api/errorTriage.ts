import { api } from './client';
import {
  ErrorListParams,
  ErrorListResponse,
  ErrorSummary,
  ErrorEventDetail,
  ErrorStatus,
  ErrorRange,
} from '../types/errorTriage';

const BASE = '/api/v1/admin/errors';

export const errorTriageApi = {
  list: async (params: ErrorListParams): Promise<ErrorListResponse> => {
    const response = await api.get<ErrorListResponse>(`${BASE}`, { params });
    return response.data;
  },

  summary: async (range: ErrorRange): Promise<ErrorSummary> => {
    const response = await api.get<ErrorSummary>(`${BASE}/summary`, {
      params: { range },
    });
    return response.data;
  },

  detail: async (fingerprint: string): Promise<ErrorEventDetail> => {
    const response = await api.get<ErrorEventDetail>(`${BASE}/${fingerprint}`);
    return response.data;
  },

  updateStatus: async (
    fingerprint: string,
    status: ErrorStatus
  ): Promise<ErrorEventDetail> => {
    const response = await api.patch<ErrorEventDetail>(`${BASE}/${fingerprint}`, {
      status,
    });
    return response.data;
  },
};

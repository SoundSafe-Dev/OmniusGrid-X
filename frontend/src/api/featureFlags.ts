import { api } from './client';

export interface FeatureFlag {
  key: string;
  description: string;
  enabled: boolean;
  rollout_percentage: number;
  created_at: string;
  updated_at: string;
  updated_by: string | null;
}

export interface FeatureFlagCreate {
  key: string;
  description?: string;
  enabled?: boolean;
  rollout_percentage?: number;
}

export interface FeatureFlagUpdate {
  description?: string;
  enabled?: boolean;
  rollout_percentage?: number;
}

const BASE = '/api/v1/feature-flags';

export const featureFlagsApi = {
  // Resolved flag map for the caller's org (bucketed server-side on organization_id).
  evaluate: async (): Promise<Record<string, boolean>> => {
    const response = await api.get<{ flags: Record<string, boolean> }>(`${BASE}/evaluate`);
    return response.data.flags;
  },

  list: async (): Promise<FeatureFlag[]> => {
    const response = await api.get<{ flags: FeatureFlag[]; count: number }>(`${BASE}/`);
    return response.data.flags;
  },

  get: async (key: string): Promise<FeatureFlag> => {
    const response = await api.get<FeatureFlag>(`${BASE}/${key}`);
    return response.data;
  },

  create: async (payload: FeatureFlagCreate): Promise<FeatureFlag> => {
    const response = await api.post<FeatureFlag>(`${BASE}/`, payload);
    return response.data;
  },

  update: async (key: string, payload: FeatureFlagUpdate): Promise<FeatureFlag> => {
    const response = await api.put<FeatureFlag>(`${BASE}/${key}`, payload);
    return response.data;
  },

  remove: async (key: string): Promise<{ deleted: string }> => {
    const response = await api.delete<{ deleted: string }>(`${BASE}/${key}`);
    return response.data;
  },
};

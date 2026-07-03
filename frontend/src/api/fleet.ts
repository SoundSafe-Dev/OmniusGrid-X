import { api } from './client';
import {
  AgentRelease,
  AgentReleaseCreate,
  AgentRollout,
  AgentRolloutCreate,
  AgentVersionDistributionResponse,
} from '../types/fleet';

const BASE = '/api/v1/fleet';

export const fleetApi = {
  versions: async (): Promise<AgentVersionDistributionResponse> => {
    const response = await api.get<AgentVersionDistributionResponse>(`${BASE}/agents/versions`);
    return response.data;
  },

  releases: async (): Promise<AgentRelease[]> => {
    const response = await api.get<AgentRelease[]>(`${BASE}/releases`);
    return response.data;
  },

  createRelease: async (payload: AgentReleaseCreate): Promise<AgentRelease> => {
    const response = await api.post<AgentRelease>(`${BASE}/releases`, payload);
    return response.data;
  },

  publishRelease: async (releaseId: string): Promise<AgentRelease> => {
    const response = await api.post<AgentRelease>(`${BASE}/releases/${releaseId}/publish`);
    return response.data;
  },

  yankRelease: async (releaseId: string): Promise<AgentRelease> => {
    const response = await api.post<AgentRelease>(`${BASE}/releases/${releaseId}/yank`);
    return response.data;
  },

  rollouts: async (): Promise<AgentRollout[]> => {
    const response = await api.get<AgentRollout[]>(`${BASE}/rollouts`);
    return response.data;
  },

  rollout: async (rolloutId: string): Promise<AgentRollout> => {
    const response = await api.get<AgentRollout>(`${BASE}/rollouts/${rolloutId}`);
    return response.data;
  },

  createRollout: async (payload: AgentRolloutCreate): Promise<AgentRollout> => {
    const response = await api.post<AgentRollout>(`${BASE}/rollouts`, payload);
    return response.data;
  },

  pauseRollout: async (rolloutId: string): Promise<AgentRollout> => {
    const response = await api.post<AgentRollout>(`${BASE}/rollouts/${rolloutId}/pause`);
    return response.data;
  },

  cancelRollout: async (rolloutId: string): Promise<AgentRollout> => {
    const response = await api.post<AgentRollout>(`${BASE}/rollouts/${rolloutId}/cancel`);
    return response.data;
  },
};

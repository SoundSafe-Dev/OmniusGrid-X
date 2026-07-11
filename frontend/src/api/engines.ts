import { api } from './client';
import { mockApi } from './mockApi';
import {
  TacticalEngineStatus,
  TacticalDecision,
  InferenceRequest,
  StrategicRecommendation,
  MLOpsStatus,
  CloudGatewayStatus,
} from '../types';
import { USE_MOCK } from './mockMode';
import { toCamel } from './transform';

export const enginesApi = {
  // Tactical Engine
  getTacticalStatus: async (): Promise<TacticalEngineStatus> => {
    if (USE_MOCK) {
      const status = await mockApi.getTacticalStatus();
      return status as TacticalEngineStatus;
    }
    const response = await api.get<any>('/api/v1/engines/tactical/status');
    return toCamel<TacticalEngineStatus>(response.data);
  },

  runInference: async (assetId: string, featureVector: Record<string, number>): Promise<TacticalDecision> => {
    const response = await api.post<any>('/api/v1/engines/tactical/infer', {
      asset_id: assetId,
      feature_vector: featureVector,
    });
    return toCamel<TacticalDecision>(response.data);
  },

  // Strategic Engine
  getStrategicRecommendations: async (minPriority?: number): Promise<StrategicRecommendation[]> => {
    if (USE_MOCK) {
      const recs = await mockApi.getStrategicRecommendations();
      return recs as StrategicRecommendation[];
    }
    const response = await api.get<any>('/api/v1/engines/strategic/recommendations', {
      params: minPriority !== undefined ? { min_priority: minPriority } : undefined,
    });
    return toCamel<StrategicRecommendation[]>(response.data);
  },

  approveRecommendation: async (recId: string, operatorId: string, notes?: string): Promise<void> => {
    await api.post(`/api/v1/engines/strategic/recommendations/${recId}/approve`, {
      operator_id: operatorId,
      notes,
    });
  },

  rejectRecommendation: async (recId: string, operatorId: string, reason: string): Promise<void> => {
    await api.post(`/api/v1/engines/strategic/recommendations/${recId}/reject`, {
      operator_id: operatorId,
      reason,
    });
  },

  // MLOps Pipeline
  getMLOpsStatus: async (): Promise<MLOpsStatus> => {
    if (USE_MOCK) return mockApi.getMLOpsStatus() as MLOpsStatus;
    const response = await api.get<any>('/api/v1/engines/mlops/status');
    return toCamel<MLOpsStatus>(response.data);
  },

  deployModel: async (version: string): Promise<void> => {
    await api.post(`/api/v1/engines/mlops/deploy/${version}`, {});
  },

  rollbackModel: async (): Promise<void> => {
    await api.post('/api/v1/engines/mlops/rollback', {});
  },

  // Cloud Gateway
  getCloudGatewayStatus: async (): Promise<CloudGatewayStatus> => {
    if (USE_MOCK) return mockApi.getCloudGatewayStatus() as CloudGatewayStatus;
    const response = await api.get<any>('/api/v1/engines/cloud/status');
    return toCamel<CloudGatewayStatus>(response.data);
  },

  forceCloudFlush: async (): Promise<void> => {
    await api.post('/api/v1/engines/cloud/flush', {});
  },
};

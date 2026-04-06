import { api } from './client';
import {
  TacticalEngineStatus,
  TacticalDecision,
  InferenceRequest,
  StrategicRecommendation,
  MLOpsStatus,
  CloudGatewayStatus,
} from '../types';

export const enginesApi = {
  // Tactical Engine
  getTacticalStatus: async (): Promise<TacticalEngineStatus> => {
    const response = await api.get<TacticalEngineStatus>('/api/v1/engines/tactical/status');
    return response.data;
  },

  runInference: async (assetId: string, featureVector: Record<string, number>): Promise<TacticalDecision> => {
    const response = await api.post<TacticalDecision>('/api/v1/engines/tactical/infer', {
      asset_id: assetId,
      feature_vector: featureVector,
    });
    return response.data;
  },

  // Strategic Engine
  getStrategicRecommendations: async (minPriority?: number): Promise<StrategicRecommendation[]> => {
    const response = await api.get<StrategicRecommendation[]>('/api/v1/engines/strategic/recommendations', {
      params: minPriority !== undefined ? { min_priority: minPriority } : undefined,
    });
    return response.data;
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
    const response = await api.get<MLOpsStatus>('/api/v1/engines/mlops/status');
    return response.data;
  },

  deployModel: async (version: string): Promise<void> => {
    await api.post(`/api/v1/engines/mlops/deploy/${version}`, {});
  },

  rollbackModel: async (): Promise<void> => {
    await api.post('/api/v1/engines/mlops/rollback', {});
  },

  // Cloud Gateway
  getCloudGatewayStatus: async (): Promise<CloudGatewayStatus> => {
    const response = await api.get<CloudGatewayStatus>('/api/v1/engines/cloud/status');
    return response.data;
  },

  forceCloudFlush: async (): Promise<void> => {
    await api.post('/api/v1/engines/cloud/flush', {});
  },
};

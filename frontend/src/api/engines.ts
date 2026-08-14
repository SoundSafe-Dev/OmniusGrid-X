import { api } from './client';
import { mockApi } from './mockApi';
import {
  TacticalEngineStatus,
  TacticalDecision,
  StrategicRecommendation,
  MLOpsStatus,
  CloudGatewayStatus,
} from '../types';
import { USE_MOCK } from './mockMode';
import { registerTransform } from './transformRegistry';

// FS-61: casing handled by the axios seam — no per-call toCamel/toSnake.
registerTransform('/api/v1/engines');

export const enginesApi = {
  // Tactical Engine
  getTacticalStatus: async (): Promise<TacticalEngineStatus> => {
    if (USE_MOCK) {
      return mockApi.getTacticalStatus();
    }
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
    if (USE_MOCK) {
      return mockApi.getStrategicRecommendations();
    }
    const response = await api.get<StrategicRecommendation[]>('/api/v1/engines/strategic/recommendations', {
      params: minPriority !== undefined ? { min_priority: minPriority } : undefined,
    });
    return response.data;
  },

  // QUERY PARAMS, NOT A BODY — and this pair has never once succeeded.
  //
  // `approve_recommendation(rec_id: str, operator_id: str, notes: Optional[str] = None)`
  // in `app/api/engines.py` annotates both as bare `str`, which FastAPI reads as QUERY
  // parameters. Sending them in the body left `operator_id` missing, so every click on
  // Approve or Reject returned 422 with `loc: ["query", "operator_id"]`. Observed by
  // clicking the buttons on /engines/strategic against a real backend on 2026-08-01;
  // nothing had ever exercised them, because the mock path returns void without a request.
  //
  // Fixed on this side deliberately: `engines.py` belongs to another lane, and moving the
  // client onto the contract the server already publishes needs no agreement to land.
  approveRecommendation: async (recId: string, operatorId: string, notes?: string): Promise<void> => {
    await api.post(`/api/v1/engines/strategic/recommendations/${recId}/approve`, null, {
      params: { operator_id: operatorId, ...(notes !== undefined ? { notes } : {}) },
    });
  },

  rejectRecommendation: async (recId: string, operatorId: string, reason: string): Promise<void> => {
    await api.post(`/api/v1/engines/strategic/recommendations/${recId}/reject`, null, {
      params: { operator_id: operatorId, reason },
    });
  },

  // Decisions already made — approvals AND rejections (P4, closing FS-567's frontend
  // half; the route landed in engines.py and this client never followed, so the History
  // card kept rendering "not available from the API" against an API where it was).
  //
  // Two signals ride the response HEADERS and are surfaced rather than dropped:
  // `X-Engine-Not-Running: strategic` — the loop behind this data is not up, so what it
  // returns is a snapshot, not a live ledger; and `X-Result-Truncated` — a bare array of
  // exactly `limit` rows is indistinguishable from the complete history, and on a
  // DECISION log that reads as "these are all the calls anyone made".
  // Returns null when the server predates the route (404): "this deployment cannot
  // list decisions" and "the request failed" are different statements, and the page
  // renders them differently.
  getRecommendationHistory: async (
    limit = 50,
  ): Promise<{ items: StrategicRecommendation[]; engineStopped: boolean; truncated: boolean } | null> => {
    try {
      const response = await api.get<StrategicRecommendation[]>(
        '/api/v1/engines/strategic/recommendations/history',
        { params: { limit } },
      );
      return {
        items: response.data,
        engineStopped: Boolean(response.headers['x-engine-not-running']),
        truncated: response.headers['x-result-truncated'] === 'true',
      };
    } catch (error: any) {
      if (error?.response?.status === 404) return null;
      throw error;
    }
  },

  // MLOps Pipeline
  getMLOpsStatus: async (): Promise<MLOpsStatus> => {
    if (USE_MOCK) return mockApi.getMLOpsStatus();
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
    if (USE_MOCK) return mockApi.getCloudGatewayStatus();
    const response = await api.get<CloudGatewayStatus>('/api/v1/engines/cloud/status');
    return response.data;
  },

  forceCloudFlush: async (): Promise<void> => {
    await api.post('/api/v1/engines/cloud/flush', {});
  },
};

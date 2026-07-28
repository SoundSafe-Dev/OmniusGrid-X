import { api } from './client';
import { toListResult, type ListResult } from './listResult';
import { USE_MOCK } from './mockMode';
import { registerTransform } from './transformRegistry';

// FS-84: casing handled by the axios seam — TS speaks camelCase, wire speaks
// snake_case. /api/v1/rul is not on the never-register list, so opt in here.
registerTransform('/api/v1/rul');

export interface MaintenanceWindow {
  start: string;
  end: string;
  urgency: string;
  reason: string;
}

export interface RULAssessment {
  assetId: string;
  healthScore: number;
  failureProbability: number;
  probabilityHorizonHours: number;
  remainingUsefulLifeHours: number;
  riskLevel: string;
  confidence: number;
  recommendedMaintenanceWindow: MaintenanceWindow;
  drivers: Array<Record<string, unknown>>;
  modelSource: string;
  computedAt: string;
  notificationDispatched: boolean;
  notificationDeliveryCount: number;
}

export interface RULListParams {
  hours?: number;
  offset?: number;
  limit?: number;
}

const MOCK_DELAY = 300;
const delay = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

const mockAssessment = (assetId: string, i = 0): RULAssessment => {
  const rul = 720 - i * 180;
  const risk = rul < 120 ? 'critical' : rul < 300 ? 'high' : rul < 500 ? 'medium' : 'low';
  const now = Date.now();
  return {
    assetId,
    healthScore: Math.max(0.2, 0.95 - i * 0.15),
    failureProbability: Math.min(0.9, 0.05 + i * 0.18),
    probabilityHorizonHours: 168,
    remainingUsefulLifeHours: Math.max(24, rul),
    riskLevel: risk,
    confidence: 0.82,
    recommendedMaintenanceWindow: {
      start: new Date(now + rul * 3600_000).toISOString(),
      end: new Date(now + (rul + 8) * 3600_000).toISOString(),
      urgency: risk,
      reason: 'Projected component wear approaching threshold',
    },
    drivers: [
      { feature: 'vibration_rms', contribution: 0.42 },
      { feature: 'bearing_temp', contribution: 0.31 },
    ],
    modelSource: 'mock',
    computedAt: new Date(now).toISOString(),
    notificationDispatched: false,
    notificationDeliveryCount: 0,
  };
};

export const rulApi = {
  // Returns ListResult, not a bare array. The endpoint caps at `limit` and orders by
  // asset NAME — remaining useful life is computed per asset in Python, so risk is not
  // a sortable column — which means truncation drops the alphabetically-last assets
  // from the one view whose job is finding machines about to fail. Handing back
  // `response.data` would discard the only thing that says so.
  listAssessments: async (params: RULListParams = {}): Promise<ListResult<RULAssessment>> => {
    if (USE_MOCK) {
      await delay(MOCK_DELAY);
      const items = ['asset-alpha', 'asset-bravo', 'asset-charlie', 'asset-delta'].map(
        (id, i) => mockAssessment(id, i)
      );
      return { items, truncated: false, limit: items.length };
    }
    return toListResult(await api.get<RULAssessment[]>('/api/v1/rul', { params }));
  },

  getAssessment: async (
    assetId: string,
    opts: { hours?: number; notify?: boolean } = {}
  ): Promise<RULAssessment> => {
    if (USE_MOCK) {
      await delay(MOCK_DELAY);
      return mockAssessment(assetId);
    }
    const response = await api.get<RULAssessment>(`/api/v1/rul/${assetId}`, { params: opts });
    return response.data;
  },
};

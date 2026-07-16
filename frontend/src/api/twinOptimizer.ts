import { api } from './client';
import { USE_MOCK } from './mockMode';
import { registerTransform } from './transformRegistry';

// FS-84: casing handled by the axios seam — TS speaks camelCase, wire speaks
// snake_case. /api/v1/twin is not on the never-register list, so opt in here.
// Request bodies are toSnake'd on the way out, which lines up with the backend's
// `extra="forbid"` OptimizeRequest schema.
registerTransform('/api/v1/twin');

export type RecommendationType =
  | 'schedule_change'
  | 'parameter_tuning'
  | 'maintenance_window';

export interface ScenarioOverrides {
  cycleTimeSeconds?: number;
  mtbfHours?: number;
  mttrHours?: number;
  performance?: number;
  quality?: number;
}

export interface BaselineRequest {
  horizonHours?: number;
  cycleTimeSeconds?: number;
  mtbfHours?: number;
  mttrHours?: number;
  performance?: number;
  quality?: number;
}

export interface CandidateAction {
  actionId: string;
  name: string;
  description: string;
  targetAssetId?: string | null;
  recommendationType?: RecommendationType;
  overrides: ScenarioOverrides;
  requiresApproval: true;
}

export interface OptimizeRequest {
  assetIds?: string[];
  baseline?: BaselineRequest;
  candidates: CandidateAction[];
  runs?: number;
  seed?: number;
  minImprovementPercent?: number;
  maxRecommendations?: number;
  emitRecommendations?: boolean;
  validForHours?: number;
}

export interface ExpectedImpact {
  throughputDeltaParts: number;
  throughputImprovementPercent: number;
  downtimeReductionHours: number;
  availabilityImprovementPoints: number;
  objectiveScore: number;
}

export interface OptimizeRecommendation {
  rank: number;
  recommendationId: string;
  actionId: string;
  name: string;
  description: string;
  assetId: string | null;
  recommendationType: string;
  priority: number;
  confidence: number;
  expectedImpact: ExpectedImpact;
  scenarioInputs: Record<string, unknown>;
  scenarioMetrics: Record<string, unknown>;
  simulationBasis: string;
  requiresApproval: boolean;
  strategicEngineEmitted: boolean;
}

export interface OptimizeResponse {
  organizationId: string;
  objective: string;
  evaluatedCandidates: number;
  baselineSimulation: Record<string, unknown>;
  fleetSummary: Record<string, unknown>;
  recommendations: OptimizeRecommendation[];
  generatedAt: string;
}

/**
 * A ready-to-send what-if request the Strategic Engine page fires by default:
 * two parameter-tuning candidates against the tenant's active fleet. Callers can
 * override any field.
 */
export function defaultOptimizeRequest(
  overrides: Partial<OptimizeRequest> = {}
): OptimizeRequest {
  return {
    candidates: [
      {
        actionId: 'faster-cycle',
        name: 'Tighten cycle time',
        description: 'Reduce nominal cycle time by ~8% via parameter tuning.',
        recommendationType: 'parameter_tuning',
        overrides: { cycleTimeSeconds: 55 },
        requiresApproval: true,
      },
      {
        actionId: 'reliability-uplift',
        name: 'Improve reliability',
        description: 'Extend MTBF and shorten MTTR through a maintenance window.',
        recommendationType: 'maintenance_window',
        overrides: { mtbfHours: 65, mttrHours: 1.5 },
        requiresApproval: true,
      },
    ],
    ...overrides,
  };
}

const mockResponse = (req: OptimizeRequest): OptimizeResponse => ({
  organizationId: '00000000-0000-0000-0000-000000000000',
  objective: 'maximize_throughput',
  evaluatedCandidates: req.candidates.length,
  baselineSimulation: { throughputParts: 5040, availability: 0.94 },
  fleetSummary: { assetCount: 4, averageOee: 0.71 },
  generatedAt: new Date().toISOString(),
  recommendations: req.candidates.map((c, i) => ({
    rank: i + 1,
    recommendationId: `rec-${c.actionId}`,
    actionId: c.actionId,
    name: c.name,
    description: c.description,
    assetId: c.targetAssetId ?? null,
    recommendationType: c.recommendationType ?? 'parameter_tuning',
    priority: 8 - i,
    confidence: 0.86 - i * 0.07,
    expectedImpact: {
      throughputDeltaParts: 320 - i * 90,
      throughputImprovementPercent: 6.3 - i * 1.8,
      downtimeReductionHours: 4.2 - i * 1.1,
      availabilityImprovementPoints: 2.1 - i * 0.6,
      objectiveScore: 0.78 - i * 0.12,
    },
    scenarioInputs: c.overrides as Record<string, unknown>,
    scenarioMetrics: { availability: 0.96 - i * 0.01 },
    simulationBasis: 'monte_carlo',
    requiresApproval: true,
    strategicEngineEmitted: req.emitRecommendations ?? true,
  })),
});

export const twinOptimizerApi = {
  optimize: async (request: OptimizeRequest): Promise<OptimizeResponse> => {
    if (USE_MOCK) {
      return mockResponse(request);
    }
    const response = await api.post<OptimizeResponse>('/api/v1/twin/optimize', request);
    return response.data;
  },
};

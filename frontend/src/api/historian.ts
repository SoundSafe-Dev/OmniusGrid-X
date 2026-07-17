import { api } from './client';
import { USE_MOCK } from './mockMode';
import { registerTransform } from './transformRegistry';

// FS-84: casing handled by the axios seam — TS speaks camelCase, wire speaks
// snake_case. /api/v1/historian is not on the never-register list, so opt in.
registerTransform('/api/v1/historian');

export type HistorianGranularity = 'raw' | '1m' | '1h' | '1d';

export interface HistorianPoint {
  timestamp: string;
  average: number;
  minimum: number;
  maximum: number;
  sampleCount: number;
}

export interface HistorianQueryResponse {
  assetId: string;
  metric: string;
  granularity: HistorianGranularity;
  start: string;
  end: string;
  effectiveStart: string;
  offset: number;
  limit: number;
  count: number;
  hasMore: boolean;
  points: HistorianPoint[];
}

export interface HistorianQueryParams {
  assetId: string;
  metric: string;
  start: string;
  end: string;
  granularity?: HistorianGranularity;
  offset?: number;
  limit?: number;
}

const MOCK_DELAY = 300;
const delay = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

const mockResponse = (params: HistorianQueryParams): HistorianQueryResponse => {
  const start = new Date(params.start).getTime();
  const end = new Date(params.end).getTime();
  const buckets = 48;
  const step = (end - start) / buckets;
  const points: HistorianPoint[] = Array.from({ length: buckets }, (_, i) => {
    const base = 50 + 20 * Math.sin(i / 4) + (Math.random() - 0.5) * 6;
    return {
      timestamp: new Date(start + i * step).toISOString(),
      average: Number(base.toFixed(2)),
      minimum: Number((base - 4).toFixed(2)),
      maximum: Number((base + 4).toFixed(2)),
      sampleCount: 60,
    };
  });
  return {
    assetId: params.assetId,
    metric: params.metric,
    granularity: params.granularity ?? 'raw',
    start: params.start,
    end: params.end,
    effectiveStart: params.start,
    offset: params.offset ?? 0,
    limit: params.limit ?? 1000,
    count: points.length,
    hasMore: false,
    points,
  };
};

export const historianApi = {
  query: async (params: HistorianQueryParams): Promise<HistorianQueryResponse> => {
    if (USE_MOCK) {
      await delay(MOCK_DELAY);
      return mockResponse(params);
    }
    const response = await api.get<HistorianQueryResponse>('/api/v1/historian/query', {
      params,
    });
    return response.data;
  },
};

import { api } from './client';
import { registerTransform } from './transformRegistry';

/**
 * The `/api/v1/oee` router, which had NO frontend client at all (P8).
 *
 * Four endpoints — `current`, `historical`, `losses`, `dashboard/summary` — none of them
 * reachable from the UI. The OEE page read a single fleet-availability figure from the
 * dashboard router and expanded rows into three-factor OEE, and that was the whole of
 * OEE in the product. The most conspicuous absence was the loss breakdown: "where is my
 * OEE going" is the question the number exists to raise, and only `/losses` answers it.
 *
 * NO USE_MOCK BRANCH. The mock dataset has no loss figures and inventing them would put
 * a fabricated Pareto in front of an operator — the failure class this repository has
 * spent findings on. In mock mode these calls fail and the panel says the data is
 * unavailable, which is true.
 */

registerTransform('/api/v1/oee');

export interface OEELosses {
  availability: { percentage: number; minutes: number; category: string };
  performance: { percentage: number; impact: string; category: string };
  quality: {
    percentage: number;
    rejectedParts?: number | null;
    totalParts?: number | null;
    category: string;
  };
}

export interface OEELossesOut {
  assetId: string;
  periodHours: number;
  oee: number;
  losses: OEELosses;
  /** The three losses SUMMED — not a percentage of anything, so it can exceed 100. The
   *  server's own comment says so; a bar chart scaled to 100 would misdraw it. */
  totalLossPercentage: number;
  potentialOee: number;
}

export interface HistoricalOEEPoint {
  periodStart: string;
  availability: number;
  performance: number;
  quality: number;
  oee: number;
}

export interface HistoricalOEEOut {
  assetId: string;
  aggregation: string;
  points: HistoricalOEEPoint[];
}

export const oeeApi = {
  getLosses: async (assetId: string, hours = 8): Promise<OEELossesOut> => {
    const response = await api.get<OEELossesOut>(`/api/v1/oee/losses/${assetId}`, {
      params: { hours },
    });
    return response.data;
  },

  getHistorical: async (
    assetId: string,
    hours = 24,
    aggregation: 'hourly' | 'daily' | 'shift' = 'hourly',
  ): Promise<HistoricalOEEOut> => {
    const response = await api.get<HistoricalOEEOut>(`/api/v1/oee/historical/${assetId}`, {
      params: { hours, aggregation },
    });
    return response.data;
  },
};

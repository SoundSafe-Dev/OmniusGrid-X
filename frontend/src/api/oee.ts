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
 * `getHistorical` IS NOT HERE, deliberately. The first draft of this client declared one
 * with a `HistoricalOEEPoint[]` under a `points` key — and
 * `test_frontend_fields_exist_on_the_wire.py` refused it: the envelope carries `data`,
 * and the calculator owns the row shape (`List[Dict[str, Any]]`), so there is no point
 * type to declare. Rather than write an accurate type for a method nothing calls, the
 * method is gone until a historical chart needs it. An unused client carrying a guessed
 * shape is the "declared and never produced" defect this repository sweeps for, written
 * by the person doing the sweeping.
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

export interface OEEDashboardSummary {
  organizationId: string;
  timestamp: string;
  aggregate: {
    /** `null` when nothing was measured. The average of an empty set is not zero, and a
     *  fleet-wide 0% OEE is an emergency — the server returns null precisely so a
     *  consumer cannot render one by accident. */
    avgOee: number | null;
    avgAvailability: number | null;
    avgPerformance: number | null;
    avgQuality: number | null;
    assetCount: number;
    /** The two figures that let a reader tell a healthy fleet from an unread one. */
    assetsMeasured: number;
    assetsUnavailable: number;
  };
}

export const oeeApi = {
  /** Fleet-wide THREE-FACTOR OEE. Not to be confused with
   *  `dashboardApi.getFleetOEE`, which reports availability only and sets
   *  `availabilityOnly: true` to say so (FS-399) — the distinction the dashboard's
   *  "Availability" tile has been carefully named around since FS-192. */
  /** NO WINDOW ARGUMENT, because the route takes none: it computes each asset over a
   *  fixed 1-hour window (`calculate_oee(..., time_window_hours=1.0)`). Sending a
   *  `hours` param would be silently dropped by FastAPI and the caller would believe a
   *  range control was doing something — the query-parameter defect this codebase has
   *  swept for twice. The tile is labelled "last hour" for the same reason. */
  getDashboardSummary: async (): Promise<OEEDashboardSummary> => {
    const response = await api.get<OEEDashboardSummary>('/api/v1/oee/dashboard/summary');
    return response.data;
  },

  getLosses: async (assetId: string, hours = 8): Promise<OEELossesOut> => {
    const response = await api.get<OEELossesOut>(`/api/v1/oee/losses/${assetId}`, {
      params: { hours },
    });
    return response.data;
  },

};

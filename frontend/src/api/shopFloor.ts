import { api } from './client';
import { registerTransform } from './transformRegistry';

/**
 * The four things that happen on a floor, and where each one has to go (FS-405).
 *
 *     a part is issued        -> inventory, purchasing, accounting
 *     time is clocked         -> production, accounting
 *     a problem is found      -> quality, inventory, production, accounting
 *     a machine goes down     -> scheduling, production, quality, accounting
 *
 * NOTHING HERE IS SUMMARISED INTO A BOOLEAN. Every response carries a `fanout` with one entry
 * per target system, because those arrows succeed and fail independently — a part issue can
 * reach inventory, sit queued for accounting, and be waiting on a phone call to purchasing,
 * all at once. `fullyPosted` is the only field that means "it all landed", and it is computed
 * server-side from the postings rather than assumed from a 201.
 *
 * `awaitingAPerson` is the analog path: targets with no integration, each carrying the
 * sentence to hand to a human. Rendering it is not optional — a dropped instruction is
 * indistinguishable from a dropped event.
 */

registerTransform('/api/v1/shop-floor');

export interface Fanout {
  eventType: string;
  eventId: string;
  targets: number;
  byStatus: Record<string, number>;
  /** The only field that means everything landed. */
  fullyPosted: boolean;
  awaitingAPerson: { target: string; instruction: string | null }[];
}

export interface Posting {
  id: string;
  targetSystem: string;
  status: string;
  externalRef: string | null;
  instruction: string | null;
  attempts: number;
  lastError: string | null;
  acknowledgedAt: string | null;
  postedAt: string | null;
}

export interface PartIssue {
  id: string;
  partNumber: string;
  quantity: number;
  unitOfMeasure: string;
  description: string | null;
  assetId: string | null;
  workOrderRef: string | null;
  unitCost: number | null;
  /** quantity x unitCost, or null when the cost is unknown. NEVER 0 as a stand-in. */
  extendedCost: number | null;
  currency: string | null;
  reason: string;
  issuedAt: string;
  fanout: Fanout;
}

export interface LaborEntry {
  id: string;
  userId: string | null;
  operatorRef: string | null;
  assetId: string | null;
  workOrderRef: string | null;
  clockInAt: string;
  clockOutAt: string | null;
  durationMinutes: number | null;
  laborCategory: string;
  /** Absent while the clock is running — an open shift has produced no hours to post. */
  fanout: Fanout | null;
}

export interface QualityEvent {
  id: string;
  eventType: string;
  severity: string;
  description: string;
  assetId: string | null;
  workOrderRef: string | null;
  partNumber: string | null;
  quantityAffected: number | null;
  scrapQuantity: number | null;
  disposition: string | null;
  occurredAt: string;
  fanout: Fanout;
}

export interface DowntimeEvent {
  id: string;
  assetId: string;
  downtimeType: string;
  reasonCode: string | null;
  description: string | null;
  startedAt: string;
  endedAt: string | null;
  durationMinutes: number | null;
  maintenanceRef: string | null;
  /** Absent while the machine is still down. */
  fanout: Fanout | null;
}

export interface PostingPage {
  items: Posting[];
  total: number;
  limit: number;
  truncated: boolean;
}

export interface PartIssuePage {
  items: PartIssue[];
  total: number;
  limit: number;
  truncated: boolean;
}

export const shopFloorApi = {
  issuePart: async (body: {
    partNumber: string;
    quantity: number;
    unitOfMeasure?: string;
    description?: string;
    assetId?: string;
    workOrderRef?: string;
    unitCost?: number;
    currency?: string;
    reason?: string;
  }): Promise<PartIssue> => {
    const response = await api.post<PartIssue>('/api/v1/shop-floor/part-issues', body);
    return response.data;
  },

  listPartIssues: async (params?: { limit?: number; workOrderRef?: string }): Promise<PartIssuePage> => {
    const response = await api.get<PartIssuePage>('/api/v1/shop-floor/part-issues', { params });
    return response.data;
  },

  clockIn: async (body: {
    operatorRef?: string;
    assetId?: string;
    workOrderRef?: string;
    laborCategory?: string;
  }): Promise<LaborEntry> => {
    const response = await api.post<LaborEntry>('/api/v1/shop-floor/labor/clock-in', body);
    return response.data;
  },

  clockOut: async (notes?: string): Promise<LaborEntry> => {
    const response = await api.post<LaborEntry>('/api/v1/shop-floor/labor/clock-out', {
      notes: notes || null,
    });
    return response.data;
  },

  /** The caller's running clock, or null. Null is a real answer, not an empty list. */
  openLaborEntry: async (): Promise<LaborEntry | null> => {
    const response = await api.get<LaborEntry | null>('/api/v1/shop-floor/labor/open');
    return response.data ?? null;
  },

  reportProblem: async (body: {
    description: string;
    eventType?: string;
    severity?: string;
    assetId?: string;
    workOrderRef?: string;
    partNumber?: string;
    quantityAffected?: number;
    scrapQuantity?: number;
    disposition?: string;
  }): Promise<QualityEvent> => {
    const response = await api.post<QualityEvent>('/api/v1/shop-floor/quality-events', body);
    return response.data;
  },

  startDowntime: async (body: {
    assetId: string;
    downtimeType?: string;
    reasonCode?: string;
    description?: string;
    maintenanceRef?: string;
  }): Promise<DowntimeEvent> => {
    const response = await api.post<DowntimeEvent>('/api/v1/shop-floor/downtime/start', body);
    return response.data;
  },

  endDowntime: async (eventId: string, body?: { reasonCode?: string; description?: string }): Promise<DowntimeEvent> => {
    const response = await api.post<DowntimeEvent>(
      `/api/v1/shop-floor/downtime/${eventId}/end`,
      body ?? {},
    );
    return response.data;
  },

  listPostings: async (params?: {
    status?: string;
    outstandingOnly?: boolean;
    limit?: number;
  }): Promise<PostingPage> => {
    const response = await api.get<PostingPage>('/api/v1/shop-floor/postings', { params });
    const page = response.data;
    if (!page || !Array.isArray(page.items) || typeof page.total !== 'number') {
      throw new Error('the postings ledger did not carry items and a total');
    }
    return page;
  },

  acknowledgePosting: async (postingId: string, externalRef?: string): Promise<Posting> => {
    const response = await api.post<Posting>(
      `/api/v1/shop-floor/postings/${postingId}/acknowledge`,
      { externalRef: externalRef || null },
    );
    return response.data;
  },

  routing: async (): Promise<{
    routing: Record<string, string[]>;
    targetSystems: string[];
    postingStatuses: Record<string, string>;
  }> => {
    const response = await api.get('/api/v1/shop-floor/routing');
    return response.data;
  },
};

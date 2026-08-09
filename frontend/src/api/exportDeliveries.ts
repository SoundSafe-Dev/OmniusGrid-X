import { api } from './client';

/**
 * Scheduled export deliveries — the ones that go out without anybody watching (FS-285).
 *
 * `GET /api/v1/exports/deliveries` has returned `status` and `error` per job for some time,
 * and **no frontend file called it.** A user schedules a report to be emailed, the send
 * fails, `ExportDeliveryJob.status` becomes `'failed'` with the reason in `error` — and
 * there is no surface anywhere that would ever show them either one. What they experience is
 * a report that did not arrive, and a product with nothing to say about it.
 *
 * That is the same shape as the notification delivery log, one artefact over: the question a
 * person actually has is *"did the thing I scheduled go out?"*, and until now the honest
 * answer available to them was silence.
 *
 * SNAKE_CASE ON PURPOSE. `/api/v1/exports` is **not** registered in `transformRegistry`, so
 * no interceptor renames these keys and the wire sends `schedule_id`, `scheduled_for` and
 * `completed_at` exactly as the response model spells them. Declaring the camelCase names
 * here would have been the defect this codebase has spent a long time sweeping for — a type
 * asserting fields the server never sends, with TypeScript vouching for them.
 *
 * Registering the prefix would fix the casing and change it for `ExportButton`'s job polling
 * too, which works today. Changing a shared seam to suit one new caller is a poor trade, so
 * the type matches the wire instead.
 *
 * NO MOCK BRANCH. Every other client here forks on `USE_MOCK`, and a fixture would be
 * actively wrong for this one: the demo would show a tidy list of successful deliveries,
 * which is the single most misleading thing this endpoint could say. In mock mode the request
 * fails and the page says the list is unavailable — which is true, and which the page
 * distinguishes from "no deliveries have been attempted" (FS-489).
 */

/** One row of `GET /api/v1/exports/deliveries`, after the casing seam. */
export interface ExportDelivery {
  id: string;
  schedule_id: string;
  /** `queued` | `sending` | `sent` | `failed` — the server's own vocabulary, not remapped. */
  status: string;
  filename: string | null;
  /** Why it failed, when it did. The whole reason this client exists. */
  error: string | null;
  scheduled_for: string | null;
  completed_at: string | null;
}

export interface ExportDeliveryList {
  items: ExportDelivery[];
}

export const exportDeliveriesApi = {
  /** Most recent first, capped by the server at `limit` (default 50, max 200). */
  list: async (limit = 50): Promise<ExportDeliveryList> => {
    const response = await api.get<ExportDeliveryList>('/api/v1/exports/deliveries', {
      params: { limit },
    });
    return response.data;
  },
};

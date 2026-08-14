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


/**
 * The SCHEDULES behind those deliveries (P9, page-enhancement review).
 *
 * Nine endpoints — schedules list/create/get/update/delete and templates
 * list/create/get/update/delete — with **zero frontend references**. A user could see
 * that a scheduled report failed and could not see what the schedule was, who received
 * it, when it next ran, or pause it. The delivery log answered "did it go out?" while
 * nothing answered "what is it and can I stop it?".
 *
 * SNAKE_CASE ON PURPOSE, for the reason the deliveries client documents above: this
 * prefix is not on the transform seam, so the wire spells `template_id`, `next_run_at`
 * and `is_active` exactly as the response models do.
 */

/** One row of `GET /api/v1/exports/schedules`. */
export interface ScheduledExport {
  id: string;
  organization_id: string;
  template_id: string;
  name: string;
  /** `daily` | `weekly` | `monthly` — the server's closed set. */
  frequency: string;
  timezone: string;
  next_run_at: string | null;
  recipients: string[];
  is_active: boolean;
  last_run_at: string | null;
  last_status: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface ScheduledExportList {
  items: ScheduledExport[];
  total: number;
  /** Whether SMTP is configured at all. A schedule with nowhere to deliver is worth
   *  saying out loud rather than letting a user infer it from reports that never
   *  arrive — the server sends this precisely so the UI can say it. */
  delivery_configured: boolean;
}

export interface ExportTemplate {
  id: string;
  name: string;
  description: string | null;
  export_type: string;
  export_format: string;
  columns: string[];
  filters: Record<string, unknown>;
}

export interface ExportTemplateList {
  items: ExportTemplate[];
  total: number;
}

export interface ScheduledExportCreate {
  template_id: string;
  name: string;
  frequency: string;
  timezone: string;
  next_run_at: string;
  recipients: string[];
  is_active: boolean;
}

export const exportSchedulesApi = {
  list: async (): Promise<ScheduledExportList> => {
    const response = await api.get<ScheduledExportList>('/api/v1/exports/schedules');
    return response.data;
  },

  listTemplates: async (): Promise<ExportTemplateList> => {
    const response = await api.get<ExportTemplateList>('/api/v1/exports/templates');
    return response.data;
  },

  create: async (payload: ScheduledExportCreate): Promise<ScheduledExport> => {
    const response = await api.post<ScheduledExport>('/api/v1/exports/schedules', payload);
    return response.data;
  },

  update: async (
    scheduleId: string,
    payload: Partial<ScheduledExportCreate>,
  ): Promise<ScheduledExport> => {
    const response = await api.put<ScheduledExport>(
      `/api/v1/exports/schedules/${scheduleId}`,
      payload,
    );
    return response.data;
  },

  remove: async (scheduleId: string): Promise<{ deleted: string }> => {
    const response = await api.delete<{ deleted: string }>(
      `/api/v1/exports/schedules/${scheduleId}`,
    );
    return response.data;
  },
};

import { api } from './client';
import { registerTransform } from './transformRegistry';

/**
 * Activating a correlation-AI recommendation (FS-406).
 *
 * WHAT THIS REPLACES. `CorrelationAIPane` rendered each recommended action as a bullet with
 * a green tick and no control, and the only way to act on one was an "Auto-integrate"
 * checkbox that fired a background job whose result never came back. This client gives the
 * pane a real verb, and — more importantly — a way to render what actually happened.
 *
 * NOTHING HERE DEFAULTS A MISSING FIELD. `ready_to_confirm ?? true`, `postings ?? []` and
 * friends are exactly the pattern `apiClientsDoNotDefaultResponses` exists to catch: a
 * malformed response would render as "everything landed", which is the one thing this whole
 * feature is built to stop claiming. A response that does not carry the fields is an error,
 * and it is thrown as one.
 */

// The casing seam handles snake_case -> camelCase; no per-call conversion here.
registerTransform('/api/v1/insights');

/** One external system this activation has to reach, and where that stands. */
export interface ActivationPosting {
  id: string;
  targetSystem: string;
  /** pending | posted | failed | manual_required | not_applicable */
  status: string;
  externalRef: string | null;
  /** Present only for `manual_required` — the sentence to hand to a person. */
  instruction: string | null;
  acknowledgedAt: string | null;
  postedAt: string | null;
  lastError: string | null;
}

export interface ActivationTask {
  id: string;
  title: string;
  taskType: string;
  status: string;
  priority: string;
  boardId: string | null;
  columnId: string | null;
}

export interface ActivationBlocker {
  kind: string;
  reason: string;
  target?: string;
  status?: string;
  taskId?: string;
  postingId?: string;
}

export interface AwaitingPerson {
  target: string;
  instruction: string | null;
  postingId: string;
}

export interface InsightActivation {
  id: string;
  title: string;
  description: string | null;
  domain: string | null;
  priority: string;
  source: string;
  sessionId: string | null;
  messageId: string | null;
  actionIndex: number | null;
  /** issued | confirmed | rejected | cancelled */
  status: string;
  issuedAt: string | null;
  confirmedAt: string | null;
  rejectedAt: string | null;
  rejectionReason: string | null;
  task: ActivationTask | null;
  /** Why no task exists, when none does. Rendered rather than swallowed. */
  taskBlockedReason: string | null;
  postings: ActivationPosting[];
  readyToConfirm: boolean;
  blockers: ActivationBlocker[];
  awaitingAPerson: AwaitingPerson[];
  validation: Record<string, unknown> | null;
  /** True when the server matched an existing activation — a retry, not a second dispatch. */
  alreadyExisted: boolean;
}

export interface ActivationPage {
  items: InsightActivation[];
  total: number;
  limit: number;
  truncated: boolean;
}

export interface ActivateRequest {
  title: string;
  description?: string;
  domain?: string;
  priority?: string;
  source?: string;
  sessionId?: string;
  messageId?: string;
  actionIndex?: number;
  assetId?: string;
  targets?: string[];
}

function requireActivation(body: unknown): InsightActivation {
  const activation = body as InsightActivation | undefined;
  if (!activation || typeof activation.id !== 'string' || !Array.isArray(activation.postings)) {
    throw new Error(
      'the server did not return an activation with its postings — refusing to render a ' +
        'dispatch that cannot be shown',
    );
  }
  return activation;
}

/**
 * The blockers the server sent with a 409, or null if this was not that kind of failure.
 *
 * They arrive nested inside the problem+json envelope (`error.details.detail.blockers`), and
 * the envelope's own `message` is the generic "request failed" — so a caller that reads the
 * top level shows the user nothing useful. Reading through the envelope is the point of this
 * helper existing rather than each call site guessing.
 */
export function blockersFromError(error: unknown): ActivationBlocker[] | null {
  const detail = (error as any)?.response?.data?.error?.details?.detail;
  if (detail && Array.isArray(detail.blockers)) return detail.blockers as ActivationBlocker[];
  return null;
}

export function messageFromError(error: unknown): string | null {
  const detail = (error as any)?.response?.data?.error?.details?.detail;
  if (detail && typeof detail.message === 'string') return detail.message;
  return null;
}

export const insightActivationApi = {
  /**
   * Issue one recommendation as real work.
   *
   * The response says what was created and where each external system stands. It does NOT
   * say the action is done, and the UI must not either — read `postings` and
   * `awaitingAPerson`.
   */
  activate: async (request: ActivateRequest): Promise<InsightActivation> => {
    const response = await api.post('/api/v1/insights/activations', request);
    return requireActivation(response.data);
  },

  list: async (params?: { status?: string; sessionId?: string; limit?: number }): Promise<ActivationPage> => {
    const response = await api.get<ActivationPage>('/api/v1/insights/activations', { params });
    const page = response.data;
    if (!page || !Array.isArray(page.items) || typeof page.total !== 'number') {
      throw new Error('the activations listing did not carry items and a total');
    }
    return page;
  },

  get: async (id: string): Promise<InsightActivation> => {
    const response = await api.get(`/api/v1/insights/activations/${id}`);
    return requireActivation(response.data);
  },

  /**
   * Validate and confirm. THROWS on 409 — the refusal is the feature. Call
   * `blockersFromError` on the thrown error to show the operator what is left.
   */
  confirm: async (id: string): Promise<InsightActivation> => {
    const response = await api.post(`/api/v1/insights/activations/${id}/confirm`);
    return requireActivation(response.data);
  },

  reject: async (id: string, reason: string): Promise<InsightActivation> => {
    const response = await api.post(`/api/v1/insights/activations/${id}/reject`, { reason });
    return requireActivation(response.data);
  },

  /**
   * The analog path: a person did the manual step. Supplying `externalRef` — the requisition
   * or work-order number the far system gave back — promotes the posting to `posted`;
   * without one it records who acted and when, and the posting stays `manual_required`.
   */
  acknowledgePosting: async (
    activationId: string,
    postingId: string,
    externalRef?: string,
  ): Promise<InsightActivation> => {
    const response = await api.post(
      `/api/v1/insights/activations/${activationId}/postings/${postingId}/acknowledge`,
      { externalRef: externalRef || null },
    );
    return requireActivation(response.data);
  },

  domainRouting: async (): Promise<{
    routing: Record<string, string[]>;
    defaultTargets: string[];
    defaultReason: string;
    targetSystems: string[];
  }> => {
    const response = await api.get('/api/v1/insights/domain-routing');
    return response.data;
  },
};

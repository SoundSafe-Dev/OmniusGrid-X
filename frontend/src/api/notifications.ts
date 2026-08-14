import { api } from './client';
import { USE_MOCK } from './mockMode';
import { toListResult, type ListResult } from './listResult';
import { registerTransform } from './transformRegistry';

// FS-132: casing handled by the axios seam — TS speaks camelCase, wire speaks
// snake_case. /api/v1/notifications is not on the never-register list, so opt
// in here (minSeverity <-> min_severity, assetId <-> asset_id, createdAt <->
// created_at all ride the shared transform).
registerTransform('/api/v1/notifications');

export type NotificationChannel = 'webhook' | 'slack' | 'email';
export type NotificationSeverity = 'info' | 'warning' | 'error' | 'critical';

export const NOTIFICATION_CHANNELS: NotificationChannel[] = ['webhook', 'slack', 'email'];
export const NOTIFICATION_SEVERITIES: NotificationSeverity[] = [
  'info',
  'warning',
  'error',
  'critical',
];

export interface NotificationSubscription {
  id: string;
  name: string;
  channel: NotificationChannel;
  target: string;
  minSeverity: NotificationSeverity;
  domain: string | null;
  assetId: string | null;
  enabled: boolean;
}

export interface SubscriptionCreate {
  name: string;
  channel: NotificationChannel;
  target: string;
  minSeverity: NotificationSeverity;
  domain?: string | null;
  assetId?: string | null;
  enabled?: boolean;
}

export interface SubscriptionCreated {
  id: string;
  name: string;
  channel: string;
}

export interface NotificationTestEvent {
  severity?: NotificationSeverity;
  title?: string;
  message?: string;
  domain?: string | null;
  assetId?: string | null;
}

export interface NotificationTestResult {
  matched: number;
  results: Array<Record<string, unknown>>;
}

export interface NotificationDeliveryEntry {
  id: string;
  channel: string;
  severity: string;
  title: string;
  delivered: boolean;
  detail: string | null;
  createdAt: string | null;
}

const BASE = '/api/v1/notifications';

const MOCK_DELAY = 200;
const delay = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

let mockSeq = 3;
const mockSubscriptions: NotificationSubscription[] = [
  {
    id: 'sub-1',
    name: 'Ops Slack — criticals',
    channel: 'slack',
    target: 'https://hooks.slack.com/services/T000/B000/demo',
    minSeverity: 'critical',
    domain: null,
    assetId: null,
    enabled: true,
  },
  {
    id: 'sub-2',
    name: 'Maintenance webhook',
    channel: 'webhook',
    target: 'https://ops.example.com/hooks/maintenance',
    minSeverity: 'warning',
    domain: 'maintenance',
    assetId: null,
    enabled: true,
  },
];
const mockLog: NotificationDeliveryEntry[] = [
  {
    id: 'del-1',
    channel: 'slack',
    severity: 'critical',
    title: 'Spindle bearing over temperature',
    delivered: true,
    detail: null,
    createdAt: new Date(Date.now() - 3600_000).toISOString(),
  },
  {
    id: 'del-2',
    channel: 'webhook',
    severity: 'warning',
    title: 'Vibration trend rising on asset-bravo',
    delivered: false,
    detail: 'HTTP 503 from target',
    createdAt: new Date(Date.now() - 7200_000).toISOString(),
  },
];

export const notificationsApi = {
  listSubscriptions: async (): Promise<NotificationSubscription[]> => {
    if (USE_MOCK) {
      await delay(MOCK_DELAY);
      return [...mockSubscriptions];
    }
    const response = await api.get<NotificationSubscription[]>(`${BASE}/subscriptions`);
    return response.data;
  },

  createSubscription: async (body: SubscriptionCreate): Promise<SubscriptionCreated> => {
    if (USE_MOCK) {
      await delay(MOCK_DELAY);
      const sub: NotificationSubscription = {
        id: `sub-${mockSeq++}`,
        name: body.name,
        channel: body.channel,
        target: body.target,
        minSeverity: body.minSeverity,
        domain: body.domain ?? null,
        assetId: body.assetId ?? null,
        enabled: body.enabled ?? true,
      };
      mockSubscriptions.push(sub);
      return { id: sub.id, name: sub.name, channel: sub.channel };
    }
    const response = await api.post<SubscriptionCreated>(`${BASE}/subscriptions`, body);
    return response.data;
  },

  /** Edit a subscription, or just flip it off (P11). Before the PATCH route existed, a
   *  wrong URL or severity meant delete-and-recreate, and the `enabled` column the list
   *  has always returned could be written once at creation and never again. */
  updateSubscription: async (
    subscriptionId: string,
    body: Partial<SubscriptionCreate>,
  ): Promise<NotificationSubscription> => {
    if (USE_MOCK) {
      await delay(MOCK_DELAY);
      const sub = mockSubscriptions.find((s) => s.id === subscriptionId);
      if (sub) Object.assign(sub, body);
      return sub ?? mockSubscriptions[0];
    }
    const response = await api.patch<NotificationSubscription>(
      `${BASE}/subscriptions/${subscriptionId}`,
      body,
    );
    return response.data;
  },

  deleteSubscription: async (subscriptionId: string): Promise<void> => {
    if (USE_MOCK) {
      await delay(MOCK_DELAY);
      const idx = mockSubscriptions.findIndex((s) => s.id === subscriptionId);
      if (idx >= 0) mockSubscriptions.splice(idx, 1);
      return;
    }
    await api.delete(`${BASE}/subscriptions/${subscriptionId}`);
  },

  sendTest: async (event: NotificationTestEvent = {}): Promise<NotificationTestResult> => {
    if (USE_MOCK) {
      await delay(MOCK_DELAY);
      const severity = event.severity ?? 'warning';
      mockLog.unshift({
        id: `del-${Date.now()}`,
        channel: mockSubscriptions[0]?.channel ?? 'webhook',
        severity,
        title: event.title ?? 'Test notification',
        delivered: true,
        detail: null,
        createdAt: new Date().toISOString(),
      });
      return { matched: mockSubscriptions.length, results: [] };
    }
    const response = await api.post<NotificationTestResult>(`${BASE}/test`, event);
    return response.data;
  },

  // ListResult, not a bare array (FS-485). The endpoint selects `limit + 1` and reports the
  // cap in `X-Result-Truncated`; this client discarded it. The log is ordered NEWEST FIRST,
  // so a cap removes the OLDEST deliveries — and the question this page answers is "was that
  // alert delivered?". An absent row read off a page presented as the whole log says "it was
  // never sent", which is a claim about the notification system, not about the query.
  deliveryLog: async (limit = 100): Promise<ListResult<NotificationDeliveryEntry>> => {
    if (USE_MOCK) {
      await delay(MOCK_DELAY);
      // The fixture IS the complete set here, so `truncated: false` is a fact rather than
      // a default — unless the caller asked for fewer rows than the fixture holds.
      const items = mockLog.slice(0, limit);
      return { items, truncated: mockLog.length > limit, limit };
    }
    return toListResult(
      await api.get<NotificationDeliveryEntry[]>(`${BASE}/log`, { params: { limit } }),
    );
  },
};

import { describe, expect, it } from 'vitest';
import type { AxiosResponse, InternalAxiosRequestConfig } from 'axios';
import { requestTransform, responseTransform } from './transformRegistry';
import { notificationsApi } from './notifications';

// Importing ./notifications registers the /api/v1/notifications transform
// prefix as a side effect; these tests pin the wire mapping the client
// relies on (camelCase in TS <-> snake_case on the wire).
describe('notifications transform mapping', () => {
  const req = (url: string, data?: unknown, params?: unknown) =>
    ({ url, data, params, headers: {} }) as InternalAxiosRequestConfig;

  const res = (url: string, data: unknown) =>
    ({ config: { url }, data }) as unknown as AxiosResponse;

  it('snake_cases subscription-create bodies on the way out', () => {
    const out = requestTransform(
      req('/api/v1/notifications/subscriptions', {
        name: 'Ops Slack',
        channel: 'slack',
        target: 'https://hooks.slack.com/x',
        minSeverity: 'critical',
        assetId: 'asset-alpha',
      })
    );
    expect(out.data).toEqual({
      name: 'Ops Slack',
      channel: 'slack',
      target: 'https://hooks.slack.com/x',
      min_severity: 'critical',
      asset_id: 'asset-alpha',
    });
  });

  it('camelizes subscription and delivery-log rows on the way in', () => {
    const subs = responseTransform(
      res('/api/v1/notifications/subscriptions', [
        { id: 's1', name: 'n', channel: 'email', target: 't@example.com',
          min_severity: 'warning', domain: null, asset_id: null, enabled: true },
      ])
    );
    expect(subs.data).toEqual([
      { id: 's1', name: 'n', channel: 'email', target: 't@example.com',
        minSeverity: 'warning', domain: null, assetId: null, enabled: true },
    ]);

    const log = responseTransform(
      res('/api/v1/notifications/log', [
        { id: 'd1', channel: 'webhook', severity: 'error', title: 'x',
          delivered: false, detail: 'HTTP 503', created_at: '2026-07-17T00:00:00Z' },
      ])
    );
    expect(log.data).toEqual([
      { id: 'd1', channel: 'webhook', severity: 'error', title: 'x',
        delivered: false, detail: 'HTTP 503', createdAt: '2026-07-17T00:00:00Z' },
    ]);
  });
});

// Runs in mock mode (VITE_USE_MOCK unset -> mock), so no network needed.
describe('notificationsApi (mock mode)', () => {
  it('create + delete round-trips', async () => {
    const created = await notificationsApi.createSubscription({
      name: 'Test sub',
      channel: 'email',
      target: 'ops@example.com',
      minSeverity: 'error',
    });
    expect(created.id).toBeTruthy();
    const afterCreate = await notificationsApi.listSubscriptions();
    const found = afterCreate.find((s) => s.id === created.id);
    expect(found).toBeDefined();
    expect(found?.minSeverity).toBe('error');
    await notificationsApi.deleteSubscription(created.id);
    const afterDelete = await notificationsApi.listSubscriptions();
    expect(afterDelete.find((s) => s.id === created.id)).toBeUndefined();
  });

  it('send test dispatches to matching subscriptions and logs a delivery', async () => {
    const result = await notificationsApi.sendTest({ severity: 'warning' });
    expect(result.matched).toBeGreaterThanOrEqual(1);
    const log = await notificationsApi.deliveryLog();
    expect(log.length).toBeGreaterThanOrEqual(1);
    expect(log[0]).toHaveProperty('delivered');
    expect(log[0]).toHaveProperty('createdAt');
  });
});

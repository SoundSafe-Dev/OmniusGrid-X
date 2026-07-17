import { describe, it, expect, beforeEach } from 'vitest';
import { useRealtimeStore } from './realtimeStore';

describe('realtimeStore', () => {
  beforeEach(() => {
    useRealtimeStore.getState().reset();
  });

  it('tracks the connection lifecycle', () => {
    const s = useRealtimeStore.getState();
    expect(s.connected).toBe(false);
    s.setConnecting(true);
    s.setConnectionState('connecting');
    expect(useRealtimeStore.getState().connectionState).toBe('connecting');
    s.setConnected(true);
    expect(useRealtimeStore.getState().connected).toBe(true);
  });

  it('caches latest telemetry per asset', () => {
    const s = useRealtimeStore.getState();
    s.updateTelemetry('a1', { timestamp: 't1', metricName: 'temp', value: 20 } as any);
    s.updateTelemetry('a1', { timestamp: 't2', metricName: 'temp', value: 21 } as any);
    s.updateTelemetry('a2', { timestamp: 't1', metricName: 'rpm', value: 900 } as any);
    const t = useRealtimeStore.getState().telemetry;
    expect(t.size).toBe(2);
    expect(t.get('a1')?.value).toBe(21); // latest wins
  });

  it('acknowledges and clears alarms', () => {
    const s = useRealtimeStore.getState();
    s.addAlarm({ id: 'al1', isAcknowledged: false, isActive: true } as any);
    s.acknowledgeAlarm('al1');
    expect(useRealtimeStore.getState().alarms.find(a => a.id === 'al1')?.isAcknowledged).toBe(true);
    // clear marks inactive (with clearedAt) — the alarm stays in the list for history
    s.clearAlarm('al1');
    const cleared = useRealtimeStore.getState().alarms.find(a => a.id === 'al1');
    expect(cleared?.isActive).toBe(false);
    expect(cleared?.clearedAt).toBeTruthy();
  });

  it('tracks PackML state transitions per asset', () => {
    const s = useRealtimeStore.getState();
    s.updateAssetState('a1', 'Execute' as any, '2026-07-11T00:00:00Z');
    s.updateAssetState('a1', 'Held' as any, '2026-07-11T00:01:00Z');
    expect(useRealtimeStore.getState().assetStates.get('a1')?.state).toBe('Held');
  });

  it('caps recent decisions at 50', () => {
    const s = useRealtimeStore.getState();
    for (let i = 0; i < 60; i++) s.addDecision({ id: `d${i}` } as any);
    expect(useRealtimeStore.getState().recentDecisions.length).toBe(50);
  });

  it('reset returns to a clean slate', () => {
    const s = useRealtimeStore.getState();
    s.setConnected(true);
    s.updateTelemetry('a1', { value: 1 } as any);
    s.reset();
    const after = useRealtimeStore.getState();
    expect(after.connected).toBe(false);
    expect(after.telemetry.size).toBe(0);
  });
});

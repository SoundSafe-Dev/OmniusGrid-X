import { create } from 'zustand';
import { Alarm, TelemetryPoint, PackMLState, TacticalDecision } from '../types';

// Task 3: explicit connection lifecycle states for the WebSocket.
export type ConnectionState = 'connecting' | 'connected' | 'disconnected' | 'reconnecting';

interface RealtimeState {
  // Connection
  connected: boolean;
  connecting: boolean;
  connectionState: ConnectionState;
  // True once reconnection attempts are exhausted and the app falls back to polling.
  pollingFallback: boolean;
  lastConnectedAt: Date | null;
  connectionError: string | null;

  // Data caches
  telemetry: Map<string, TelemetryPoint>; // assetId -> latest telemetry
  alarms: Alarm[];
  assetStates: Map<string, { state: PackMLState; changedAt: string }>;
  recentDecisions: TacticalDecision[];

  // Actions
  setConnected: (connected: boolean) => void;
  setConnecting: (connecting: boolean) => void;
  setConnectionState: (state: ConnectionState) => void;
  setPollingFallback: (pollingFallback: boolean) => void;
  setConnectionError: (error: string | null) => void;
  updateTelemetry: (assetId: string, data: TelemetryPoint) => void;
  addAlarm: (alarm: Alarm) => void;
  acknowledgeAlarm: (alarmId: string) => void;
  clearAlarm: (alarmId: string) => void;
  updateAssetState: (assetId: string, state: PackMLState, changedAt: string) => void;
  addDecision: (decision: TacticalDecision) => void;
  reset: () => void;
}

const MAX_RECENT_DECISIONS = 50;

export const useRealtimeStore = create<RealtimeState>((set, get) => ({
  connected: false,
  connecting: false,
  connectionState: 'disconnected',
  pollingFallback: false,
  lastConnectedAt: null,
  connectionError: null,
  telemetry: new Map(),
  alarms: [],
  assetStates: new Map(),
  recentDecisions: [],

  setConnected: (connected) =>
    set({
      connected,
      lastConnectedAt: connected ? new Date() : get().lastConnectedAt,
      connectionError: connected ? null : get().connectionError,
    }),

  setConnecting: (connecting) => set({ connecting }),

  setConnectionState: (connectionState) => set({ connectionState }),

  setPollingFallback: (pollingFallback) => set({ pollingFallback }),

  setConnectionError: (error) => set({ connectionError: error }),

  updateTelemetry: (assetId, data) =>
    set((state) => {
      const newTelemetry = new Map(state.telemetry);
      newTelemetry.set(assetId, data);
      return { telemetry: newTelemetry };
    }),

  addAlarm: (alarm) =>
    set((state) => ({
      alarms: [alarm, ...state.alarms.filter((a) => a.id !== alarm.id)],
    })),

  acknowledgeAlarm: (alarmId) =>
    set((state) => ({
      alarms: state.alarms.map((alarm) =>
        alarm.id === alarmId
          ? { ...alarm, isAcknowledged: true, acknowledgedAt: new Date().toISOString() }
          : alarm
      ),
    })),

  clearAlarm: (alarmId) =>
    set((state) => ({
      alarms: state.alarms.map((alarm) =>
        alarm.id === alarmId
          ? { ...alarm, isActive: false, clearedAt: new Date().toISOString() }
          : alarm
      ),
    })),

  updateAssetState: (assetId, state, changedAt) =>
    set((stateData) => {
      const newStates = new Map(stateData.assetStates);
      newStates.set(assetId, { state, changedAt });
      return { assetStates: newStates };
    }),

  addDecision: (decision) =>
    set((state) => ({
      recentDecisions: [decision, ...state.recentDecisions].slice(0, MAX_RECENT_DECISIONS),
    })),

  reset: () =>
    set({
      connected: false,
      connecting: false,
      connectionState: 'disconnected',
      pollingFallback: false,
      connectionError: null,
      telemetry: new Map(),
      alarms: [],
      assetStates: new Map(),
      recentDecisions: [],
    }),
}));

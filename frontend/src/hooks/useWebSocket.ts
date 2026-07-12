import { useEffect, useCallback } from 'react';
import { websocketManager } from '../api';
import type { ConnectionStatus } from '../api/websocket';
import { useRealtimeStore, useAuthStore } from '../stores';
import { useFallbackPolling } from './useFallbackPolling';
import { TelemetryPoint, Alarm, PackMLState, TacticalDecision } from '../types';

export function useWebSocket() {
  const {
    connected,
    connecting,
    connectionState,
    pollingFallback,
    setConnected,
    setConnecting,
    setConnectionState,
    setPollingFallback,
    setConnectionError,
    updateTelemetry,
    addAlarm,
    updateAssetState,
    addDecision,
  } = useRealtimeStore();

  const { isAuthenticated, accessToken } = useAuthStore();

  // Drives REST polling for alarms + asset state once the socket gives up.
  useFallbackPolling();

  useEffect(() => {
    if (!isAuthenticated) {
      websocketManager.disconnect();
      return;
    }

    setConnecting(true);
    websocketManager.connect(accessToken || undefined);

    const unsubscribeStatus = websocketManager.subscribe<ConnectionStatus>(
      'connection_status',
      ({ connected, state, pollingFallback }) => {
        setConnected(connected);
        setConnecting(state === 'connecting' || state === 'reconnecting');
        setConnectionState(state);
        setPollingFallback(pollingFallback);
      }
    );

    const unsubscribeTelemetry = websocketManager.subscribe<TelemetryPoint & { assetId: string }>(
      'telemetry',
      (data) => {
        const { assetId, ...telemetry } = data;
        updateTelemetry(assetId, telemetry);
      }
    );

    const unsubscribeAlarm = websocketManager.subscribe<Alarm>('alarm', (alarm) => {
      addAlarm(alarm);
    });

    const unsubscribeState = websocketManager.subscribe<{
      assetId: string;
      oldState: PackMLState;
      newState: PackMLState;
      changedAt: string;
    }>('state_change', (data) => {
      updateAssetState(data.assetId, data.newState, data.changedAt);
    });

    const unsubscribeDecision = websocketManager.subscribe<TacticalDecision>(
      'engine_decision',
      (decision) => {
        addDecision(decision);
      }
    );

    return () => {
      unsubscribeStatus();
      unsubscribeTelemetry();
      unsubscribeAlarm();
      unsubscribeState();
      unsubscribeDecision();
    };
  }, [
    isAuthenticated,
    accessToken,
    setConnected,
    setConnecting,
    setConnectionState,
    setPollingFallback,
    setConnectionError,
    updateTelemetry,
    addAlarm,
    updateAssetState,
    addDecision,
  ]);

  const reconnect = useCallback(() => {
    websocketManager.disconnect();
    setConnecting(true);
    websocketManager.connect(accessToken || undefined);
  }, [accessToken, setConnecting]);

  return {
    connected,
    connecting,
    connectionState,
    pollingFallback,
    reconnect,
  };
}

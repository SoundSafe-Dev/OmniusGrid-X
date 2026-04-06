import { useEffect, useCallback } from 'react';
import { websocketManager } from '../api';
import { useRealtimeStore, useAuthStore } from '../stores';
import { TelemetryPoint, Alarm, PackMLState, TacticalDecision } from '../types';

export function useWebSocket() {
  const {
    connected,
    connecting,
    setConnected,
    setConnecting,
    setConnectionError,
    updateTelemetry,
    addAlarm,
    acknowledgeAlarm,
    clearAlarm,
    updateAssetState,
    addDecision,
  } = useRealtimeStore();

  const { isAuthenticated, accessToken } = useAuthStore();

  useEffect(() => {
    if (!isAuthenticated) {
      websocketManager.disconnect();
      return;
    }

    setConnecting(true);
    websocketManager.connect(accessToken || undefined);

    const unsubscribeStatus = websocketManager.subscribe<{ connected: boolean }>(
      'connection_status',
      ({ connected }) => {
        setConnected(connected);
        setConnecting(false);
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
    reconnect,
  };
}

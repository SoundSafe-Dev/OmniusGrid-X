import { useEffect } from 'react';
import { useQueryClient } from 'react-query';
import { useRealtimeStore } from '../stores';

// Task 3: when the WebSocket exhausts its reconnect attempts the app falls back
// to REST polling. We refresh the low-volume, high-value caches (alarms + asset
// state) by invalidating their react-query keys on an interval. Telemetry is
// intentionally NOT polled here — it is high-volume and the gap during a short
// reconnect window is acceptable (confirmed by Hamad).
const FALLBACK_POLL_INTERVAL_MS = 10000; // matches the existing 10s alarm poll cadence
const POLLED_QUERY_KEYS = ['alarms', 'assets', 'dashboard'];

export function useFallbackPolling(): void {
  const queryClient = useQueryClient();
  const pollingFallback = useRealtimeStore((state) => state.pollingFallback);

  useEffect(() => {
    if (!pollingFallback) return;

    const intervalId = window.setInterval(() => {
      POLLED_QUERY_KEYS.forEach((key) => queryClient.invalidateQueries([key]));
    }, FALLBACK_POLL_INTERVAL_MS);

    return () => window.clearInterval(intervalId);
  }, [pollingFallback, queryClient]);
}

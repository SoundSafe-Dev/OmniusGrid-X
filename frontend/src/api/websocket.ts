import { WebSocketMessage } from '../types';

// WS endpoint resolution mirrors client.ts: VITE_WS_URL wins; dev builds hit
// the backend on :8000; production builds use same-origin (nginx proxies /ws),
// upgrading to wss: when the page is https.
//
// EXPORTED SO IT CAN BE TESTED. `fleetHealth.ts` used to open its own socket with a
// hardcoded `ws://`, which fails on any HTTPS deployment; that helper is gone and this is
// the single derivation left. It was correct and nothing asserted it, so a regression to
// `ws://` would have been silent until an operator on an HTTPS deployment noticed the fleet
// had stopped updating — which looks like a quiet fleet, not a broken socket.
export const getWsUrl = (): string => {
  const envUrl = import.meta.env.VITE_WS_URL;
  if (envUrl) return envUrl;
  if (import.meta.env.DEV) {
    // FOLLOW VITE_API_URL WHEN IT IS SET, rather than assuming :8000.
    //
    // `VITE_API_URL` is the documented knob for pointing the dev frontend at a backend,
    // and this branch ignored it — so moving the API to another port gave a socket that
    // retried against nothing, forever, while every HTTP call worked. One backend needed
    // two env vars in agreement and only one of them was written down. Hit while running
    // the app on :8100 during a QA sweep on 2026-08-01.
    //
    // VITE_WS_URL still wins above, for the case where the socket really is elsewhere.
    const apiUrl = import.meta.env.VITE_API_URL;
    if (apiUrl) {
      try {
        const parsed = new URL(apiUrl, window.location.origin);
        const scheme = parsed.protocol === 'https:' ? 'wss' : 'ws';
        return `${scheme}://${parsed.host}/ws`;
      } catch {
        // An unparseable VITE_API_URL is the developer's typo, not a reason to have no
        // socket at all; fall through to the default rather than throwing at module load.
      }
    }
    return `ws://${window.location.hostname || 'localhost'}:8000/ws`;
  }
  const scheme = window.location.protocol === 'https:' ? 'wss' : 'ws';
  return `${scheme}://${window.location.host}/ws`;
};
const WS_URL = getWsUrl();

// Task 3: reconnection/heartbeat tuning. Kept as named constants so behaviour is
// easy to adjust without hunting through the logic.
const MAX_RECONNECT_ATTEMPTS = 6; // attempts 0..5 -> delays 1/2/4/8/16/30s before polling fallback
const RECONNECT_CAP_MS = 30000;
const HEARTBEAT_INTERVAL_MS = 30000; // normal ping cadence
const HEARTBEAT_PROBE_INTERVAL_MS = 15000; // faster cadence once a pong is missed
const MAX_MISSED_PONGS = 3; // probe this many times before marking the link dead

export type ConnectionState = 'connecting' | 'connected' | 'disconnected' | 'reconnecting';

export interface ConnectionStatus {
  connected: boolean;
  state: ConnectionState;
  pollingFallback: boolean;
}

export class WebSocketManager {
  private ws: WebSocket | null = null;
  private reconnectAttempts = 0;
  private maxReconnectAttempts = MAX_RECONNECT_ATTEMPTS;
  private reconnectTimeout: number | null = null;
  // True once the fast-retry budget is exhausted and we are in degraded
  // polling-fallback mode (still retrying the socket in the background).
  private polling = false;
  private listeners: Map<string, Set<(data: any) => void>> = new Map();
  private messageQueue: WebSocketMessage[] = [];

  // Heartbeat state
  private heartbeatTimer: number | null = null;
  private awaitingPong = false;
  private missedPongs = 0;

  // Set when the caller intentionally disconnects, to suppress auto-reconnect.
  private manualClose = false;

  // Last server-side subscription filter, replayed after a reconnect.
  private lastSubscribeMessage: WebSocketMessage | null = null;

  // Last emitted status, so late subscribers (e.g. a header indicator mounting
  // after the socket settled) can read the current state synchronously.
  private lastStatus: ConnectionStatus = {
    connected: false,
    state: 'disconnected',
    pollingFallback: false,
  };

  // The access token rotates (refresh flow writes the new one to localStorage),
  // so it must be read at connect time — never captured once and replayed on
  // reconnect, or re-auth fails after the first rotation.
  private currentToken(): string | undefined {
    return localStorage.getItem('accessToken') || undefined;
  }

  connect(token?: string): void {
    if (this.ws?.readyState === WebSocket.OPEN) return;
    token = token ?? this.currentToken();

    this.manualClose = false;
    // Keep pollingFallback steady while a background attempt is in flight so the
    // REST polling doesn't flicker off and on during degraded mode.
    const initialState = this.reconnectAttempts > 0 || this.polling ? 'reconnecting' : 'connecting';
    this.emitStatus(initialState, this.polling);

    // Token rides the Sec-WebSocket-Protocol header (["bearer.v1", token]) so
    // it never lands in access logs the way ?token= query strings do. The
    // backend echoes "bearer.v1" back to complete the handshake.
    this.ws = token ? new WebSocket(WS_URL, ['bearer.v1', token]) : new WebSocket(WS_URL);

    this.ws.onopen = () => {
      // `debug`, not `log`: this fires on every reconnect (six attempts with backoff
      // before the polling fallback), so at `log` level a flapping link floods the
      // console and buries whatever the operator opened it to see.
      console.debug('WebSocket connected');
      this.reconnectAttempts = 0;
      this.polling = false; // recovered: clears polling fallback via 'connected'
      this.flushMessageQueue();
      this.restoreSubscriptions();
      this.startHeartbeat();
      this.emitStatus('connected');
    };

    this.ws.onmessage = (event) => {
      try {
        const message: WebSocketMessage = JSON.parse(event.data);
        // Heartbeat acknowledgement from the server (websocket.py replies pong).
        if (message.type === 'pong') {
          this.awaitingPong = false;
          this.missedPongs = 0;
          return;
        }
        this.emit(message.type, message.payload);
      } catch (error) {
        console.error('Failed to parse WebSocket message:', error);
      }
    };

    this.ws.onclose = () => {
      console.debug('WebSocket disconnected');
      this.stopHeartbeat();
      if (this.manualClose) {
        this.emitStatus('disconnected');
        return;
      }
      this.scheduleReconnect();
    };

    this.ws.onerror = (error) => {
      console.error('WebSocket error:', error);
    };
  }

  disconnect(): void {
    this.manualClose = true;
    if (this.reconnectTimeout) {
      clearTimeout(this.reconnectTimeout);
      this.reconnectTimeout = null;
    }
    this.stopHeartbeat();
    this.reconnectAttempts = 0;
    this.polling = false;
    this.ws?.close();
    this.ws = null;
    this.emitStatus('disconnected');
  }

  private scheduleReconnect(): void {
    // Fast exponential-backoff budget exhausted: enter degraded polling mode but
    // keep retrying the socket in the background at the cap interval, so the app
    // automatically switches back to WebSocket when the link recovers (per
    // Hamad's fallback design). reconnectAttempts stays at the cap, so a fresh
    // disconnect after a successful reconnect gets a new fast-retry budget.
    if (this.reconnectAttempts >= this.maxReconnectAttempts) {
      if (!this.polling) {
        this.polling = true;
        console.error('Max reconnection attempts reached — falling back to polling; retrying in background');
      }
      this.emitStatus('disconnected', true);
      this.scheduleReconnectTimer(this.jitter(RECONNECT_CAP_MS));
      return;
    }

    const backoff = Math.min(1000 * Math.pow(2, this.reconnectAttempts), RECONNECT_CAP_MS);
    this.reconnectAttempts++;
    this.emitStatus('reconnecting');
    this.scheduleReconnectTimer(this.jitter(backoff));
  }

  // Equal jitter: [delay/2, delay), capped by construction. Spreads a fleet of
  // clients reconnecting after a shared outage so the backend isn't stampeded.
  private jitter(delay: number): number {
    return delay / 2 + Math.random() * (delay / 2);
  }

  private scheduleReconnectTimer(delay: number): void {
    this.reconnectTimeout = window.setTimeout(() => {
      // Re-auth with whatever token is current NOW (it may have rotated since
      // the last connect); connect() falls back to currentToken().
      this.connect();
    }, delay);
  }

  // --- Heartbeat -------------------------------------------------------------
  // Ping every 30s. When a pong is missed, probe every 15s up to MAX_MISSED_PONGS
  // times; if all probes go unanswered the link is treated as dead and closed,
  // which triggers the normal reconnect path.
  private startHeartbeat(): void {
    this.stopHeartbeat();
    this.awaitingPong = false;
    this.missedPongs = 0;
    this.scheduleHeartbeat(HEARTBEAT_INTERVAL_MS);
  }

  private scheduleHeartbeat(delay: number): void {
    this.heartbeatTimer = window.setTimeout(() => this.heartbeatTick(), delay);
  }

  private heartbeatTick(): void {
    if (this.ws?.readyState !== WebSocket.OPEN) return;

    // A previous ping went unanswered before this tick.
    if (this.awaitingPong) {
      this.missedPongs++;
      if (this.missedPongs >= MAX_MISSED_PONGS) {
        console.warn('Heartbeat: connection considered dead, forcing reconnect');
        this.ws.close(); // onclose -> scheduleReconnect
        return;
      }
    }

    this.ws.send(JSON.stringify({ type: 'ping', timestamp: Date.now() }));
    this.awaitingPong = true;

    const nextDelay = this.missedPongs > 0 ? HEARTBEAT_PROBE_INTERVAL_MS : HEARTBEAT_INTERVAL_MS;
    this.scheduleHeartbeat(nextDelay);
  }

  private stopHeartbeat(): void {
    if (this.heartbeatTimer) {
      clearTimeout(this.heartbeatTimer);
      this.heartbeatTimer = null;
    }
    this.awaitingPong = false;
    this.missedPongs = 0;
  }

  // --- Subscriptions ---------------------------------------------------------
  private restoreSubscriptions(): void {
    if (this.lastSubscribeMessage && this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(this.lastSubscribeMessage));
    }
  }

  private flushMessageQueue(): void {
    while (this.messageQueue.length > 0 && this.ws?.readyState === WebSocket.OPEN) {
      const message = this.messageQueue.shift();
      if (message) {
        this.ws.send(JSON.stringify(message));
      }
    }
  }

  send(message: WebSocketMessage): void {
    // Remember the latest subscription so it can be replayed after a reconnect.
    if (message.type === 'subscribe') {
      this.lastSubscribeMessage = message;
    }
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(message));
    } else {
      this.messageQueue.push(message);
    }
  }

  subscribe<T>(eventType: string, callback: (data: T) => void): () => void {
    if (!this.listeners.has(eventType)) {
      this.listeners.set(eventType, new Set());
    }
    this.listeners.get(eventType)!.add(callback);

    return () => {
      this.listeners.get(eventType)?.delete(callback);
    };
  }

  private emit(eventType: string, data: any): void {
    this.listeners.get(eventType)?.forEach((callback) => {
      try {
        callback(data);
      } catch (error) {
        console.error(`Error in ${eventType} listener:`, error);
      }
    });
  }

  private emitStatus(state: ConnectionState, pollingFallback = false): void {
    const status: ConnectionStatus = {
      connected: state === 'connected',
      state,
      pollingFallback,
    };
    this.lastStatus = status;
    this.emit('connection_status', status);
  }

  // Synchronous snapshot of the connection status, for consumers that mount
  // after the last 'connection_status' event was emitted.
  getStatus(): ConnectionStatus {
    return this.lastStatus;
  }

  isConnected(): boolean {
    return this.ws?.readyState === WebSocket.OPEN;
  }
}

export const websocketManager = new WebSocketManager();

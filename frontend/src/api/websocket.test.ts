import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { WebSocketManager } from './websocket'

// Controllable fake WebSocket so we can drive onopen/onmessage deterministically.
class FakeWebSocket {
  static OPEN = 1
  static instances: FakeWebSocket[] = []
  readyState = FakeWebSocket.OPEN
  onopen: ((ev?: any) => void) | null = null
  onmessage: ((ev: any) => void) | null = null
  onclose: (() => void) | null = null
  onerror: (() => void) | null = null
  sent: string[] = []
  constructor(public url: string, public protocols?: string[]) {
    FakeWebSocket.instances.push(this)
  }
  send(data: string) {
    this.sent.push(data)
  }
  close() {
    this.onclose?.()
  }
}

describe('WebSocketManager', () => {
  beforeEach(() => {
    FakeWebSocket.instances = []
    vi.stubGlobal('WebSocket', FakeWebSocket as any)
  })
  afterEach(() => vi.unstubAllGlobals())

  it('delivers messages to subscribers by type', () => {
    const mgr = new WebSocketManager()
    mgr.connect('tok')
    const ws = FakeWebSocket.instances[0]
    ws.onopen?.()

    const received: any[] = []
    mgr.subscribe('telemetry', (d) => received.push(d))

    ws.onmessage?.({ data: JSON.stringify({ type: 'telemetry', payload: { v: 1 } }) })
    expect(received).toEqual([{ v: 1 }])
  })

  it('unsubscribe stops delivery', () => {
    const mgr = new WebSocketManager()
    mgr.connect()
    const ws = FakeWebSocket.instances[0]

    const received: any[] = []
    const off = mgr.subscribe('alarm', (d) => received.push(d))
    off()
    ws.onmessage?.({ data: JSON.stringify({ type: 'alarm', payload: { id: 'a' } }) })
    expect(received).toHaveLength(0)
  })

  it('passes the token via the bearer.v1 subprotocol, not the url', () => {
    const mgr = new WebSocketManager()
    mgr.connect('secret')
    // FS-49: the token must NOT appear in the URL (query strings land in
    // access logs); it rides Sec-WebSocket-Protocol as ['bearer.v1', token].
    expect(FakeWebSocket.instances[0].url).not.toContain('secret')
    expect(FakeWebSocket.instances[0].protocols).toEqual(['bearer.v1', 'secret'])
  })

  // FS-130: resilience — jittered exponential backoff + fresh-token re-auth.
  it('reconnects with exponential backoff (jittered) and the CURRENT token', () => {
    vi.useFakeTimers()
    // Deterministic jitter: equal jitter -> delay = base/2 + 0.5 * base/2 = 0.75 * base
    const rand = vi.spyOn(Math, 'random').mockReturnValue(0.5)
    localStorage.setItem('accessToken', 'tok-1')
    try {
      const mgr = new WebSocketManager()
      mgr.connect('tok-1')
      const ws = FakeWebSocket.instances[0]
      ws.onopen?.()

      // Token rotates while connected; the reconnect must pick up the NEW one.
      localStorage.setItem('accessToken', 'tok-2')
      ws.readyState = 3 // CLOSED, so connect() doesn't early-return
      ws.onclose?.()

      // First retry: base 1000ms -> jittered to 750ms.
      vi.advanceTimersByTime(749)
      expect(FakeWebSocket.instances).toHaveLength(1)
      vi.advanceTimersByTime(1)
      expect(FakeWebSocket.instances).toHaveLength(2)
      expect(FakeWebSocket.instances[1].protocols).toEqual(['bearer.v1', 'tok-2'])

      // Second retry: base doubles to 2000ms -> jittered to 1500ms.
      FakeWebSocket.instances[1].readyState = 3
      FakeWebSocket.instances[1].onclose?.()
      vi.advanceTimersByTime(1499)
      expect(FakeWebSocket.instances).toHaveLength(2)
      vi.advanceTimersByTime(1)
      expect(FakeWebSocket.instances).toHaveLength(3)
      expect(FakeWebSocket.instances[2].protocols).toEqual(['bearer.v1', 'tok-2'])
    } finally {
      rand.mockRestore()
      localStorage.removeItem('accessToken')
      vi.useRealTimers()
    }
  })

  it('exposes the connection status snapshot for late subscribers', () => {
    const mgr = new WebSocketManager()
    expect(mgr.getStatus().state).toBe('disconnected')
    mgr.connect('tok')
    expect(mgr.getStatus().state).toBe('connecting')
    FakeWebSocket.instances[0].onopen?.()
    expect(mgr.getStatus()).toEqual({ connected: true, state: 'connected', pollingFallback: false })
  })
})

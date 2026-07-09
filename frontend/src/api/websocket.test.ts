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
  constructor(public url: string) {
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

  it('passes the token in the connection url', () => {
    const mgr = new WebSocketManager()
    mgr.connect('secret')
    expect(FakeWebSocket.instances[0].url).toContain('token=secret')
  })
})

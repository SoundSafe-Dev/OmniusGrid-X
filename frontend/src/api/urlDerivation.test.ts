import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

/**
 * The API and WebSocket URLs are derived, not configured — so the derivation is the contract.
 *
 * `fleetHealth.ts` used to open its own socket with a hardcoded `ws://`, which fails on any
 * HTTPS deployment; that helper is gone and `getWsUrl` is the single derivation left. It was
 * already correct, and **nothing asserted it**. A regression to `ws://` would have been silent
 * until an operator on an HTTPS deployment noticed the fleet had stopped updating — which looks
 * like a quiet fleet rather than a broken socket, and is the same
 * failure-reads-as-a-fact-about-the-world shape this codebase keeps finding.
 *
 * The equivalent for HTTP is `getApiUrl`, whose production branch returns `''` (same-origin,
 * nginx proxies `/api` and `/ws`). It previously guessed `http://<hostname>:8000`, a port that
 * is not published in production.
 *
 * WHY THE MODULE IS RE-IMPORTED PER CASE. Both helpers are called once at module load and the
 * result is stored in a `const`, so the environment has to be set before the import. That is
 * the same constraint `loadInRealMode` exists for, and the reason `vi.resetModules()` appears
 * in every case here.
 */

const ORIGINAL_LOCATION = window.location

function setLocation(href: string): void {
  const url = new URL(href)
  Object.defineProperty(window, 'location', {
    configurable: true,
    writable: true,
    value: {
      ...ORIGINAL_LOCATION,
      href,
      protocol: url.protocol,
      hostname: url.hostname,
      host: url.host,
      port: url.port,
    },
  })
}

async function wsUrl(): Promise<string> {
  vi.resetModules()
  const mod = await import('./websocket')
  return mod.getWsUrl()
}

async function apiUrl(): Promise<string> {
  vi.resetModules()
  const mod = await import('./client')
  return mod.getApiUrl()
}

beforeEach(() => {
  vi.unstubAllEnvs()
})

afterEach(() => {
  vi.unstubAllEnvs()
  vi.resetModules()
  Object.defineProperty(window, 'location', {
    configurable: true,
    writable: true,
    value: ORIGINAL_LOCATION,
  })
})

describe('the WebSocket scheme follows the page protocol', () => {
  it('uses wss:// on an https page', async () => {
    // THE ASSERTION THIS FILE EXISTS FOR. A browser refuses a ws:// connection from an https
    // page outright, so this is not a preference — it is whether the socket opens at all.
    vi.stubEnv('DEV', false)
    setLocation('https://opsgrid.example.com/dashboard')

    expect(await wsUrl()).toBe('wss://opsgrid.example.com/ws')
  })

  it('uses ws:// on an http page', async () => {
    // The control. A derivation hardcoded to `wss` would satisfy the case above and break
    // every plain-http deployment, which is the mirror of the bug being guarded.
    vi.stubEnv('DEV', false)
    setLocation('http://opsgrid.internal/dashboard')

    expect(await wsUrl()).toBe('ws://opsgrid.internal/ws')
  })

  it('keeps the port, because same-origin means the page port too', async () => {
    vi.stubEnv('DEV', false)
    setLocation('https://opsgrid.example.com:8443/dashboard')

    expect(await wsUrl()).toBe('wss://opsgrid.example.com:8443/ws')
  })

  it('lets VITE_WS_URL win outright', async () => {
    vi.stubEnv('DEV', false)
    vi.stubEnv('VITE_WS_URL', 'wss://ws.example.com/socket')
    setLocation('http://opsgrid.internal/dashboard')

    expect(await wsUrl()).toBe('wss://ws.example.com/socket')
  })

  it('points at :8000 in a dev build', async () => {
    // The dev branch is the one place `ws://` and a hardcoded port are correct: the vite
    // server and the backend are separate origins and the page is plain http.
    vi.stubEnv('DEV', true)
    setLocation('http://localhost:5173/dashboard')

    expect(await wsUrl()).toBe('ws://localhost:8000/ws')
  })

  it('follows VITE_API_URL in dev instead of assuming :8000', async () => {
    // THE DEFECT THIS PAIR GUARDS. `VITE_API_URL` is the documented way to point the dev
    // frontend at a backend, and this branch ignored it — so running the API on any other
    // port gave a socket retrying forever against nothing while every HTTP call succeeded.
    // Hit for real during a QA sweep with the backend on :8100.
    vi.stubEnv('DEV', true)
    vi.stubEnv('VITE_API_URL', 'http://127.0.0.1:8100')
    setLocation('http://localhost:3100/dashboard')

    expect(await wsUrl()).toBe('ws://127.0.0.1:8100/ws')
  })

  it('upgrades to wss when VITE_API_URL is https', async () => {
    vi.stubEnv('DEV', true)
    vi.stubEnv('VITE_API_URL', 'https://staging.example.com')
    setLocation('http://localhost:3100/dashboard')

    expect(await wsUrl()).toBe('wss://staging.example.com/ws')
  })

  it('still lets VITE_WS_URL beat VITE_API_URL', async () => {
    // Order matters: the socket genuinely does live elsewhere on some setups, and the
    // explicit variable has to keep winning over the one that was inferred.
    vi.stubEnv('DEV', true)
    vi.stubEnv('VITE_API_URL', 'http://127.0.0.1:8100')
    vi.stubEnv('VITE_WS_URL', 'ws://elsewhere:9999/socket')
    setLocation('http://localhost:3100/dashboard')

    expect(await wsUrl()).toBe('ws://elsewhere:9999/socket')
  })

  it('falls back to :8000 when VITE_API_URL is unparseable', async () => {
    // A typo in an env var should not leave the app with no socket derivation at all —
    // `new URL()` throws, and this runs at module load.
    vi.stubEnv('DEV', true)
    vi.stubEnv('VITE_API_URL', 'http://[not a url')
    setLocation('http://localhost:5173/dashboard')

    expect(await wsUrl()).toBe('ws://localhost:8000/ws')
  })
})

describe('the API base is same-origin in production', () => {
  it('is empty on a production build', async () => {
    // `''` means "same origin", which is what nginx serves. It used to guess
    // `http://<hostname>:8000` — a port that is not published in production, so every request
    // failed on a deployment that was otherwise correct.
    vi.stubEnv('DEV', false)
    setLocation('https://opsgrid.example.com/dashboard')

    expect(await apiUrl()).toBe('')
  })

  it('points at :8000 in a dev build', async () => {
    vi.stubEnv('DEV', true)
    setLocation('http://localhost:5173/dashboard')

    expect(await apiUrl()).toBe('http://localhost:8000')
  })

  it('lets VITE_API_URL win outright', async () => {
    vi.stubEnv('DEV', true)
    vi.stubEnv('VITE_API_URL', 'https://api.example.com')
    setLocation('http://localhost:5173/dashboard')

    expect(await apiUrl()).toBe('https://api.example.com')
  })

  it('never hardcodes a scheme that contradicts the page', async () => {
    // The pair of derivations must agree: an https page that got a `http://` API base would
    // be blocked as mixed content exactly as a `ws://` socket is.
    vi.stubEnv('DEV', false)
    setLocation('https://opsgrid.example.com/dashboard')

    expect(await apiUrl()).not.toMatch(/^http:/)
    expect(await wsUrl()).not.toMatch(/^ws:\/\//)
  })
})

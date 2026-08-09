import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { loadInRealMode, restoreMockMode } from '../test/realMode'

/**
 * REAL-MODE tests for the historian client (FS-488).
 *
 * One endpoint, and the whole client is a passthrough — which is exactly why the interesting
 * part is the request. `HistorianQueryParams` is camelCase (`assetId`); the endpoint declares
 * `asset_id` as a REQUIRED parameter with no default, so an untransformed request is a 422
 * and the page shows nothing at all.
 *
 * It survives because `historian.ts` calls `registerTransform('/api/v1/historian')` at module
 * load, and the axios request interceptor renames the keys on the way out. **That registration
 * is load-bearing and invisible**: delete the line and every historian query 422s, with no
 * type error and no failing unit test anywhere, because the mock branch reads the camelCase
 * names off the same object and agrees with itself.
 *
 * So the first test below asserts the registration happens. These tests mock `./client`,
 * which replaces axios and its interceptors — so what they see is the pre-transform argument.
 * Asserting the *registration* rather than the transformed URL is the honest version of the
 * check at this layer; the rename itself has its own tests in `transformRegistry.test.ts`.
 *
 * `hasMore` is the other half. `Historian.tsx` renders it as "(more available)" and FS-479
 * put it at the top of the CSV export, so the flag has to survive the client — which here
 * means not being reshaped out of the response body.
 */

const get = vi.fn()
const registerTransform = vi.fn()

vi.mock('./client', () => ({
  api: {
    get: (...args: unknown[]) => get(...args),
    post: vi.fn(),
    patch: vi.fn(),
    put: vi.fn(),
    delete: vi.fn(),
  },
}))
vi.mock('./transformRegistry', () => ({
  registerTransform: (...args: unknown[]) => registerTransform(...args),
}))

type AnyApi = Record<string, (...args: any[]) => Promise<any>>

async function historian(): Promise<AnyApi> {
  const mod = await loadInRealMode(() => import('./historian'))
  return (mod as unknown as { historianApi: AnyApi }).historianApi
}

const RESPONSE = {
  assetId: 'asset-1',
  metric: 'temperature',
  granularity: 'raw',
  start: '2026-08-01T00:00:00Z',
  end: '2026-08-02T00:00:00Z',
  effectiveStart: '2026-08-01T00:00:00Z',
  offset: 0,
  limit: 1000,
  count: 2,
  hasMore: false,
  points: [
    { timestamp: '2026-08-01T00:00:00Z', average: 20, minimum: 19, maximum: 21, sampleCount: 60 },
    { timestamp: '2026-08-01T01:00:00Z', average: 21, minimum: 20, maximum: 22, sampleCount: 60 },
  ],
}

beforeEach(() => {
  get.mockReset()
  registerTransform.mockReset()
  get.mockResolvedValue({ data: RESPONSE })
})

afterEach(() => {
  restoreMockMode()
})

describe('the camel-to-snake registration is load-bearing', () => {
  it('registers the historian prefix on import', async () => {
    // `asset_id` is required with no default, so without this line every query is a 422 and
    // the page renders "Query failed" forever — with no type error and nothing else failing.
    await historian()

    expect(registerTransform).toHaveBeenCalledWith('/api/v1/historian')
  })
})

describe('the query reaches the endpoint with its parameters', () => {
  it('passes the whole parameter object through', async () => {
    const api = await historian()

    const params = {
      assetId: 'asset-1',
      metric: 'temperature',
      start: '2026-08-01T00:00:00Z',
      end: '2026-08-02T00:00:00Z',
      granularity: 'hour',
      offset: 0,
      limit: 500,
    }
    await api.query(params)

    expect(get).toHaveBeenCalledWith('/api/v1/historian/query', { params })
  })

  it('omits the optional ones the caller left out', async () => {
    // An explicit `undefined` granularity is not the same request as no granularity, and
    // the endpoint's own default (`raw`) is what "unspecified" is supposed to mean.
    const api = await historian()

    await api.query({
      assetId: 'asset-1',
      metric: 'temperature',
      start: '2026-08-01T00:00:00Z',
      end: '2026-08-02T00:00:00Z',
    })

    expect(Object.keys(get.mock.calls[0][1].params)).toEqual([
      'assetId',
      'metric',
      'start',
      'end',
    ])
  })
})

describe('the truncation flag survives', () => {
  it('carries hasMore through when the window was capped', async () => {
    // Rendered as "(more available)" on the page and as a PARTIAL preamble at the top of the
    // CSV export (FS-479) — the artefact that leaves the building.
    get.mockResolvedValue({ data: { ...RESPONSE, hasMore: true, count: 500, limit: 500 } })
    const api = await historian()

    const result = await api.query({
      assetId: 'asset-1',
      metric: 'temperature',
      start: '2026-08-01T00:00:00Z',
      end: '2026-08-02T00:00:00Z',
    })

    expect(result.hasMore).toBe(true)
    expect(result.limit).toBe(500)
  })

  it('returns the response unreshaped', async () => {
    const api = await historian()

    expect(
      await api.query({
        assetId: 'asset-1',
        metric: 'temperature',
        start: '2026-08-01T00:00:00Z',
        end: '2026-08-02T00:00:00Z',
      }),
    ).toEqual(RESPONSE)
  })
})

describe('the harness is not testing the mock branch by accident', () => {
  it('reaches the http client at all', async () => {
    // The mock branch synthesises a whole series and never calls `api.get`.
    const api = await historian()

    await api.query({
      assetId: 'asset-1',
      metric: 'temperature',
      start: '2026-08-01T00:00:00Z',
      end: '2026-08-02T00:00:00Z',
    })

    expect(get).toHaveBeenCalled()
  })
})

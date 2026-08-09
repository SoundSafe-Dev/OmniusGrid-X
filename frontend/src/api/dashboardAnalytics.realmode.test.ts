import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { loadInRealMode, restoreMockMode } from '../test/realMode'

/**
 * REAL-MODE tests for the dashboard analytics client (FS-488).
 *
 * Five endpoints, six `USE_MOCK` forks, and a mock branch that computes its own series from
 * `hours` and `bucket` — so in mock mode the parameters are honoured by construction and no
 * test through the fixture can tell whether they were ever sent.
 *
 * WHAT MAKES `bucket` DIFFERENT from the other parameter guards in this family. `kpi`'s
 * `range` falls back silently: `_RANGE_DAYS.get(value, 30)` turns every mistake into a
 * thirty-day answer nobody can spot. `bucket` does not — `resolve_bucket` **raises** on a
 * name it does not know:
 *
 *     if name not in BUCKET_SECONDS:
 *         raise ValueError(f"unsupported bucket '{name}'; expected one of {...}")
 *
 * A drift between `BucketName` and `BUCKET_SECONDS` therefore breaks loudly rather than
 * quietly, which is the better failure and the reason this client needed no fix. What it
 * still needs is a test that the value reaches the request at all: an OMITTED bucket is not
 * an error — the parameter is `Optional[str] = Query(None)` and defaults to `1hour` — so a
 * client that stopped sending it would silently draw hourly buckets on a chart labelled
 * five-minute.
 *
 * The union-versus-registry comparison lives in
 * `backend/tests/test_bucket_names_match_the_backend.py`, because only the backend can see
 * `BUCKET_SECONDS`.
 *
 * A NOTE ON WHAT THESE ASSERT. Mocking `./client` replaces axios and its interceptors, so
 * what is checked here is the argument the client hands to `api.get` — before the
 * camel-to-snake request transform runs. That seam has its own tests
 * (`transformRegistry.test.ts`) and its own backend guard
 * (`test_frontend_query_params_are_declared.py`); splitting them keeps each test about one
 * thing.
 */

const get = vi.fn()

vi.mock('./client', () => ({
  api: {
    get: (...args: unknown[]) => get(...args),
    post: vi.fn(),
    patch: vi.fn(),
    put: vi.fn(),
    delete: vi.fn(),
  },
}))

type AnyApi = Record<string, (...args: any[]) => Promise<any>>

async function analytics(): Promise<AnyApi> {
  const mod = await loadInRealMode(() => import('./dashboardAnalytics'))
  return (mod as unknown as { dashboardAnalyticsApi: AnyApi }).dashboardAnalyticsApi
}

/** The four calls that take an (hours, bucket) pair, and the path each reaches. */
const BUCKETED: Array<[string, string]> = [
  ['getAlarmTrend', '/api/v1/dashboard/alarms/trend'],
  ['getThroughput', '/api/v1/dashboard/throughput'],
  ['getAvailabilityTrend', '/api/v1/dashboard/oee/trend'],
]

beforeEach(() => {
  get.mockReset()
  get.mockResolvedValue({ data: {} })
})

afterEach(() => {
  restoreMockMode()
})

describe('the window and the bucket both reach the request', () => {
  it.each(BUCKETED)('%s sends what it was given', async (method, path) => {
    const api = await analytics()

    await api[method](72, '6hour')

    expect(get).toHaveBeenCalledWith(path, { params: { hours: 72, bucket: '6hour' } })
  })

  it.each(BUCKETED)('%s sends its defaults rather than omitting them', async (method, path) => {
    // `bucket` is `Optional[str] = Query(None)` and defaults to 1hour server-side, so a
    // client that stopped sending it would draw hourly buckets under a five-minute label
    // and nothing would error.
    const api = await analytics()

    await api[method]()

    expect(get).toHaveBeenCalledWith(path, { params: { hours: 24, bucket: '1hour' } })
  })

  it('sends every bucket name the union allows', async () => {
    // `resolve_bucket` raises on an unknown name, so a typo in either list is a 500 rather
    // than a wrong chart — the better failure, and still worth not shipping.
    const api = await analytics()

    for (const bucket of ['5min', '15min', '1hour', '6hour', '1day']) {
      get.mockClear()
      await api.getAlarmTrend(24, bucket)
      expect(get.mock.calls[0][1].params.bucket).toBe(bucket)
    }
  })
})

describe('the two calls that take no bucket', () => {
  it('asks for the health distribution with hours alone', async () => {
    // The control. A client that appended a bucket everywhere would pass every test above
    // and start sending a parameter these endpoints do not declare.
    const api = await analytics()

    await api.getHealthDistribution(48)

    expect(get).toHaveBeenCalledWith('/api/v1/dashboard/health/distribution', {
      params: { hours: 48 },
    })
  })

  it('asks for assets at risk with hours and a limit', async () => {
    const api = await analytics()

    await api.getAssetsAtRisk(12, 10)

    expect(get).toHaveBeenCalledWith('/api/v1/dashboard/assets/at-risk', {
      params: { hours: 12, limit: 10 },
    })
  })
})

describe('the payload is returned as the server sent it', () => {
  it('does not reshape the trend response', async () => {
    const wire = { bucket: '1hour', points: [{ t: '2026-08-06T09:00:00Z', count: 3 }] }
    get.mockResolvedValue({ data: wire })
    const api = await analytics()

    expect(await api.getAlarmTrend(24, '1hour')).toEqual(wire)
  })
})

describe('the harness is not testing the mock branch by accident', () => {
  it('reaches the http client at all', async () => {
    // In mock mode `mockDashboardAnalytics` computes the series locally and `api.get` is
    // never called, so this is the test that notices if `loadInRealMode` stops working.
    const api = await analytics()

    await api.getThroughput()

    expect(get).toHaveBeenCalled()
  })
})

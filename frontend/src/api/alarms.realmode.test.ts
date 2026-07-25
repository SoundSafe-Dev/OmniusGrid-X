import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { loadInRealMode, restoreMockMode } from '../test/realMode'

/**
 * REAL-MODE tests for the alarms client (FS-238).
 *
 * Every other unit test in this project runs with `VITE_USE_MOCK=true` forced by
 * `src/test/setup.ts`, so they all exercise the `if (USE_MOCK)` branch. That branch
 * is not what production runs. The real branch — the paths, the query parameters,
 * the envelope mapping — has never been asserted, which is how the alarms client
 * kept sending an `organization_id` the server had stopped accepting.
 *
 * These tests stub axios rather than the network, so what is verified is the thing
 * that was untested: WHICH request the client builds and HOW it maps the response.
 */

const get = vi.fn()
const post = vi.fn()

vi.mock('./client', () => ({
  api: {
    get: (...args: unknown[]) => get(...args),
    post: (...args: unknown[]) => post(...args),
  },
}))

// The transform registry is a no-op seam here; casing is asserted by its own tests.
vi.mock('./transformRegistry', () => ({ registerTransform: vi.fn() }))

type AnyApi = Record<string, (...args: any[]) => Promise<any>>

async function alarmsApi(): Promise<AnyApi> {
  const mod = await loadInRealMode(() => import('./alarms'))
  return (mod as unknown as { alarmsApi: AnyApi }).alarmsApi
}

beforeEach(() => {
  vi.clearAllMocks()
})

afterEach(() => {
  restoreMockMode()
})

describe('alarmsApi in real mode', () => {
  it('does NOT send organization_id to /alarms/active', async () => {
    // The security-relevant assertion. The endpoint used to accept
    // `organization_id` as an optional query param, so omitting it returned every
    // tenant's alarms and supplying another org's id was obeyed (FS-216). The
    // server no longer accepts it; sending it would be a silent no-op that looks
    // like tenant scoping is being requested.
    get.mockResolvedValue({ data: { count: 0, by_severity: {}, alarms: [] } })
    const api = await alarmsApi()

    await api.getActive('critical')

    expect(get).toHaveBeenCalledTimes(1)
    const [url, config] = get.mock.calls[0] as [string, { params: Record<string, unknown> }]
    expect(url).toBe('/api/v1/alarms/active')
    expect(config.params).toEqual({ severity: 'critical' })
    expect(config.params).not.toHaveProperty('organization_id')
  })

  it('hits the real list path and maps the {items, meta} envelope', async () => {
    get.mockResolvedValue({
      data: {
        items: [{ id: 'a1' }],
        meta: { total: 42, skip: 0, limit: 1, has_more: true },
      },
    })
    const api = await alarmsApi()

    const page = (await api.list({ severity: 'high', skip: 0, limit: 1 })) as {
      items: unknown[]
      total: number
      hasMore: boolean
    }

    expect(get).toHaveBeenCalledWith('/api/v1/alarms/', {
      params: { severity: 'high', skip: 0, limit: 1 },
    })
    // `total` must come from meta, not from items.length — reporting the page size
    // as the total is how a paginated count silently becomes wrong.
    expect(page.total).toBe(42)
    expect(page.items).toHaveLength(1)
    expect(page.hasMore).toBe(true)
  })

  it('translates camelCase filters to the snake_case the API expects', async () => {
    get.mockResolvedValue({ data: { items: [], meta: { total: 0, skip: 0, limit: 100 } } })
    const api = await alarmsApi()

    await api.list({ assetId: 'asset-1', isActive: true, acknowledged: false })

    const [, config] = get.mock.calls[0] as [string, { params: Record<string, unknown> }]
    expect(config.params).toEqual({
      asset_id: 'asset-1',
      is_active: true,
      acknowledged: false,
    })
  })

  it('posts to the acknowledge path with the comment body', async () => {
    post.mockResolvedValue({ data: { id: 'a1', is_acknowledged: true } })
    const api = await alarmsApi()

    await api.acknowledge('a1', { comment: 'on it' })

    expect(post).toHaveBeenCalledWith('/api/v1/alarms/a1/acknowledge', { comment: 'on it' })
  })

  it('is genuinely in real mode — the mock branch would not call axios', async () => {
    // Guards the harness itself. If `loadInRealMode` stopped working, every
    // assertion above would pass vacuously against the mock branch, which returns
    // fixtures without touching `api.get`.
    const { USE_MOCK } = await loadInRealMode(() => import('./mockMode'))
    expect(USE_MOCK).toBe(false)
  })
})

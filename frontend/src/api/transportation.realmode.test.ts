import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { loadInRealMode, restoreMockMode } from '../test/realMode'

/**
 * REAL-MODE tests for the transportation and yard clients.
 *
 * WHAT THESE PIN. Both clients used to send `organization_id` (transportation) and
 * `workcell_id` (yard dock doors) as query parameters. Neither is accepted any more:
 *
 *   * `organization_id` was a REQUIRED client-supplied parameter on carriers, drivers,
 *     shipments and routes — the IDOR shape — and it did not even work, because those
 *     tables have FORCE row-level security while the handler set no tenant GUC, so the
 *     policy filtered every row. Every one of those endpoints returned an empty list to
 *     every caller, including for its own organization. The org now comes from the JWT.
 *
 *   * `workcell_id` was never declared by `GET /yard/dock/doors`, and `dock_doors` has
 *     no workcell column, so it could never have been honoured. FastAPI ignores unknown
 *     query parameters SILENTLY — the request succeeds and returns the unfiltered set,
 *     which the caller then renders as though it were filtered. Only the mock branch,
 *     filtering fixture data on a field the real model lacks, made it look implemented.
 *
 * `test_frontend_query_params_are_declared.py` catches a reintroduction from the
 * backend's side. This catches it from the frontend's, and unlike that guard it runs in
 * the frontend suite where the change would actually be made.
 */

const get = vi.fn()
const post = vi.fn()

vi.mock('./client', () => ({
  api: {
    get: (...args: unknown[]) => get(...args),
    post: (...args: unknown[]) => post(...args),
  },
}))
vi.mock('./transformRegistry', () => ({ registerTransform: vi.fn() }))

type AnyApi = Record<string, (...args: any[]) => Promise<any>>

async function transportApi(): Promise<AnyApi> {
  const mod = await loadInRealMode(() => import('./transportation'))
  return (mod as unknown as { transportationApi: AnyApi }).transportationApi
}

async function yardApi(): Promise<AnyApi> {
  const mod = await loadInRealMode(() => import('./yard'))
  return (mod as unknown as { yardApi: AnyApi }).yardApi
}

function paramsOf(call: unknown[]): Record<string, unknown> {
  const config = call[call.length - 1] as { params?: Record<string, unknown> } | undefined
  return (config && typeof config === 'object' && config.params) || {}
}

beforeEach(() => {
  vi.clearAllMocks()
})

afterEach(() => {
  restoreMockMode()
})

describe('transportationApi in real mode', () => {
  it('does not send organization_id when listing carriers', async () => {
    get.mockResolvedValue({ data: [] })
    const api = await transportApi()

    await api.getCarriers()

    expect(get).toHaveBeenCalledTimes(1)
    const [url] = get.mock.calls[0] as [string]
    expect(url).toBe('/api/v1/transportation/carriers')
    expect(paramsOf(get.mock.calls[0])).not.toHaveProperty('organization_id')
  })

  it('does not send organization_id when listing drivers, but keeps carrier_id', async () => {
    get.mockResolvedValue({ data: [] })
    const api = await transportApi()

    await api.getDrivers('carrier-1')

    const params = paramsOf(get.mock.calls[0])
    expect(params).not.toHaveProperty('organization_id')
    expect(params.carrier_id).toBe('carrier-1')
  })

  it('does not send organization_id when listing shipments', async () => {
    get.mockResolvedValue({ data: { items: [], meta: { total: 0, skip: 0, limit: 0 } } })
    const api = await transportApi()

    await api.getShipments()

    expect(paramsOf(get.mock.calls[0])).not.toHaveProperty('organization_id')
  })
})

describe('yardApi in real mode', () => {
  it('requests dock doors with no query parameters at all', async () => {
    // `workcell_id` was silently ignored by the server, so a filtered request returned
    // every door and looked like a filtered result.
    get.mockResolvedValue({ data: [] })
    const api = await yardApi()

    await api.getDockDoors()

    expect(get).toHaveBeenCalledTimes(1)
    const [url, config] = get.mock.calls[0] as [string, unknown]
    expect(url).toBe('/api/v1/yard/dock/doors')
    expect(config).toBeUndefined()
  })

  it('takes no filter argument, because the column it filtered on does not exist', async () => {
    const api = await yardApi()
    expect(api.getDockDoors.length).toBe(0)
  })
})

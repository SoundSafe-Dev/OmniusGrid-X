import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { loadInRealMode, restoreMockMode } from '../test/realMode'

/**
 * REAL-MODE tests for the assets/workcells client.
 *
 * Every other unit test runs with `VITE_USE_MOCK=true` forced by `src/test/setup.ts`,
 * so they all take the `if (USE_MOCK)` branch. That branch is not what production runs,
 * and the real one — which path, which query parameters — had never been asserted here.
 *
 * WHAT THAT HID. `workcellsApi.list` sent `organization_id`. `GET /api/v1/workcells/`
 * declares only `skip` and `limit`, and **FastAPI drops unknown query parameters
 * silently** — so the request succeeded, returned the caller's own workcells either way,
 * and looked like a filter had been applied. The organisation comes from the JWT; there
 * was never a filter to apply.
 *
 * The backend guard (`test_frontend_query_params_are_declared.py`) could not see it
 * either: the parameters were a ternary rather than an object literal, so the call was
 * neither checked nor counted as skipped. These assertions are the second lock — they
 * hold even if that guard's extractor regresses again.
 */

const get = vi.fn()
const post = vi.fn()
const put = vi.fn()
const patch = vi.fn()

vi.mock('./client', () => ({
  api: {
    get: (...args: unknown[]) => get(...args),
    post: (...args: unknown[]) => post(...args),
    put: (...args: unknown[]) => put(...args),
    patch: (...args: unknown[]) => patch(...args),
  },
}))
vi.mock('./transformRegistry', () => ({ registerTransform: vi.fn() }))

type AnyApi = Record<string, (...args: any[]) => Promise<any>>

async function clients(): Promise<{ workcells: AnyApi; assets: AnyApi }> {
  const mod = await loadInRealMode(() => import('./assets'))
  const m = mod as unknown as { workcellsApi: AnyApi; assetsApi: AnyApi }
  return { workcells: m.workcellsApi, assets: m.assetsApi }
}

beforeEach(() => {
  vi.clearAllMocks()
})

afterEach(() => {
  restoreMockMode()
})

describe('workcellsApi.list in real mode', () => {
  it('calls the endpoint that exists', async () => {
    get.mockResolvedValue({ data: { items: [], meta: { total: 0 } } })
    const { workcells } = await clients()
    await workcells.list()
    expect(get).toHaveBeenCalledWith('/api/v1/workcells/')
  })

  it('sends no tenant identifier even when handed one', async () => {
    // THE ASSERTION THIS FILE EXISTS FOR, and the first version of it was worthless:
    // it called `list()` with no argument, and the OLD code only attached
    // `organization_id` when it was given one — so it passed against the defect.
    // Passing an argument is what makes the check real. The current signature takes
    // none, so this is also the regression test for re-adding the parameter.
    get.mockResolvedValue({ data: { items: [], meta: { total: 0 } } })
    const { workcells } = await clients()
    await workcells.list('11111111-2222-3333-4444-555555555555')
    const serialised = JSON.stringify(get.mock.calls[0])
    expect(serialised).not.toContain('organization_id')
    expect(serialised).not.toContain('organizationId')
    expect(serialised).not.toContain('11111111-2222-3333-4444-555555555555')
  })

  it('unwraps the paginated envelope', async () => {
    // The endpoint returns `{ items, meta }`; a caller typed as an array reads
    // `.map is not a function`. Pinning the unwrap keeps that from coming back.
    get.mockResolvedValue({
      data: { items: [{ id: 'w1', name: 'Line 1' }], meta: { total: 1 } },
    })
    const { workcells } = await clients()
    expect(await workcells.list()).toEqual([{ id: 'w1', name: 'Line 1' }])
  })
})

describe('assetsApi in real mode', () => {
  it('lists assets from the real path', async () => {
    get.mockResolvedValue({ data: { items: [], meta: { total: 0 } } })
    const { assets } = await clients()
    await assets.list()
    expect(get.mock.calls[0][0]).toBe('/api/v1/assets/')
  })

  it('sends no tenant identifier either', async () => {
    get.mockResolvedValue({ data: { items: [], meta: { total: 0 } } })
    const { assets } = await clients()
    await assets.list({ organizationId: '11111111-2222-3333-4444-555555555555' })
    const serialised = JSON.stringify(get.mock.calls[0])
    expect(serialised).not.toContain('organization_id')
    expect(serialised).not.toContain('11111111-2222-3333-4444-555555555555')
  })
})

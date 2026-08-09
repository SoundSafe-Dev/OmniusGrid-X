/**
 * `assetsApi.setMaintenanceMode` sent the flag somewhere the endpoint does not read.
 *
 * It posted `{ inMaintenance }` as a JSON **body**. The endpoint declares
 *
 *     enabled: bool = True
 *
 * and for a scalar FastAPI reads that from the **query string**, not the body. So the body
 * was discarded and `enabled` fell to its default:
 *
 *     setMaintenanceMode(id, false)   ->   POST .../maintenance   ->   enabled = True
 *
 * **Calling it to take an asset out of maintenance put the asset into maintenance.** Not a
 * 422 anyone would have chased — a 200, the opposite of the requested effect, and a
 * response body reading "Game-theoretic engine commands are blocked".
 *
 * This is the fifth defect found in one feature. The column did not exist (migration 053);
 * the write was not tenant-scoped and did not check its rowcount; the tactical engine's
 * read was blind to RLS and treated an invisible row as "available to command";
 * `AssetResponse` never declared the field so no client could see it; and the one call site
 * sent it in a place the server never looks. Each was individually plausible, and the
 * feature could not have worked if any one of them had been the only problem.
 *
 * Asserted against the axios instance rather than a rendered page, because the defect is
 * entirely in the SHAPE of the request — a component test would have to reach through the
 * client to see it, and every existing one mocks the client away.
 */
import { describe, expect, it, vi, beforeEach } from 'vitest'

const post = vi.fn()

vi.mock('./client', () => ({
  api: { post: (...a: unknown[]) => post(...a), get: vi.fn(), put: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}))
// The real mock-mode switch would short-circuit the call entirely.
vi.mock('./mockMode', () => ({ USE_MOCK: false }))

import { assetsApi } from './assets'

beforeEach(() => {
  vi.clearAllMocks()
  post.mockResolvedValue({ data: {} })
})

describe('assetsApi.setMaintenanceMode', () => {
  it('sends enabled=true as a query parameter when enabling', async () => {
    await assetsApi.setMaintenanceMode('a-1', true)
    expect(post).toHaveBeenCalledTimes(1)
    const [url, , config] = post.mock.calls[0]
    expect(url).toBe('/admin/assets/a-1/maintenance')
    expect(config?.params).toEqual({ enabled: true })
  })

  it('sends enabled=false when clearing, rather than nothing at all', async () => {
    // THE ASSERTION THIS FILE EXISTS FOR. With the flag in the body, the query string was
    // empty and the endpoint's `= True` default took over — so this call ENABLED
    // maintenance on an asset somebody was trying to return to service.
    await assetsApi.setMaintenanceMode('a-1', false)
    const [, , config] = post.mock.calls[0]
    expect(config?.params).toEqual({ enabled: false })
  })

  it('does not put the flag in the body, where nothing reads it', async () => {
    // Pinned separately: moving it to the query string while ALSO leaving it in the body
    // would satisfy the two tests above and leave the misleading shape in place for the
    // next reader to copy.
    await assetsApi.setMaintenanceMode('a-1', false)
    const [, body] = post.mock.calls[0]
    expect(JSON.stringify(body ?? null)).not.toContain('inMaintenance')
  })
})

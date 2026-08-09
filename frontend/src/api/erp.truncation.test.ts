/**
 * The client must not discard the truncation signal.
 *
 * `listEntities`, `listEvents` and `listCorrelations` returned bare arrays, so a full
 * page was indistinguishable from the complete set — the same silent-truncation shape
 * that bit three ERP connectors, and now the API reports it in `X-Result-Truncated`.
 *
 * None of these has a production caller yet: the hub's Entities/Events/AI tabs are not
 * built. That is precisely why the shape is pinned now, so whoever builds them receives
 * the flag instead of an array they will assume is everything.
 */
import { describe, expect, it, vi, beforeEach } from 'vitest'

vi.mock('./mockMode', () => ({ USE_MOCK: false }))

const get = vi.fn()
vi.mock('./client', () => ({ api: { get: (...a: unknown[]) => get(...a) } }))

const { erpApi } = await import('./erp')

beforeEach(() => get.mockReset())

describe('ERP list results carry the truncation signal', () => {
  it('reports truncated when the server says the page was cut short', async () => {
    get.mockResolvedValue({
      data: [{ id: '1' }, { id: '2' }],
      headers: { 'x-result-truncated': 'true', 'x-result-limit': '2' },
    })
    const result = await erpApi.listEntities('int-1')
    expect(result.items).toHaveLength(2)
    expect(result.truncated).toBe(true)
    expect(result.limit).toBe(2)
  })

  it('reports not-truncated for a partial page', async () => {
    get.mockResolvedValue({
      data: [{ id: '1' }],
      headers: { 'x-result-truncated': 'false', 'x-result-limit': '200' },
    })
    expect((await erpApi.listEntities('int-1')).truncated).toBe(false)
  })

  it('defaults to not-truncated when the header is absent', async () => {
    // Fail SAFE rather than closed: claiming truncation on every response would make
    // the banner meaningless, and an older server simply does not send the header.
    get.mockResolvedValue({ data: [{ id: '1' }], headers: {} })
    const result = await erpApi.listEntities('int-1')
    expect(result.truncated).toBe(false)
    expect(result.limit).toBe(1)
  })

  it('applies to events and correlations too', async () => {
    get.mockResolvedValue({
      data: [{ id: 'e1' }],
      headers: { 'x-result-truncated': 'true', 'x-result-limit': '1' },
    })
    expect((await erpApi.listEvents('int-1')).truncated).toBe(true)
    expect((await erpApi.listCorrelations()).truncated).toBe(true)
  })

  it('never returns a bare array, so the flag cannot be dropped by accident', async () => {
    get.mockResolvedValue({ data: [], headers: {} })
    for (const result of [
      await erpApi.listEntities('int-1'),
      await erpApi.listEvents('int-1'),
      await erpApi.listCorrelations(),
    ]) {
      expect(Array.isArray(result)).toBe(false)
      expect(result).toHaveProperty('truncated')
    }
  })
})

/**
 * `getRecommendationHistory` must surface both header signals (P4).
 *
 * The route rides two facts in HEADERS: `X-Engine-Not-Running: strategic` (the loop
 * behind this data is not up — a decision log from a dead loop is a snapshot, not a
 * ledger) and `X-Result-Truncated` (a bare array of exactly `limit` rows is
 * indistinguishable from the complete history). The page tests mock this client whole,
 * so nothing there can catch the client dropping a header on the way in — proven the
 * usual way: setting `truncated: false` unconditionally passed every page test. This
 * file is where that mutation dies. Same failure class as FS-459: a flag produced
 * correctly and read by nobody.
 */
import { describe, expect, it, vi } from 'vitest'

vi.mock('./mockMode', () => ({ USE_MOCK: false }))

const get = vi.fn()
vi.mock('./client', () => ({
  api: { get: (...a: unknown[]) => get(...a), post: vi.fn() },
}))

const { enginesApi } = await import('./engines')

// NO beforeEach hook, deliberately (empirically bisected): with any beforeEach
// touching this mock — mockReset or mockClear alike — vitest 4 attributes an
// unhandled rejection to the mockRejectedValue tests, while the identical tests
// with no hook pass. Every test sets its own implementation, so the hook bought
// no isolation; each mockResolvedValue/mockRejectedValue call fully replaces the
// previous behaviour.

const ROW = { recommendationId: 'r1', status: 'approved' }

describe('getRecommendationHistory', () => {
  it('surfaces the truncation header', async () => {
    get.mockResolvedValue({
      data: [ROW],
      headers: { 'x-result-truncated': 'true', 'x-result-limit': '50' },
    })
    const result = await enginesApi.getRecommendationHistory()
    expect(result).not.toBeNull()
    expect(result!.truncated).toBe(true)
    expect(result!.items).toEqual([ROW])
  })

  it('surfaces the engine-stopped header', async () => {
    get.mockResolvedValue({
      data: [],
      headers: { 'x-engine-not-running': 'strategic' },
    })
    const result = await enginesApi.getRecommendationHistory()
    expect(result!.engineStopped).toBe(true)
  })

  it('reads a complete, live response as neither', async () => {
    // NEGATIVE CONTROL: a client that hardcoded both flags true would pass the two
    // tests above and put a permanent warning banner on a healthy engine.
    get.mockResolvedValue({ data: [ROW], headers: {} })
    const result = await enginesApi.getRecommendationHistory()
    expect(result!.truncated).toBe(false)
    expect(result!.engineStopped).toBe(false)
  })

  it('maps a 404 to null — an absent route is not a failed request', async () => {
    // An Error carrying `response`, as axios actually rejects (AxiosError extends
    // Error). The first draft rejected with a bare object, which the suite's
    // unhandled-rejection watchdog flags — a reminder that even test rejections
    // should be shaped like the real thing (rule 188).
    get.mockRejectedValue(
      Object.assign(new Error('Request failed with status code 404'), {
        response: { status: 404 },
      }),
    )
    await expect(enginesApi.getRecommendationHistory()).resolves.toBeNull()
  })

  it('rethrows everything else', async () => {
    get.mockRejectedValue(
      Object.assign(new Error('Request failed with status code 500'), {
        response: { status: 500 },
      }),
    )
    await expect(enginesApi.getRecommendationHistory()).rejects.toThrow(/500/)
  })
})

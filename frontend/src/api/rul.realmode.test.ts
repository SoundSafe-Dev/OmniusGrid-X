import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { loadInRealMode, restoreMockMode } from '../test/realMode'

/**
 * REAL-MODE tests for the remaining-useful-life client (FS-488).
 *
 * `/api/v1/rul` was the first endpoint in this codebase to carry `X-Result-Truncated`, and
 * the reason is recorded in `listResult.ts`: **RUL is computed per asset in Python, so the
 * list is ordered by asset NAME.** Truncation therefore removes the alphabetically-last
 * assets from a view whose entire purpose is spotting the ones about to fail. There is no
 * relationship between where an asset sits in the alphabet and how close it is to failing,
 * so the rows that vanish are an arbitrary subset presented as the complete answer.
 *
 * The mock branch returns four fixed assessments with `truncated: false` — true of a fixture
 * and unable to exercise the flag. What is asserted here is that the real path reads it.
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
vi.mock('./transformRegistry', () => ({ registerTransform: vi.fn() }))

type AnyApi = Record<string, (...args: any[]) => Promise<any>>

async function rul(): Promise<AnyApi> {
  const mod = await loadInRealMode(() => import('./rul'))
  return (mod as unknown as { rulApi: AnyApi }).rulApi
}

const ASSESSMENT = {
  assetId: 'asset-alpha',
  assetName: 'Press 1',
  remainingUsefulLifeHours: 412,
  confidence: 0.81,
  computedAt: '2026-08-06T09:00:00Z',
}

const capped = (items: unknown[], limit: number) => ({
  data: items,
  headers: { 'x-result-truncated': 'true', 'x-result-limit': String(limit) },
})

const complete = (items: unknown[]) => ({ data: items, headers: {} })

beforeEach(() => {
  get.mockReset()
})

afterEach(() => {
  restoreMockMode()
})

describe('a capped assessment list says so', () => {
  it('reads the truncation flag', async () => {
    // The rows dropped are the alphabetically-last assets, which has nothing to do with
    // which are closest to failing — so a capped list presented as complete is not a
    // shorter answer, it is an arbitrary one.
    get.mockResolvedValue(capped([ASSESSMENT], 50))
    const api = await rul()

    const result = await api.listAssessments({ limit: 50 })

    expect(result.truncated).toBe(true)
    expect(result.limit).toBe(50)
  })

  it('does not claim a cap the server did not report', async () => {
    get.mockResolvedValue(complete([ASSESSMENT, { ...ASSESSMENT, assetId: 'asset-bravo' }]))
    const api = await rul()

    const result = await api.listAssessments()

    expect(result.truncated).toBe(false)
    expect(result.limit).toBe(2)
  })

  it('passes its filters through as query parameters', async () => {
    get.mockResolvedValue(complete([]))
    const api = await rul()

    await api.listAssessments({ limit: 10, hours: 48 })

    expect(get).toHaveBeenCalledWith('/api/v1/rul', { params: { limit: 10, hours: 48 } })
  })
})

describe('a single assessment', () => {
  it('asks for the asset it was given, with its options', async () => {
    get.mockResolvedValue({ data: ASSESSMENT })
    const api = await rul()

    await api.getAssessment('asset-alpha', { hours: 24, notify: true })

    expect(get).toHaveBeenCalledWith('/api/v1/rul/asset-alpha', {
      params: { hours: 24, notify: true },
    })
  })

  it('returns the server assessment unaltered', async () => {
    get.mockResolvedValue({ data: ASSESSMENT })
    const api = await rul()

    expect(await api.getAssessment('asset-alpha')).toEqual(ASSESSMENT)
  })
})

describe('the harness is not testing the mock branch by accident', () => {
  it('reaches the http client at all', async () => {
    get.mockResolvedValue(complete([]))
    const api = await rul()

    await api.listAssessments()

    expect(get).toHaveBeenCalled()
  })
})

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { loadInRealMode, restoreMockMode } from '../test/realMode'

/**
 * REAL-MODE tests for the strategic-engine approve/reject calls (FS-379).
 *
 * THE DEFECT. `app/api/engines.py` declares both handlers with bare `str` annotations:
 *
 *     async def approve_recommendation(rec_id: str, operator_id: str, notes: str | None = None)
 *     async def reject_recommendation(rec_id: str, operator_id: str, reason: str)
 *
 * FastAPI reads a bare scalar as a QUERY parameter. The client sent them in the request
 * body, so `operator_id` was always absent and every call came back
 *
 *     422 {"loc": ["query", "operator_id"], "msg": "Field required"}
 *
 * Found by clicking Approve and Reject on /engines/strategic against a real backend on
 * 2026-08-01. Both buttons had never succeeded once.
 *
 * WHY NOTHING CAUGHT IT. `src/test/setup.ts` forces `VITE_USE_MOCK=true`, and the mock
 * branch of these two functions returns `void` without building a request at all — so a
 * passing unit test proved only that the mock returns nothing. There is no assertion
 * anywhere about the request that real mode builds. That is the gap `loadInRealMode`
 * exists to close, and these are the first tests to use it on this client.
 *
 * The tests assert the SHAPE of the outgoing request, which is where the bug lived. They
 * deliberately do not stub the network: what was wrong was never the response handling.
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

async function enginesApi(): Promise<AnyApi> {
  const mod = await loadInRealMode(() => import('./engines'))
  return (mod as unknown as { enginesApi: AnyApi }).enginesApi
}

beforeEach(() => {
  vi.clearAllMocks()
  post.mockResolvedValue({ data: { message: 'ok' } })
})

afterEach(() => {
  restoreMockMode()
})

describe('strategic recommendation decisions in real mode', () => {
  it('sends operator_id as a query parameter, not in the body', async () => {
    const api = await enginesApi()
    await api.approveRecommendation('rec-42', 'operator-7')

    expect(post).toHaveBeenCalledTimes(1)
    const [url, body, config] = post.mock.calls[0]
    expect(url).toBe('/api/v1/engines/strategic/recommendations/rec-42/approve')
    expect(config?.params).toMatchObject({ operator_id: 'operator-7' })
    expect(body ?? null).toBeNull()
  })

  it('does not put operator_id in the body, which is what returned 422', async () => {
    // The assertion stated in the negative as well, because a client that sent the id in
    // BOTH places would satisfy the test above while still being wrong about the contract.
    const api = await enginesApi()
    await api.approveRecommendation('rec-42', 'operator-7', 'looks right')

    const [, body] = post.mock.calls[0]
    expect(JSON.stringify(body ?? null)).not.toContain('operator_id')
  })

  it('passes notes as a query parameter when given', async () => {
    const api = await enginesApi()
    await api.approveRecommendation('rec-42', 'operator-7', 'approved on call')
    expect(post.mock.calls[0][2]?.params).toEqual({
      operator_id: 'operator-7',
      notes: 'approved on call',
    })
  })

  it('omits notes entirely when not given', async () => {
    // `notes` is optional on the server. Sending `notes=undefined` as a query parameter
    // would serialise to an empty string on some stacks, which is a different value from
    // "not supplied" — the server would store an empty note rather than none.
    const api = await enginesApi()
    await api.approveRecommendation('rec-42', 'operator-7')
    expect(post.mock.calls[0][2]?.params).toEqual({ operator_id: 'operator-7' })
    expect('notes' in post.mock.calls[0][2].params).toBe(false)
  })

  it('sends both operator_id and reason as query parameters on reject', async () => {
    // `reason` is REQUIRED by the server, so getting it into the wrong place fails the
    // call exactly as operator_id did.
    const api = await enginesApi()
    await api.rejectRecommendation('rec-9', 'operator-7', 'cost not justified')

    const [url, body, config] = post.mock.calls[0]
    expect(url).toBe('/api/v1/engines/strategic/recommendations/rec-9/reject')
    expect(config?.params).toEqual({
      operator_id: 'operator-7',
      reason: 'cost not justified',
    })
    expect(body ?? null).toBeNull()
  })

  it('encodes the recommendation id into the path', async () => {
    const api = await enginesApi()
    await api.rejectRecommendation('demo-rec-1', 'operator-7', 'demo row')
    expect(post.mock.calls[0][0]).toContain('/recommendations/demo-rec-1/reject')
  })
})

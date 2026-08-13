import { beforeEach, describe, expect, it, vi } from 'vitest'

/**
 * The shop-floor client: 228 lines at **0% coverage** until this file (FS-682).
 *
 * It is the client for a live page — issuing parts, clocking operators in and out,
 * reporting problems, opening and closing downtime — and nothing had ever exercised it.
 * That is the state `broadcast_to_org` was in when the first real exercise of its endpoint
 * found it (FS-678), which is the reason for starting here rather than somewhere larger.
 *
 * NO `USE_MOCK` FORK, which is why `everyMockedClientHasARealModeTest.test.ts` does not
 * cover it and correctly so: that guard exists for clients whose mock branch is tested while
 * the real one is not, and this client has only one branch. It was simply untested.
 *
 * WHAT THESE ASSERT. The path, the method, and the SHAPE of what goes out — because the
 * failure this codebase keeps meeting at that seam is a body sent where the server declared a
 * query parameter, or a field the server never reads (FS-420, FS-658, FS-676). And two
 * response behaviours that are decisions rather than plumbing:
 *
 *   * `openLaborEntry` returns `null` for "no running clock". Null is a real answer, not an
 *     empty collection, and `?? null` is what keeps `undefined` from reaching the page.
 *   * `clockOut(undefined)` sends `notes: null` rather than omitting the key — the server
 *     takes a `ClockOutRequest` body, and an absent key and an explicit null are different
 *     requests.
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

const BASE = '/api/v1/shop-floor'

async function client() {
  const mod = await import('./shopFloor')
  return mod.shopFloorApi as unknown as Record<string, (...args: any[]) => Promise<any>>
}

beforeEach(() => {
  get.mockReset()
  post.mockReset()
})

describe('issuing a part', () => {
  it('posts to the part-issues collection with the caller’s body', async () => {
    post.mockResolvedValue({ data: { id: 'pi-1', partNumber: 'P-9' } })
    const api = await client()
    const body = { partNumber: 'P-9', quantity: 2, unitOfMeasure: 'ea', reason: 'consumed' }

    const result = await api.issuePart(body)

    expect(post).toHaveBeenCalledWith(`${BASE}/part-issues`, body)
    expect(result).toEqual({ id: 'pi-1', partNumber: 'P-9' })
  })

  it('lists them through query parameters, not a body', async () => {
    get.mockResolvedValue({ data: { items: [], total: 0 } })
    const api = await client()

    await api.listPartIssues({ limit: 10, workOrderRef: 'WO-1' })

    expect(get).toHaveBeenCalledWith(`${BASE}/part-issues`, {
      params: { limit: 10, workOrderRef: 'WO-1' },
    })
  })

  it('omits the params object’s contents rather than inventing defaults', async () => {
    get.mockResolvedValue({ data: { items: [], total: 0 } })
    const api = await client()

    await api.listPartIssues()

    expect(get).toHaveBeenCalledWith(`${BASE}/part-issues`, { params: undefined })
  })
})

describe('the labour clock', () => {
  it('clocks in with the body it was given', async () => {
    post.mockResolvedValue({ data: { id: 'le-1' } })
    const api = await client()

    await api.clockIn({ workOrderRef: 'WO-7' })

    expect(post).toHaveBeenCalledWith(`${BASE}/labor/clock-in`, { workOrderRef: 'WO-7' })
  })

  it('clocks out with an explicit null when no note is given', async () => {
    /** An absent key and an explicit null are different requests to a pydantic body. */
    post.mockResolvedValue({ data: { id: 'le-1' } })
    const api = await client()

    await api.clockOut()

    expect(post).toHaveBeenCalledWith(`${BASE}/labor/clock-out`, { notes: null })
  })

  it('passes a note through when there is one', async () => {
    post.mockResolvedValue({ data: { id: 'le-1' } })
    const api = await client()

    await api.clockOut('finished the run')

    expect(post).toHaveBeenCalledWith(`${BASE}/labor/clock-out`, { notes: 'finished the run' })
  })

  it('reports no running clock as null rather than undefined', async () => {
    /** The server's response model is `Optional[LaborEntryOut]`, so a body of `null` is the
     *  ordinary answer. `undefined` reaching the page would render as a loading state. */
    get.mockResolvedValue({ data: null })
    const api = await client()

    expect(await api.openLaborEntry()).toBeNull()
  })

  it('turns a missing body into null too', async () => {
    get.mockResolvedValue({})
    const api = await client()

    expect(await api.openLaborEntry()).toBeNull()
  })

  it('returns the running clock when there is one', async () => {
    get.mockResolvedValue({ data: { id: 'le-9', startedAt: '2026-08-13T00:00:00Z' } })
    const api = await client()

    expect(await api.openLaborEntry()).toEqual({ id: 'le-9', startedAt: '2026-08-13T00:00:00Z' })
  })
})

describe('reporting a problem', () => {
  it('posts to the quality-events collection', async () => {
    post.mockResolvedValue({ data: { id: 'qe-1' } })
    const api = await client()
    const body = { defectType: 'scrap', severity: 'major', quantityAffected: 3 }

    await api.reportProblem(body)

    expect(post).toHaveBeenCalledWith(`${BASE}/quality-events`, body)
  })
})

describe('every call names a real shop-floor path', () => {
  it('sends nothing outside /api/v1/shop-floor', async () => {
    /** The cheap half of `test_frontend_calls_real_endpoints.py`, asserted client-side: a
     *  typo in a path here is a 404 that the page reports as an empty screen. */
    get.mockResolvedValue({ data: null })
    post.mockResolvedValue({ data: {} })
    const api = await client()

    await api.listPartIssues()
    await api.openLaborEntry()
    await api.issuePart({ partNumber: 'P', quantity: 1, unitOfMeasure: 'ea', reason: 'r' })
    await api.clockIn({})
    await api.clockOut()
    await api.reportProblem({ defectType: 'd', severity: 's', quantityAffected: 1 })

    const paths = [...get.mock.calls, ...post.mock.calls].map((call) => call[0] as string)
    expect(paths.length).toBeGreaterThanOrEqual(6)
    for (const p of paths) expect(p.startsWith(BASE)).toBe(true)
  })
})

describe('downtime', () => {
  it('starts against the asset', async () => {
    post.mockResolvedValue({ data: { id: 'dt-1' } })
    const api = await client()

    await api.startDowntime({ assetId: 'a-1', downtimeType: 'unplanned' })

    expect(post).toHaveBeenCalledWith(`${BASE}/downtime/start`, {
      assetId: 'a-1',
      downtimeType: 'unplanned',
    })
  })

  it('ends the named event, sending an object rather than undefined', async () => {
    /** `body ?? {}` — a POST with an undefined body and one with `{}` are different
     *  requests, and the server declares a body model. */
    post.mockResolvedValue({ data: { id: 'dt-1' } })
    const api = await client()

    await api.endDowntime('dt-1')

    expect(post).toHaveBeenCalledWith(`${BASE}/downtime/dt-1/end`, {})
  })

  it('passes a closing reason through when given one', async () => {
    post.mockResolvedValue({ data: { id: 'dt-1' } })
    const api = await client()

    await api.endDowntime('dt-1', { reasonCode: 'repaired' })

    expect(post).toHaveBeenCalledWith(`${BASE}/downtime/dt-1/end`, { reasonCode: 'repaired' })
  })
})

describe('the postings ledger', () => {
  it('returns a well-formed page', async () => {
    get.mockResolvedValue({ data: { items: [{ id: 'p-1' }], total: 1 } })
    const api = await client()

    expect(await api.listPostings({ outstandingOnly: true })).toEqual({
      items: [{ id: 'p-1' }],
      total: 1,
    })
    expect(get).toHaveBeenCalledWith(`${BASE}/postings`, {
      params: { outstandingOnly: true },
    })
  })

  it.each([
    ['no body at all', undefined],
    ['items that are not a list', { items: 'nope', total: 0 }],
    ['a total that is not a number', { items: [], total: null }],
  ])('refuses %s rather than rendering an empty ledger', async (_label, data) => {
    /** THE DISTINCTION THIS CLIENT EXISTS TO KEEP. An empty postings ledger means "nothing
     *  is waiting"; a malformed response means "we do not know". Rendering the second as
     *  the first tells an operator every event has landed when none may have. */
    get.mockResolvedValue({ data })
    const api = await client()

    await expect(api.listPostings()).rejects.toThrow(/items and a total/)
  })

  it('acknowledges with an explicit null reference when none is given', async () => {
    post.mockResolvedValue({ data: { id: 'p-1', status: 'acknowledged' } })
    const api = await client()

    await api.acknowledgePosting('p-1')

    expect(post).toHaveBeenCalledWith(`${BASE}/postings/p-1/acknowledge`, { externalRef: null })
  })

  it('passes the external reference through when there is one', async () => {
    post.mockResolvedValue({ data: { id: 'p-1' } })
    const api = await client()

    await api.acknowledgePosting('p-1', 'ERP-42')

    expect(post).toHaveBeenCalledWith(`${BASE}/postings/p-1/acknowledge`, {
      externalRef: 'ERP-42',
    })
  })
})

describe('the routing map', () => {
  it('is fetched from the routing endpoint', async () => {
    get.mockResolvedValue({ data: { routing: {}, targetSystems: [], postingStatuses: {} } })
    const api = await client()

    await api.routing()

    expect(get).toHaveBeenCalledWith(`${BASE}/routing`)
  })
})

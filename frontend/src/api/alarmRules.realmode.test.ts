import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { loadInRealMode, restoreMockMode } from '../test/realMode'

/**
 * REAL-MODE tests for the alarm-rules client (FS-488).
 *
 * This is the only client here that RESHAPES its response: the endpoint returns
 * `{items, meta}` and the client flattens it into the `PaginatedResponse` its callers expect.
 * The mock branch returns that flat shape directly, so the reshaping code — the part that can
 * actually be wrong — runs only in production.
 *
 * `hasMore` is read with a triple fallback:
 *
 *     meta.hasMore ?? meta.has_more ?? meta.skip + items.length < meta.total
 *
 * which is a client hedging about its own wire. All three branches are asserted here, and the
 * computed one matters most: it is what runs when the server sends neither spelling, and a
 * wrong `hasMore` on a paginated rules list means an operator believes they have seen every
 * rule that governs their alarms.
 *
 * THE TRAILING SLASH IS DELIBERATE. `list` and `create` post to `/api/v1/alarm-rules/`, and
 * the router declares `@router.get("/")` and `@router.post("/")` under a
 * `/api/v1/alarm-rules` prefix — so the slash is the exact path, not a redirect. It was
 * checked rather than assumed, and it is asserted below so nobody "tidies" it into a 307.
 */

const get = vi.fn()
const post = vi.fn()
const patch = vi.fn()
const del = vi.fn()

vi.mock('./client', () => ({
  api: {
    get: (...args: unknown[]) => get(...args),
    post: (...args: unknown[]) => post(...args),
    patch: (...args: unknown[]) => patch(...args),
    delete: (...args: unknown[]) => del(...args),
    put: vi.fn(),
  },
}))
vi.mock('./transformRegistry', () => ({ registerTransform: vi.fn() }))

type AnyApi = Record<string, (...args: any[]) => Promise<any>>

async function alarmRules(): Promise<AnyApi> {
  const mod = await loadInRealMode(() => import('./alarmRules'))
  return (mod as unknown as { alarmRulesApi: AnyApi }).alarmRulesApi
}

const RULE = {
  id: 'rule-1',
  name: 'Press 1 over temperature',
  metricName: 'temperature',
  comparator: 'gt',
  threshold: 80,
  severity: 'high',
  isEnabled: true,
}

const envelope = (items: unknown[], meta: Record<string, unknown>) => ({
  data: { items, meta },
})

beforeEach(() => {
  get.mockReset()
  post.mockReset()
  patch.mockReset()
  del.mockReset()
})

afterEach(() => {
  restoreMockMode()
})

describe('the envelope is flattened for callers', () => {
  it('lifts total, skip and limit out of meta', async () => {
    get.mockResolvedValue(envelope([RULE], { total: 12, skip: 0, limit: 20, hasMore: false }))
    const api = await alarmRules()

    const page = await api.list()

    expect(page.items).toEqual([RULE])
    expect(page.total).toBe(12)
    expect(page.skip).toBe(0)
    expect(page.limit).toBe(20)
  })

  it('prefers the camelCase hasMore when the server sends it', async () => {
    get.mockResolvedValue(envelope([RULE], { total: 50, skip: 0, limit: 20, hasMore: true }))
    const api = await alarmRules()

    expect((await api.list()).hasMore).toBe(true)
  })

  it('accepts the snake_case spelling', async () => {
    get.mockResolvedValue(envelope([RULE], { total: 50, skip: 0, limit: 20, has_more: true }))
    const api = await alarmRules()

    expect((await api.list()).hasMore).toBe(true)
  })

  it('computes it when the server sends neither', async () => {
    // The branch that runs when the hedge is needed. A wrong answer here tells an operator
    // they have seen every rule governing their alarms when they have seen the first page.
    get.mockResolvedValue(envelope([RULE], { total: 50, skip: 0, limit: 20 }))
    const api = await alarmRules()

    expect((await api.list()).hasMore).toBe(true)
  })

  it('computes false on the last page', async () => {
    // The other direction: a client that always computed `true` would pass the test above
    // and put a permanent "there is more" under a complete list.
    get.mockResolvedValue(envelope([RULE], { total: 41, skip: 40, limit: 20 }))
    const api = await alarmRules()

    expect((await api.list()).hasMore).toBe(false)
  })
})

describe('filters are renamed on the way out', () => {
  it('sends metric_name, severity and is_enabled', async () => {
    get.mockResolvedValue(envelope([], { total: 0, skip: 0, limit: 20 }))
    const api = await alarmRules()

    await api.list({ metricName: 'temperature', severity: 'high', isEnabled: true })

    expect(get).toHaveBeenCalledWith('/api/v1/alarm-rules/', {
      params: { metric_name: 'temperature', severity: 'high', is_enabled: true },
    })
  })

  it('sends is_enabled false rather than dropping it', async () => {
    // `if (filters?.isEnabled !== undefined)` exists precisely so `false` survives. A truthy
    // check here would silently turn "show me the disabled rules" into "show me everything",
    // and a disabled alarm rule listed among the active ones is the wrong direction to err.
    get.mockResolvedValue(envelope([], { total: 0, skip: 0, limit: 20 }))
    const api = await alarmRules()

    await api.list({ isEnabled: false })

    expect(get.mock.calls[0][1].params).toEqual({ is_enabled: false })
  })

  it('sends nothing when no filter was given', async () => {
    get.mockResolvedValue(envelope([], { total: 0, skip: 0, limit: 20 }))
    const api = await alarmRules()

    await api.list()

    expect(get.mock.calls[0][1].params).toEqual({})
  })
})

describe('the paths are the ones the router declares', () => {
  it('lists and creates on the trailing slash', async () => {
    // The router declares `@router.get("/")` and `@router.post("/")`. Dropping the slash
    // would make both a 307 redirect rather than the route.
    get.mockResolvedValue(envelope([], { total: 0, skip: 0, limit: 20 }))
    post.mockResolvedValue({ data: RULE })
    const api = await alarmRules()

    await api.list()
    await api.create({ name: 'x', metricName: 'temperature', comparator: 'gt', threshold: 80 })

    expect(get.mock.calls[0][0]).toBe('/api/v1/alarm-rules/')
    expect(post.mock.calls[0][0]).toBe('/api/v1/alarm-rules/')
  })

  it('addresses a single rule without one', async () => {
    get.mockResolvedValue({ data: RULE })
    patch.mockResolvedValue({ data: RULE })
    del.mockResolvedValue({ data: {} })
    const api = await alarmRules()

    await api.get('rule-1')
    await api.update('rule-1', { threshold: 90 })
    await api.remove('rule-1')

    expect(get.mock.calls[0][0]).toBe('/api/v1/alarm-rules/rule-1')
    expect(patch.mock.calls[0][0]).toBe('/api/v1/alarm-rules/rule-1')
    expect(del.mock.calls[0][0]).toBe('/api/v1/alarm-rules/rule-1')
  })
})

describe('the harness is not testing the mock branch by accident', () => {
  it('reaches the http client at all', async () => {
    get.mockResolvedValue(envelope([], { total: 0, skip: 0, limit: 20 }))
    const api = await alarmRules()

    await api.list()

    expect(get).toHaveBeenCalled()
  })
})

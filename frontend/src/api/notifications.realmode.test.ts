import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { loadInRealMode, restoreMockMode } from '../test/realMode'

/**
 * REAL-MODE tests for the notifications client (FS-487).
 *
 * Six `USE_MOCK` forks, and the mock branch is a small working notification system: it keeps
 * `mockSubscriptions` and `mockLog` arrays, pushes on create, splices on delete, and unshifts
 * a delivery row on test. Every existing test of this page runs through that, so what has
 * never been exercised is the four requests it stands in for.
 *
 * **`matched` is the number the whole page turns on.** The mock returns
 * `mockSubscriptions.length` — every subscription, always, regardless of the severity, domain
 * and asset filters the server applies. So in mock mode a test dispatch always matches
 * everything, and the case worth seeing — nothing matched, the event reached nobody — cannot
 * occur. The real path must return the server's count untouched, including zero, because the
 * page now says something different about zero (FS-487).
 *
 * **The delivery log is a `ListResult` since FS-485.** The endpoint selects `limit + 1` and
 * reports the cap in `X-Result-Truncated`; this client used to return the body alone. The log
 * is newest-first, so a cap removes the OLDEST attempts, and the question the page answers is
 * "was that alert delivered?" — a row absent from a list presented as complete says the alert
 * was never sent.
 */

const get = vi.fn()
const post = vi.fn()
const del = vi.fn()

vi.mock('./client', () => ({
  api: {
    get: (...args: unknown[]) => get(...args),
    post: (...args: unknown[]) => post(...args),
    delete: (...args: unknown[]) => del(...args),
    put: vi.fn(),
    patch: vi.fn(),
  },
}))

type AnyApi = Record<string, (...args: any[]) => Promise<any>>

async function notifications(): Promise<AnyApi> {
  const mod = await loadInRealMode(() => import('./notifications'))
  return (mod as unknown as { notificationsApi: AnyApi }).notificationsApi
}

const DELIVERY = {
  id: 'del-1',
  channel: 'webhook',
  severity: 'warning',
  title: 'Test notification',
  delivered: true,
  detail: null,
  createdAt: '2026-08-06T09:00:00Z',
}

const capped = (items: unknown[], limit: number) => ({
  data: items,
  headers: { 'x-result-truncated': 'true', 'x-result-limit': String(limit) },
})

const complete = (items: unknown[]) => ({ data: items, headers: {} })

beforeEach(() => {
  get.mockReset()
  post.mockReset()
  del.mockReset()
})

afterEach(() => {
  restoreMockMode()
})

describe('the delivery log carries its cap', () => {
  it('reads the truncation flag off the response', async () => {
    get.mockResolvedValue(capped([DELIVERY], 100))
    const api = await notifications()

    const log = await api.deliveryLog(100)

    expect(log.truncated).toBe(true)
    expect(log.limit).toBe(100)
    expect(log.items).toEqual([DELIVERY])
  })

  it('does not claim a cap the server did not report', async () => {
    // A client hard-coding `truncated: true` would pass the test above and put a permanent
    // "there is more" on a log that is complete.
    get.mockResolvedValue(complete([DELIVERY]))
    const api = await notifications()

    expect((await api.deliveryLog(100)).truncated).toBe(false)
  })

  it('asks for the limit it was given', async () => {
    get.mockResolvedValue(complete([]))
    const api = await notifications()

    await api.deliveryLog(25)

    expect(get).toHaveBeenCalledWith('/api/v1/notifications/log', { params: { limit: 25 } })
  })
})

describe('the test dispatch returns the server count', () => {
  it('passes zero through rather than reporting a match', async () => {
    // The case the mock cannot produce — it returns `mockSubscriptions.length`, so in mock
    // mode a test always matches everything. Zero means the event reached nobody, which is
    // the one thing pressing Test is meant to find out.
    post.mockResolvedValue({ data: { matched: 0, results: [] } })
    const api = await notifications()

    expect((await api.sendTest({ severity: 'warning' })).matched).toBe(0)
  })

  it('passes a real count through', async () => {
    post.mockResolvedValue({ data: { matched: 3, results: [{ id: 'del-1' }] } })
    const api = await notifications()

    const result = await api.sendTest({ severity: 'critical' })

    expect(result.matched).toBe(3)
    expect(result.results).toHaveLength(1)
  })

  it('sends the event to the test endpoint', async () => {
    post.mockResolvedValue({ data: { matched: 0, results: [] } })
    const api = await notifications()

    await api.sendTest({ severity: 'critical', title: 'drill' })

    expect(post).toHaveBeenCalledWith('/api/v1/notifications/test', {
      severity: 'critical',
      title: 'drill',
    })
  })
})

describe('subscriptions are created and removed on the server', () => {
  it('posts the subscription and returns what the server assigned', async () => {
    // The mock SYNTHESISES the id. A real path returning the request rather than the
    // response would show an id no server ever issued, and the delete that followed would
    // 404 on a row that looks present.
    post.mockResolvedValue({ data: { id: 'sub-server', name: 'Ops webhook', channel: 'webhook' } })
    const api = await notifications()

    const created = await api.createSubscription({
      name: 'Ops webhook',
      channel: 'webhook',
      target: 'https://hooks.example.com/x',
      minSeverity: 'warning',
    })

    expect(post).toHaveBeenCalledWith(
      '/api/v1/notifications/subscriptions',
      expect.objectContaining({ name: 'Ops webhook' }),
    )
    expect(created.id).toBe('sub-server')
  })

  it('deletes by id', async () => {
    del.mockResolvedValue({ data: {} })
    const api = await notifications()

    await api.deleteSubscription('sub-1')

    expect(del).toHaveBeenCalledWith('/api/v1/notifications/subscriptions/sub-1')
  })

  it('lists subscriptions from the subscriptions endpoint', async () => {
    get.mockResolvedValue({ data: [{ id: 'sub-1', name: 'Ops webhook', channel: 'webhook' }] })
    const api = await notifications()

    await api.listSubscriptions()

    expect(get).toHaveBeenCalledWith('/api/v1/notifications/subscriptions')
  })
})

describe('the harness is not testing the mock branch by accident', () => {
  it('reaches the http client at all', async () => {
    // In mock mode none of these calls touches `api`. If `loadInRealMode` stopped working,
    // every assertion above would run against the in-memory arrays and prove nothing.
    get.mockResolvedValue(complete([]))
    const api = await notifications()

    await api.deliveryLog()

    expect(get).toHaveBeenCalled()
  })
})

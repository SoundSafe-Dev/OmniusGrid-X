import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { loadInRealMode, restoreMockMode } from '../test/realMode'

/**
 * REAL-MODE tests for the analysis-sessions client (FS-485).
 *
 * The largest client without one: 503 lines and **eighteen** `USE_MOCK` forks, backing the
 * correlation assistant. Every unit test in this repository runs with `VITE_USE_MOCK=true`
 * stubbed before any module evaluates, so until now every one of those eighteen forks was
 * exercised on its mock side and none on the side that ships.
 *
 * The two properties here are the ones the mock branch cannot check, because in mock mode
 * they are true by construction:
 *
 * **Truncation is read, not assumed** (FS-459). Three of these endpoints return a bare JSON
 * array capped at `limit` and report the cap in `X-Result-Truncated`. The mock branch returns
 * the whole fixture and says `truncated: false`, which is a fact there. On the real path the
 * flag has to come off the response headers, and if it stops arriving the pane shows the
 * start of a conversation and silently omits what was just said. Messages are ordered
 * OLDEST FIRST, so truncation removes the recent half — the half somebody is looking at.
 *
 * Search is the sharpest of the three: a capped result means matches EXIST that the user was
 * not shown, and a search box that quietly omits hits is worse than one that finds nothing,
 * because the user concludes the thing is not there.
 *
 * **`simulated` is carried, never defaulted.** The mock branch sets `simulated: true` on
 * purpose — it contacted no backend, and returning `false` would make the demo the one place
 * claiming a real inference with the most confidence. The real path must pass through
 * whatever the server said, including *absent*: the server sets it when a reply is a
 * heuristic or an error fallback rather than an inference, and a client that defaulted it to
 * `false` would put the confident version back in front of the operator. `CorrelationAIPane`
 * renders that flag; this is the other end of the same wire.
 */

const get = vi.fn()
const post = vi.fn()

vi.mock('./client', () => ({
  api: {
    get: (...args: unknown[]) => get(...args),
    post: (...args: unknown[]) => post(...args),
    put: vi.fn(),
    patch: vi.fn(),
    delete: vi.fn(),
  },
}))

type AnyApi = Record<string, (...args: any[]) => Promise<any>>

async function sessions(): Promise<AnyApi> {
  const mod = await loadInRealMode(() => import('./analysisSessions'))
  return (mod as unknown as { analysisSessionsApi: AnyApi }).analysisSessionsApi
}

const message = (over: Record<string, unknown> = {}) => ({
  id: 'm1',
  session_id: 'sess-1',
  role: 'assistant',
  content: 'Press 1 has been late on three of the last five shifts.',
  timestamp: '2026-08-06T09:00:00Z',
  ...over,
})

/** An axios response carrying the truncation headers the server sends. */
const capped = (items: unknown[], limit: number) => ({
  data: items,
  headers: { 'x-result-truncated': 'true', 'x-result-limit': String(limit) },
})

const complete = (items: unknown[]) => ({ data: items, headers: {} })

beforeEach(() => {
  get.mockReset()
  post.mockReset()
})

afterEach(() => {
  restoreMockMode()
})

describe('a capped page says so on the real path (FS-459)', () => {
  it('reads the truncation flag off the message list', async () => {
    get.mockResolvedValue(capped([message()], 1))
    const api = await sessions()

    const result = await api.getSessionMessages('sess-1', 1, 0)

    expect(result.truncated).toBe(true)
    expect(result.limit).toBe(1)
    expect(result.items).toHaveLength(1)
  })

  it('does not claim truncation when the server sent none', async () => {
    // The other direction. A client that hard-coded `truncated: true` would pass the test
    // above and put a permanent "there is more" on every complete conversation.
    get.mockResolvedValue(complete([message(), message({ id: 'm2' })]))
    const api = await sessions()

    const result = await api.getSessionMessages('sess-1')

    expect(result.truncated).toBe(false)
    expect(result.limit).toBe(2)
  })

  it('reads it off the cross-session history too', async () => {
    get.mockResolvedValue(capped([message()], 100))
    const api = await sessions()

    expect((await api.getChatHistory(100, 0)).truncated).toBe(true)
  })

  it('reads it off search, where a dropped hit is a wrong answer', async () => {
    // A capped search means matches exist that were not shown. The user reads the absence
    // as "it is not there", which is a conclusion, not a missing row.
    get.mockResolvedValue(capped([message()], 50))
    const api = await sessions()

    expect((await api.searchChatHistory('bearing', 50, 0)).truncated).toBe(true)
  })
})

describe('the real path asks the endpoints it claims to', () => {
  it('requests messages with the limit and offset it was given', async () => {
    get.mockResolvedValue(complete([]))
    const api = await sessions()

    await api.getSessionMessages('sess-9', 25, 50)

    expect(get).toHaveBeenCalledWith('/api/v1/nlp/sessions/sess-9/messages', {
      params: { limit: 25, offset: 50 },
    })
  })

  it('passes the search query as `q`, not as the message body', async () => {
    // The mock branch filters the fixture in JavaScript, so a wrong parameter name here
    // would look correct in every existing test and return the whole history in production.
    get.mockResolvedValue(complete([]))
    const api = await sessions()

    await api.searchChatHistory('bearing', 50, 0, 'sess-3')

    expect(get).toHaveBeenCalledWith('/api/v1/nlp/sessions/chat/search', {
      params: { q: 'bearing', limit: '50', offset: '0', session_id: 'sess-3' },
    })
  })

  it('omits session_id from history when none was asked for', async () => {
    get.mockResolvedValue(complete([]))
    const api = await sessions()

    await api.getChatHistory(10, 0)

    const params = get.mock.calls[0][1].params
    expect(params).not.toHaveProperty('session_id')
  })
})

describe('`simulated` is carried, never defaulted', () => {
  it('passes a simulated reply through with its reason', async () => {
    // The server sets this when the reply is a heuristic or an error fallback rather than
    // an inference. A client that dropped it would put the confident version back on screen.
    post.mockResolvedValue({
      data: {
        role: 'assistant',
        content: 'Based on the last recorded values…',
        timestamp: '2026-08-06T09:00:00Z',
        simulated: true,
        simulation_reason: 'correlation model unavailable; heuristic reply',
      },
    })
    const api = await sessions()

    const reply = await api.sessionChat('sess-1', { message: 'why?', auto_integrate: false })

    expect(reply.simulated).toBe(true)
    expect(reply.simulation_reason).toMatch(/heuristic/)
  })

  it('does not invent `simulated: false` when the server omitted it', async () => {
    // The direction that matters. Defaulting to `false` is a claim — "this was a real
    // inference" — made by the client about something it cannot know.
    post.mockResolvedValue({
      data: { role: 'assistant', content: 'ok', timestamp: '2026-08-06T09:00:00Z' },
    })
    const api = await sessions()

    const reply = await api.sessionChat('sess-1', { message: 'why?', auto_integrate: false })

    expect(reply.simulated).toBeUndefined()
  })

  it('posts the chat to the session it names', async () => {
    post.mockResolvedValue({ data: { role: 'assistant', content: '', timestamp: 'x' } })
    const api = await sessions()

    await api.sessionChat('sess-7', { message: 'why?', auto_integrate: true })

    expect(post).toHaveBeenCalledWith(
      '/api/v1/nlp/sessions/sess-7/chat',
      { message: 'why?', auto_integrate: true },
      expect.objectContaining({ timeout: expect.any(Number) }),
    )
  })
})

describe('the harness is not testing the mock branch by accident', () => {
  it('reaches the http client at all', async () => {
    // The failure this whole file family exists to prevent: if `loadInRealMode` stopped
    // working, every assertion above would run against the fixture branch and pass while
    // proving nothing about the code that ships.
    get.mockResolvedValue(complete([]))
    const api = await sessions()

    await api.getSessionMessages('sess-1')

    expect(get).toHaveBeenCalled()
  })
})

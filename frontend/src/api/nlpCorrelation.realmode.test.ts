import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { loadInRealMode, restoreMockMode } from '../test/realMode'

/**
 * REAL-MODE tests for the correlation-chat client.
 *
 * WHY THIS ONE MATTERS MORE THAN MOST. `chat()` sends `message` as a QUERY parameter
 * and `conversation_history` as the BODY, because the handler declares the latter as
 * `Optional[List[Dict[str, str]]]` and FastAPI reads complex types from the body. It
 * used to send both in `params` with a `null` body, so the server received
 * `conversation_history = None` on every call — while the endpoint's docstring promised
 * it "maintains conversation context for multi-turn queries". It had no context to
 * maintain.
 *
 * NO BACKEND GUARD CAN CATCH THAT. `test_frontend_calls_real_endpoints.py` checks the
 * path exists. `test_frontend_query_params_are_declared.py` would have flagged
 * `conversation_history` as an undeclared query parameter — and did — but neither can
 * confirm it now travels in the body instead. The only thing that observes which
 * argument goes where is a test that inspects the request the client builds.
 *
 * Every other unit test in this project runs with `VITE_USE_MOCK=true` forced by
 * `src/test/setup.ts`, so they exercise the mock branch. This loads the module in real
 * mode and stubs axios, so what is asserted is the request itself.
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

async function nlpApi(): Promise<AnyApi> {
  const mod = await loadInRealMode(() => import('./nlpCorrelation'))
  return (mod as unknown as { nlpCorrelationApi: AnyApi }).nlpCorrelationApi
}

beforeEach(() => {
  vi.clearAllMocks()
})

afterEach(() => {
  restoreMockMode()
})

describe('nlpCorrelationApi.chat in real mode', () => {
  it('sends conversation_history as the BODY, not a query parameter', async () => {
    post.mockResolvedValue({ data: { role: 'assistant', content: 'ok' } })
    const api = await nlpApi()
    const history = [{ role: 'user', content: 'earlier turn' }]

    await api.chat('why is line 3 down?', history)

    expect(post).toHaveBeenCalledTimes(1)
    const [url, body, config] = post.mock.calls[0] as [
      string,
      unknown,
      { params: Record<string, unknown> },
    ]
    expect(url).toBe('/api/v1/nlp/correlation/chat')
    expect(body).toEqual(history)
    expect(config.params).not.toHaveProperty('conversation_history')
  })

  it('still sends message as a query parameter, which is what the handler declares', async () => {
    post.mockResolvedValue({ data: {} })
    const api = await nlpApi()

    await api.chat('hello')

    const [, , config] = post.mock.calls[0] as [
      string,
      unknown,
      { params: Record<string, unknown> },
    ]
    expect(config.params).toEqual({ message: 'hello' })
  })

  it('sends a null body when there is no history, rather than omitting the argument', async () => {
    // The handler's parameter is Optional; an explicit null is a valid "no history".
    // Passing `undefined` would make axios drop the body entirely, which is a
    // different request — and the shape this call had before the fix.
    post.mockResolvedValue({ data: {} })
    const api = await nlpApi()

    await api.chat('first turn')

    const [, body] = post.mock.calls[0] as [string, unknown, unknown]
    expect(body).toBeNull()
  })

  it('returns the payload the server sent', async () => {
    post.mockResolvedValue({ data: { role: 'assistant', content: 'answer', simulated: true } })
    const api = await nlpApi()

    const result = await api.chat('q')

    expect(result).toEqual({ role: 'assistant', content: 'answer', simulated: true })
  })
})

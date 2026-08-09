import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { loadInRealMode, restoreMockMode } from '../test/realMode'

/**
 * REAL-MODE tests for the Compliance Assistant client.
 *
 * Every other unit test runs with `VITE_USE_MOCK=true` forced by `test/setup.ts`,
 * so they exercise the `if (USE_MOCK)` fork — which is not what production runs.
 * These stub axios instead, so what gets asserted is the thing the page tests
 * cannot see: WHICH request is built and HOW the response is carried through.
 *
 * Two of these are load-bearing beyond "the path is right":
 *
 *   - The generation call needs a long timeout. Retrieval is fast; a cold local
 *     model is not, and the shared axios default of 30s cuts the answer off
 *     mid-generation. That failure looks like a network error, not a slow model,
 *     so nobody would go looking at the timeout.
 *   - `documentLink` must POST. A GET would put the S3 key of a compliance
 *     document into every access log and proxy trace between the browser and the
 *     backend — the key is not a secret, but the fact that a named person opened
 *     a named disciplinary policy is exactly the sort of thing that should not
 *     leak into log aggregation by accident.
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

async function ragApi(): Promise<AnyApi> {
  const mod = await loadInRealMode(() => import('./rag'))
  return (mod as unknown as { ragApi: AnyApi }).ragApi
}

const answerBody = {
  answer: 'Apply a personal lock [1].',
  citations: [
    {
      n: 1,
      docId: 'd1',
      filename: 'loto.pdf',
      s3Key: 'org-a/d1/loto.pdf',
      source: { page: 4 },
      score: 0.9,
      snippet: 'text',
    },
  ],
  usedContext: true,
  generated: true,
  sources: [
    { docId: 'd1', filename: 'loto.pdf', s3Key: 'org-a/d1/loto.pdf', cited: true, score: 0.9, isForm: false },
  ],
}

beforeEach(() => vi.clearAllMocks())
afterEach(() => restoreMockMode())

describe('ragApi in real mode', () => {
  it('posts the question to the RAG query route', async () => {
    post.mockResolvedValue({ data: answerBody })
    const api = await ragApi()

    await api.query({ query: 'lockout procedure' })

    expect(post).toHaveBeenCalledTimes(1)
    const [url, body] = post.mock.calls[0] as [string, Record<string, unknown>]
    expect(url).toBe('/api/v1/rag/query')
    expect(body).toEqual({ query: 'lockout procedure' })
  })

  it('gives generation room to finish', async () => {
    post.mockResolvedValue({ data: answerBody })
    const api = await ragApi()

    await api.query({ query: 'lockout procedure' })

    const [, , config] = post.mock.calls[0] as [string, unknown, { timeout: number }]
    expect(config.timeout).toBeGreaterThanOrEqual(120000)
  })

  it('passes topN and generate through when the caller sets them', async () => {
    post.mockResolvedValue({ data: answerBody })
    const api = await ragApi()

    await api.query({ query: 'q', topN: 10, generate: false })

    const [, body] = post.mock.calls[0] as [string, Record<string, unknown>]
    expect(body).toEqual({ query: 'q', topN: 10, generate: false })
  })

  it('returns the server response untouched', async () => {
    /** No defaulting, no reshaping. `answer: null` and `score: null` are real
     *  server states that mean something specific; a client that filled them in
     *  would be deciding what the server meant. */
    const degraded = {
      ...answerBody,
      answer: null,
      generated: false,
      sources: [{ ...answerBody.sources[0], cited: false, score: null }],
    }
    post.mockResolvedValue({ data: degraded })
    const api = await ragApi()

    const result = await api.query({ query: 'q' })

    expect(result.answer).toBeNull()
    expect(result.generated).toBe(false)
    expect(result.sources[0].score).toBeNull()
  })

  it('requests a document link by POST, not GET', async () => {
    post.mockResolvedValue({ data: { url: 'https://s3/signed', expiresIn: 3600 } })
    const api = await ragApi()

    const result = await api.documentLink('org-a/d1/loto.pdf')

    expect(get).not.toHaveBeenCalled()
    const [url, body] = post.mock.calls[0] as [string, Record<string, unknown>]
    expect(url).toBe('/api/v1/rag/documents/link')
    expect(body).toEqual({ s3Key: 'org-a/d1/loto.pdf' })
    expect(result.url).toBe('https://s3/signed')
  })

  it('does not offer an ingest call', async () => {
    /** Documents enter the corpus through the Correlation AI intake flow. An
     *  upload path appearing here would quietly make the Compliance Assistant a
     *  second, unreviewed way into the same corpus. */
    const api = await ragApi()
    expect(api.ingest).toBeUndefined()
    expect(api.upload).toBeUndefined()
  })
})

/**
 * The normaliser the UI actually uses (FS-656).
 *
 * There were two in this directory with different contracts. `normalizeApiError` answers
 * `status: null` and `code: 'network_error'` when a request never reached the server.
 * `handleApiError` answered **`status: 500`** — `error.response?.status || 500` — so a machine
 * that could not reach the backend reported that the backend had failed.
 *
 * Fifteen call sites read only `.message`, so nothing was visibly wrong yet. That is the
 * shape of the trap rather than a reason to leave it: the first caller to retry on `>= 500`
 * would retry a request that never left the machine, and error triage would attribute every
 * network outage to a server fault. `handleApiError` now delegates.
 *
 * The message matters as much as the status, because `.message` is the one field every caller
 * renders — and for a request with no response, axios offers "Network Error", which tells the
 * user nothing they can act on.
 */
import { AxiosError } from 'axios'
import { describe, expect, it } from 'vitest'

import { handleApiError } from './client'
import { normalizeApiError } from './errors'

const axiosError = (over: Partial<AxiosError> = {}): AxiosError =>
  Object.assign(new Error('Network Error'), { isAxiosError: true, toJSON: () => ({}) }, over) as AxiosError

describe('a response the server sent', () => {
  it('keeps the status it was given', () => {
    const e = axiosError({ response: { status: 404, data: { detail: 'no such asset' } } as never })
    expect(handleApiError(e).status).toBe(404)
  })

  it('prefers the backend envelope message', () => {
    const e = axiosError({
      response: { status: 422, data: { error: { code: 'invalid', message: 'asset_id required' } } } as never,
    })
    expect(handleApiError(e).message).toBe('asset_id required')
  })

  it('falls back to a bare detail', () => {
    const e = axiosError({ response: { status: 400, data: { detail: 'bad input' } } as never })
    expect(handleApiError(e).message).toBe('bad input')
  })

  it('reports a genuine 500 as 500', () => {
    // The case the old default was impersonating. It has to keep working, or the fix would
    // have traded one indistinguishable pair for another.
    const e = axiosError({ response: { status: 500, data: { detail: 'boom' } } as never })
    expect(handleApiError(e).status).toBe(500)
  })
})

describe('a request that never reached the server', () => {
  it('does not invent a status', () => {
    // THE FINDING. `|| 500` turned "no response" into "the server answered 500".
    expect(handleApiError(axiosError()).status).toBeNull()
  })

  it('is distinguishable from a real server error', () => {
    // The property that makes the fix worth anything: a caller CAN now branch. Before this
    // both cases were the number 500.
    const offline = handleApiError(axiosError())
    const serverFault = handleApiError(
      axiosError({ response: { status: 500, data: { detail: 'boom' } } as never }),
    )
    expect(offline.status).not.toBe(serverFault.status)
  })

  it('says something the user can act on rather than "Network Error"', () => {
    // `.message` is the only field any of the fifteen callers render.
    expect(handleApiError(axiosError()).message).toMatch(/could not reach the server/i)
  })
})

describe('anything else that was thrown', () => {
  it('carries a plain Error through', () => {
    expect(handleApiError(new Error('boom')).message).toBe('boom')
  })

  it('does not claim a plain Error failed to reach the server', () => {
    // A non-axios throw has no response either, so the naive check — "status is null,
    // therefore offline" — would mislabel every bug in a request handler as a network fault.
    expect(handleApiError(new Error('boom')).message).not.toMatch(/could not reach/i)
  })

  it('survives a thrown non-Error', () => {
    expect(handleApiError('just a string').message).toBeTruthy()
  })
})

describe('the two normalisers agree', () => {
  /**
   * The defect was not the `|| 500` on its own — it was that two functions in one directory
   * answered the same question differently and no caller could see which one it had. A
   * behavioural check rather than "handleApiError must call normalizeApiError", because the
   * structural version passes for any delegation and fails for any honest reimplementation,
   * which is backwards.
   */
  const CASES: [string, unknown][] = [
    ['no response at all', axiosError()],
    ['a 404 with a detail', axiosError({ response: { status: 404, data: { detail: 'gone' } } as never })],
    ['a 500 with a detail', axiosError({ response: { status: 500, data: { detail: 'boom' } } as never })],
    ['the backend envelope', axiosError({
      response: { status: 422, data: { error: { code: 'invalid', message: 'bad field' } } } as never,
    })],
    ['a plain Error', new Error('boom')],
  ]

  it.each(CASES)('reports the same status for %s', (_label, error) => {
    expect(handleApiError(error).status).toBe(normalizeApiError(error).status)
  })
})

describe('the caller that does branch on status', () => {
  /**
   * `ComplianceAssistant.tsx` destructures `{ status, message }` and compares `status === 503`
   * to tell a RAG service outage from a failed answer. It is pinned here because the sweep
   * that found this defect reported that no caller read `.status` — its regex matched
   * `handleApiError(...).field` and could not see a destructure. Behaviour is unchanged by the
   * fix, and this is the test that would have said so.
   */
  it('still recognises a real 503', () => {
    const e = axiosError({ response: { status: 503, data: { detail: 'retrieval down' } } as never })
    expect(handleApiError(e).status).toBe(503)
  })

  it('does not turn an unreachable server into a 503-shaped answer', () => {
    // Nor into any other status a caller might special-case. The old `|| 500` at least had
    // the courtesy of being obviously wrong; null is the only honest value.
    expect(handleApiError(axiosError()).status).toBeNull()
  })
})

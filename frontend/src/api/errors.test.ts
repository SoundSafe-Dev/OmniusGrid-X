import { describe, expect, it } from 'vitest'
import { normalizeApiError } from './errors'

describe('normalizeApiError', () => {
  it('maps the backend error envelope', () => {
    const err = {
      response: { status: 404, data: { error: { code: 'not_found', message: 'no thing', trace_id: 't1', details: { id: 9 } }, detail: 'no thing' } },
    }
    const n = normalizeApiError(err)
    expect(n).toEqual({ code: 'not_found', message: 'no thing', status: 404, traceId: 't1', details: { id: 9 } })
  })

  it('falls back to bare detail', () => {
    const n = normalizeApiError({ response: { status: 400, data: { detail: 'bad input' } } })
    expect(n.message).toBe('bad input')
    expect(n.code).toBe('http_400')
  })

  it('handles network errors', () => {
    const n = normalizeApiError({ message: 'Network Error' })
    expect(n.code).toBe('network_error')
    expect(n.message).toBe('Network Error')
  })
})

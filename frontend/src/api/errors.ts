import { AxiosError } from 'axios'

// Typed API error normalizer (task 3). Maps the backend error envelope
// ({ error: { code, message, details, trace_id }, detail }) — and any other
// failure shape — into one predictable object the UI can render/branch on.

export interface NormalizedApiError {
  code: string
  message: string
  status: number | null
  traceId: string | null
  details: unknown
}

export function normalizeApiError(err: unknown): NormalizedApiError {
  const axiosErr = err as AxiosError<any>
  const resp = axiosErr?.response
  const body = resp?.data as any

  if (body && typeof body === 'object' && body.error) {
    return {
      code: body.error.code ?? 'error',
      message: body.error.message ?? body.detail ?? 'Request failed',
      status: resp?.status ?? null,
      traceId: body.error.trace_id ?? null,
      details: body.error.details ?? null,
    }
  }

  // Fallbacks: bare {detail}, network error, or a plain Error.
  const message =
    (body && (body.detail || body.message)) ||
    (axiosErr?.message) ||
    (err instanceof Error ? err.message : 'Unknown error')

  return {
    code: resp?.status ? `http_${resp.status}` : 'network_error',
    message,
    status: resp?.status ?? null,
    traceId: null,
    details: null,
  }
}

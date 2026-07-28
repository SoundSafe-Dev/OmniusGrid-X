/**
 * A list response that can tell you whether it is the whole list.
 *
 * Several endpoints return a bare JSON array capped at `limit`, which makes a full page
 * indistinguishable from the complete set — the caller renders N rows as "all of them"
 * and nothing anywhere says otherwise. The server reports the difference in headers
 * (`X-Result-Truncated`, `X-Result-Limit`) rather than an envelope, so the body every
 * existing caller consumes is unchanged; this type is what stops the flag being dropped
 * on the way in.
 *
 * Lifted out of `erp.ts` when `/api/v1/rul` became the second consumer. RUL is the
 * sharper case: remaining useful life is computed per asset in Python, so the list is
 * ordered by asset NAME, and truncation silently removes the alphabetically-last
 * assets from a view whose entire purpose is spotting the ones about to fail.
 */
export interface ListResult<T> {
  items: T[]
  /** True when more rows exist beyond this page. */
  truncated: boolean
  /** The page size the server actually applied. */
  limit: number
}

/** Read the truncation headers off an axios response. */
export function toListResult<T>(res: {
  data: T[]
  headers?: Record<string, unknown>
}): ListResult<T> {
  const header = (name: string) => String(res.headers?.[name] ?? '')
  return {
    items: res.data,
    truncated: header('x-result-truncated') === 'true',
    // Falls back to the row count so a server that sends no header still yields a
    // sensible `limit` rather than NaN.
    limit: Number(header('x-result-limit')) || res.data.length,
  }
}

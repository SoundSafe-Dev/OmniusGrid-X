/**
 * The chat clients must not discard the truncation signal (FS-459).
 *
 * `getChatHistory`, `searchChatHistory` and `getSessionMessages` returned bare arrays, so a
 * full page was indistinguishable from the complete set. Three reasons that matters more
 * here than on most lists:
 *
 *   * **history** — a modal showing 100 of 400 messages reads as the whole record, and
 *     "there is no earlier conversation" is the wrong conclusion to hand someone looking
 *     for what was said;
 *   * **search** — a capped result set means matches EXIST that were not shown. A search
 *     box that quietly omits hits is worse than one that finds nothing, because the user
 *     concludes the thing is not there;
 *   * **session messages** — the endpoint orders OLDEST FIRST, so truncation removes the
 *     most RECENT turns. The pane shows the start of a conversation and silently omits what
 *     was just said, which is the half the user is actually looking at.
 *
 * The backend halves shipped the same day (`limit + 1` and `mark_truncated`). This is the
 * client half, pinned so the signal cannot be dropped on the way in — the failure recorded
 * three times in this repository is a flag that is produced correctly and read by nobody.
 */
import { describe, expect, it, vi, beforeEach } from 'vitest'

vi.mock('./mockMode', () => ({ USE_MOCK: false }))

const get = vi.fn()
vi.mock('./client', () => ({ api: { get: (...a: unknown[]) => get(...a) } }))

const api = await import('./analysisSessions')

beforeEach(() => get.mockReset())

const MESSAGE = { id: 'm1', session_id: 's1', role: 'user', content: 'hello' }

/** Each entry: a label, and a call that must surface the flag. */
const CALLS: Array<[string, () => Promise<{ items: unknown[]; truncated: boolean; limit: number }>]> = [
  ['getChatHistory', () => api.getChatHistory(100, 0)],
  ['searchChatHistory', () => api.searchChatHistory('hello', 50, 0)],
  ['getSessionMessages', () => api.getSessionMessages('s1', 100, 0)],
]

describe('chat list results carry the truncation signal', () => {
  it.each(CALLS)('%s reports truncated when the server says so', async (_label, call) => {
    get.mockResolvedValue({
      data: [MESSAGE, MESSAGE],
      headers: { 'x-result-truncated': 'true', 'x-result-limit': '2' },
    })
    const result = await call()
    expect(result.items).toHaveLength(2)
    expect(result.truncated).toBe(true)
    expect(result.limit).toBe(2)
  })

  it.each(CALLS)('%s reports not-truncated for a partial page', async (_label, call) => {
    get.mockResolvedValue({
      data: [MESSAGE],
      headers: { 'x-result-truncated': 'false', 'x-result-limit': '100' },
    })
    expect((await call()).truncated).toBe(false)
  })

  it.each(CALLS)('%s defaults to not-truncated when the header is absent', async (_label, call) => {
    // Fail SAFE rather than closed, matching `erp.truncation.test.ts`: claiming truncation
    // on every response would make the notice meaningless, and an older server simply does
    // not send the header.
    get.mockResolvedValue({ data: [MESSAGE], headers: {} })
    const result = await call()
    expect(result.truncated).toBe(false)
    // The limit falls back to the row count so a caller never reads NaN.
    expect(result.limit).toBe(1)
  })

  it.each(CALLS)('%s still returns the rows themselves', async (_label, call) => {
    // The other direction. A wrapper that surfaces the flag and loses the payload would
    // pass every assertion above while rendering an empty list.
    get.mockResolvedValue({
      data: [MESSAGE],
      headers: { 'x-result-truncated': 'true' },
    })
    expect((await call()).items).toEqual([MESSAGE])
  })
})

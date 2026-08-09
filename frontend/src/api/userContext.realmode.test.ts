import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { loadInRealMode, restoreMockMode } from '../test/realMode'

/**
 * REAL-MODE tests for the user-context client (FS-488).
 *
 * **Only the read was mocked here.** `getUserContext` returned a fixture and the four
 * writers went straight to the API in every mode — so in the demo, `ContextManagementModal`
 * showed a context, accepted edits, and failed on Save against a backend that is not running.
 * FS-478 gave that failure a message, which turned a silent oddity into a visibly broken
 * button.
 *
 * Every other client here mocks its writes: `erp.createIntegration`,
 * `notifications.createSubscription`, `kanbanStore.moveTask`. The convention existed; this
 * file had adopted half of it. **A mode that mocks half a surface is a double for exactly
 * the half nobody was testing.**
 *
 * These tests hold the real branch — every write returns the SERVER's context, not the
 * request — because the whole point of these endpoints is that the server owns the goal list
 * and assigns the ids. `ContextManagementModal` refetches after each write, so a client
 * returning its own argument would look right for one render and diverge from the moment
 * anything else touched the record.
 */

const get = vi.fn()
const post = vi.fn()
const put = vi.fn()
const del = vi.fn()

vi.mock('./client', () => ({
  api: {
    get: (...args: unknown[]) => get(...args),
    post: (...args: unknown[]) => post(...args),
    put: (...args: unknown[]) => put(...args),
    delete: (...args: unknown[]) => del(...args),
    patch: vi.fn(),
  },
}))

type AnyApi = Record<string, (...args: any[]) => Promise<any>>

async function userContext(): Promise<AnyApi> {
  const mod = await loadInRealMode(() => import('./userContext'))
  return (mod as unknown as { userContextApi: AnyApi }).userContextApi
}

const CONTEXT = {
  id: 'user-1',
  email: 'ops@example.com',
  full_name: 'A. Operator',
  role: 'Operations Director',
  department: 'Manufacturing',
  priorities: ['Reduce downtime'],
  user_context: {},
  user_goals: [{ id: 'goal-1', title: 'Cut downtime 20%', progress: 62, deadline: null }],
}

beforeEach(() => {
  get.mockReset()
  post.mockReset()
  put.mockReset()
  del.mockReset()
  get.mockResolvedValue({ data: CONTEXT })
  post.mockResolvedValue({ data: CONTEXT })
  put.mockResolvedValue({ data: CONTEXT })
  del.mockResolvedValue({ data: CONTEXT })
})

afterEach(() => {
  restoreMockMode()
})

describe('every call reaches the endpoint it names', () => {
  it('reads the context', async () => {
    const api = await userContext()
    await api.getUserContext()
    expect(get).toHaveBeenCalledWith('/api/v1/user/context')
  })

  it('updates the context with PUT', async () => {
    const api = await userContext()
    await api.updateUserContext({ department: 'Quality', priorities: ['Scrap < 1%'] })
    expect(put).toHaveBeenCalledWith('/api/v1/user/context', {
      department: 'Quality',
      priorities: ['Scrap < 1%'],
    })
  })

  it('adds a goal with POST to the goals collection', async () => {
    const api = await userContext()
    await api.addUserGoal({ title: 'OTIF 97%', progress: 0 })
    expect(post).toHaveBeenCalledWith('/api/v1/user/goals', { title: 'OTIF 97%', progress: 0 })
  })

  it('updates a goal by id, not by index', async () => {
    // The mock branch maps over the array; the real path addresses the row. A client using
    // a position here would edit whichever goal happened to be in that slot.
    const api = await userContext()
    await api.updateGoal('goal-7', { title: 'Renamed', progress: 40 })
    expect(put).toHaveBeenCalledWith('/api/v1/user/goals/goal-7', {
      title: 'Renamed',
      progress: 40,
    })
  })

  it('deletes a goal by id', async () => {
    const api = await userContext()
    await api.deleteGoal('goal-7')
    expect(del).toHaveBeenCalledWith('/api/v1/user/goals/goal-7')
  })
})

describe('a write returns the server context, not the request', () => {
  it('returns the whole context after adding a goal', async () => {
    // These endpoints all return the FULL context because the server owns the goal list and
    // assigns the ids. A client echoing its own argument would look right for one render
    // and diverge the moment anything else touched the record.
    post.mockResolvedValue({
      data: { ...CONTEXT, user_goals: [...CONTEXT.user_goals, { id: 'goal-server', title: 'OTIF 97%', progress: 0, deadline: null }] },
    })
    const api = await userContext()

    const result = await api.addUserGoal({ title: 'OTIF 97%', progress: 0 })

    expect(result.user_goals).toHaveLength(2)
    expect(result.user_goals[1].id).toBe('goal-server')
  })

  it('returns the server context after a delete', async () => {
    del.mockResolvedValue({ data: { ...CONTEXT, user_goals: [] } })
    const api = await userContext()

    expect((await api.deleteGoal('goal-1')).user_goals).toEqual([])
  })

  it('lets a failed write reach the caller', async () => {
    // `ContextManagementModal` catches these into a visible message (FS-478). A client that
    // swallowed the rejection would take that away and leave a modal that just stays open.
    put.mockRejectedValue(new Error('403'))
    const api = await userContext()

    await expect(api.updateUserContext({ department: 'Quality' })).rejects.toThrow()
  })
})

describe('the harness is not testing the mock branch by accident', () => {
  it('reaches the http client at all', async () => {
    const api = await userContext()
    await api.getUserContext()
    expect(get).toHaveBeenCalled()
  })
})

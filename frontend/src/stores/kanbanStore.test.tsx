/**
 * The kanban store (FS-651).
 *
 * 367 lines that own board loading and **every task mutation**, and `pages/Kanban.test.tsx`
 * mocks the whole module — so the page tests prove the page renders whatever this returns and
 * nothing about what it returns.
 *
 * WHAT THESE PIN.
 *
 *   * **`moveTask` is pessimistic, despite its comment.** The POST is awaited BEFORE local
 *     state changes, so a rejected move leaves the card in its original column — which is
 *     the right behaviour and the opposite of the "update local state optimistically" note
 *     sitting above it. A card that moves and then silently snaps back is the failure this
 *     ordering avoids; the comment described the version that would have had it.
 *   * **A failed refresh keeps the old board AND sets an error.** Blanking the board on a
 *     transient failure throws away the last known state; blanking the error would leave a
 *     stale board reading as current. It has to do both.
 *   * **Filters reach the server**, or the board silently returns everything and the user
 *     believes they have filtered.
 */
import { act, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const get = vi.fn()
const post = vi.fn()
const put = vi.fn()
vi.mock('../api/client', () => ({
  api: { get: (...a: unknown[]) => get(...a), post: (...a: unknown[]) => post(...a), put: (...a: unknown[]) => put(...a), delete: vi.fn() },
}))
// The live path, not the demo one. In mock mode `moveTask` never calls the server at all,
// so testing that would assert the fixture rather than the store.
vi.mock('../api/mockMode', () => ({ USE_MOCK: false }))

import { KanbanProvider, useKanban } from './kanbanStore'

const TASK = { id: 't-1', title: 'Bearing', column_id: 'col-a', position: 0, status: 'todo' }

let ctx: ReturnType<typeof useKanban>
function Probe() {
  ctx = useKanban()
  return <div data-testid="col">{ctx.tasks.map((t) => `${t.id}:${t.column_id}`).join(',')}</div>
}

const board = (tasks = [TASK]) => ({
  data: { board: { id: 'b-1' }, columns: [{ id: 'col-a' }, { id: 'col-b' }], tasks },
})

async function mount() {
  render(<KanbanProvider><Probe /></KanbanProvider>)
  await waitFor(() => expect(get).toHaveBeenCalled())
}

beforeEach(() => {
  vi.clearAllMocks()
  get.mockResolvedValue(board())
  post.mockResolvedValue({ data: {} })
  put.mockResolvedValue({ data: {} })
})

describe('loading the board', () => {
  it('reads the board endpoint and exposes its tasks', async () => {
    await mount()
    await waitFor(() => expect(screen.getByTestId('col').textContent).toBe('t-1:col-a'))
  })

  it('sends the active filters as query parameters', async () => {
    // A filter the client applies and the server never sees means the board returns
    // everything and the user believes they have narrowed it.
    await mount()
    await act(async () => { ctx.setFilters({ priority: 'critical' }) })
    await waitFor(
      () =>
        expect(
          get.mock.calls.some(
            ([url, cfg]) => url === '/api/v1/kanban/board' && cfg?.params?.priority === 'critical',
          ),
        ).toBe(true),
      { timeout: 3000 },
    )
  })

  it('records an error when the board cannot be loaded', async () => {
    get.mockRejectedValue(new Error('gateway timeout'))
    await mount()
    await waitFor(() => expect(ctx.error).toBe('gateway timeout'))
  })

  it('keeps the last known board when a refresh fails', async () => {
    // Blanking on a transient failure throws away the only state the operator has. The
    // error is what tells them it is stale — which is why both have to be true at once.
    await mount()
    await waitFor(() => expect(ctx.tasks).toHaveLength(1))
    get.mockRejectedValue(new Error('offline'))
    await act(async () => { await ctx.refreshBoard() })
    expect(ctx.tasks).toHaveLength(1)
    expect(ctx.error).toBe('offline')
  })

  it('clears a previous error once a refresh succeeds', async () => {
    get.mockRejectedValueOnce(new Error('blip'))
    await mount()
    await waitFor(() => expect(ctx.error).toBe('blip'))
    get.mockResolvedValue(board())
    await act(async () => { await ctx.refreshBoard() })
    await waitFor(() => expect(ctx.error).toBeNull())
  })
})

describe('moving a task', () => {
  it('tells the server which column it went to', async () => {
    await mount()
    await act(async () => { await ctx.moveTask('t-1', 'col-b') })
    expect(post).toHaveBeenCalledWith(
      '/api/v1/kanban/tasks/t-1/move',
      expect.objectContaining({ target_column_id: 'col-b' }),
    )
  })

  it('does NOT move the card when the server refuses', async () => {
    // The comment above this code says "update local state optimistically". It does not:
    // the POST is awaited first, so a rejection leaves the card where it was. That is the
    // better behaviour — a card that moves and snaps back is indistinguishable from a
    // board that reordered itself — and this test is what keeps the ordering.
    await mount()
    await waitFor(() => expect(screen.getByTestId('col').textContent).toBe('t-1:col-a'))
    post.mockRejectedValue(new Error('WIP limit reached'))
    await act(async () => {
      await expect(ctx.moveTask('t-1', 'col-b')).rejects.toThrow('WIP limit reached')
    })
    expect(screen.getByTestId('col').textContent).toBe('t-1:col-a')
  })

  it('re-reads the board after a successful move', async () => {
    // The local update is a guess at what the server did; the refresh is the truth. Without
    // it a move that the server adjusted — a position clamp, a WIP reshuffle — leaves the
    // screen disagreeing with the database until something else reloads.
    await mount()
    const before = get.mock.calls.length
    await act(async () => { await ctx.moveTask('t-1', 'col-b') })
    expect(get.mock.calls.length).toBeGreaterThan(before)
  })
})

describe('updating a task', () => {
  it('sends only what changed', async () => {
    await mount()
    await act(async () => { await ctx.updateTask('t-1', { title: 'Bearing, urgent' }) })
    expect(put).toHaveBeenCalledWith('/api/v1/kanban/tasks/t-1', { title: 'Bearing, urgent' })
  })

  it('propagates a failure to the caller rather than swallowing it', async () => {
    // The modal that calls this keeps itself open on a rejection. If the store swallowed
    // the error the modal would close on a write that never happened.
    await mount()
    put.mockRejectedValue(new Error('not permitted'))
    await act(async () => {
      await expect(ctx.updateTask('t-1', { title: 'x' })).rejects.toThrow('not permitted')
    })
  })
})

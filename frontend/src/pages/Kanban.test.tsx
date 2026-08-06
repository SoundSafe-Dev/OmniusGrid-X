/**
 * The operations board — the last routed page from FS-364 with no test.
 *
 * The load path is already careful: a failed board fetch renders the error with a retry
 * rather than an empty board, which matters because an empty kanban reads as "nothing
 * needs doing" and that is a reason to go home. Asserted here so it stays true.
 *
 * **What was wrong** (FS-483). `handleDragEnd` awaited `moveTask` and caught into
 * `console.error`. `moveTask` posts to the server BEFORE it updates local state, so on
 * failure the card re-renders in the column it came from — which is also exactly what a
 * mis-drop looks like. The operator's reading is that they missed the target and they try
 * again; the truth is that the board and the server disagree about where the task is.
 *
 * Neither hand-rolled sweep could see it. The awaited call is `moveTask(…)` — a context
 * function, not the `…Api.<verb>(…)` shape those sweeps key on — and the `await` lives in
 * `kanbanStore.tsx` while the `catch` lives here, two files apart.
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const moveTask = vi.fn()
const refreshBoard = vi.fn()
const kanbanState: Record<string, unknown> = {}

vi.mock('../stores/kanbanStore', () => ({
  KanbanProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  useKanban: () => ({
    board: { id: 'b1' },
    columns: [
      { id: 'c1', name: 'To do', position: 0 },
      { id: 'c2', name: 'Done', position: 1 },
    ],
    tasks: [{ id: 't1', title: 'Replace bearing', column_id: 'c1', position: 0, status: 'open' }],
    metrics: null,
    filters: {},
    isLoading: false,
    error: null,
    setFilters: vi.fn(),
    refreshBoard,
    moveTask,
    ...kanbanState,
  }),
}))

vi.mock('../hooks/useAuth', () => ({ useAuth: () => ({ isAdmin: false }) }))

/** The board's own drag machinery is HTML5 drag events on nested divs, which jsdom does
 *  not carry far enough to drive reliably. Stubbing it to a plain button exposes the one
 *  thing under test — what the page does when `onDragEnd` rejects — without asserting on
 *  a drag implementation this test is not about. */
vi.mock('../components/kanban/KanbanBoard', () => ({
  KanbanBoard: ({ onDragEnd }: { onDragEnd: (a: string, b: string) => Promise<void> }) => (
    <button onClick={() => onDragEnd('t1', 'c2')}>drop t1 on Done</button>
  ),
}))
vi.mock('../components/kanban/TaskDetailModal', () => ({ TaskDetailModal: () => null }))
vi.mock('../components/kanban/CreateTaskModal', () => ({ CreateTaskModal: () => null }))
vi.mock('../components/kanban/KanbanMetrics', () => ({ KanbanMetrics: () => null }))
vi.mock('../components/kanban/KanbanFilters', () => ({ KanbanFilters: () => null }))
vi.mock('../components/ExportButton', () => ({ ExportButton: () => null }))

const { default: KanbanPage } = await import('./Kanban')
const { TooltipProvider } = await import('../components/ui')

const show = () =>
  render(
    <TooltipProvider>
      <KanbanPage />
    </TooltipProvider>,
  )

beforeEach(() => {
  moveTask.mockReset()
  refreshBoard.mockReset()
  for (const key of Object.keys(kanbanState)) delete kanbanState[key]
  moveTask.mockResolvedValue(undefined)
})

describe('a move the server refused (FS-483)', () => {
  it('says the task is still where it started', async () => {
    // Not "an error occurred". The card is visibly back in its original column, and the
    // only question the operator has is whether that is their doing or the system's.
    moveTask.mockRejectedValue(new Error('409'))
    show()

    fireEvent.click(screen.getByRole('button', { name: /drop t1 on Done/i }))

    const alert = await screen.findByRole('alert')
    expect(alert.textContent).toMatch(/could not be moved/i)
    expect(alert.textContent).toMatch(/still in the column it started in/i)
  })

  it('says nothing when the move succeeded', async () => {
    // The other direction. A banner after every drag would make the failure above
    // indistinguishable from the ordinary case, which is most of them.
    moveTask.mockResolvedValue(undefined)
    show()

    fireEvent.click(screen.getByRole('button', { name: /drop t1 on Done/i }))

    await waitFor(() => expect(moveTask).toHaveBeenCalledWith('t1', 'c2', undefined))
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('clears the warning once a later move works', async () => {
    moveTask.mockRejectedValue(new Error('409'))
    show()
    fireEvent.click(screen.getByRole('button', { name: /drop t1 on Done/i }))
    await screen.findByRole('alert')

    moveTask.mockResolvedValue(undefined)
    fireEvent.click(screen.getByRole('button', { name: /drop t1 on Done/i }))

    await waitFor(() => expect(screen.queryByRole('alert')).not.toBeInTheDocument())
  })

  it('still dispatches the move', async () => {
    // An error banner that replaced the board would pass the tests above and remove the
    // feature.
    show()
    fireEvent.click(screen.getByRole('button', { name: /drop t1 on Done/i }))
    await waitFor(() => expect(moveTask).toHaveBeenCalled())
  })
})

describe('a board that will not load is not an empty board', () => {
  it('says so, with a retry', async () => {
    // An empty kanban reads as "nothing needs doing", which is a reason to go home.
    kanbanState.error = 'kanban unreachable'
    show()

    expect(screen.getByText(/kanban unreachable/i)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /retry/i }))
    await waitFor(() => expect(refreshBoard).toHaveBeenCalled())
  })

  it('shows a spinner while loading, not the error', () => {
    kanbanState.isLoading = true
    const { container } = show()

    expect(container.querySelector('.animate-spin')).toBeTruthy()
    expect(screen.queryByRole('button', { name: /retry/i })).not.toBeInTheDocument()
  })

  it('shows the board when it loads', () => {
    show()
    expect(screen.getByRole('button', { name: /drop t1 on Done/i })).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })
})

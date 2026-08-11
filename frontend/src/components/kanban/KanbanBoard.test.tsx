/**
 * The kanban board — where the drag gesture is held between the two halves (FS-651).
 *
 * 214 lines, previously a `() => null` stub. The card starts a drag, the column receives the
 * drop, and this component is the only thing that remembers **which task** was picked up in
 * between. That state is the finding.
 *
 * A REFUSED MOVE LEFT THE BOARD HOLDING THE TASK. `handleDrop` awaited `onDragEnd` and
 * cleared `draggedTaskId` afterwards — so when the store rejected (a WIP limit, a permission,
 * a dropped connection) the await threw, the two resets never ran, and the board kept
 * pointing at the task with the target column still highlighted. The next drop anywhere on
 * the board then moved **that** task, not the one the operator was dragging. Fixed with
 * `finally`; pinned below.
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { TooltipProvider } from '../ui'
import { KanbanBoard } from './KanbanBoard'

const col = (id: string, name = id) => ({ id, name, wip_limit: 0, color: '#888' }) as never
const task = (id: string, column_id: string) =>
  ({
    id,
    title: `Task ${id}`,
    column_id,
    task_type: 'custom',
    priority: 'medium',
    status: 'todo',
    progress_percent: 0,
    checklist_items: [],
  }) as never

function show(over: Record<string, unknown> = {}) {
  const onDragEnd = vi.fn().mockResolvedValue(undefined)
  const onTaskClick = vi.fn()
  const utils = render(
    <TooltipProvider>
      <KanbanBoard
        board={{ id: 'b-1' }}
        columns={[col('col-a', 'To Do'), col('col-b', 'Doing')]}
        tasks={[task('t-1', 'col-a')]}
        viewMode="board"
        onTaskClick={onTaskClick}
        onDragEnd={onDragEnd}
        {...(over as Record<string, never>)}
      />
    </TooltipProvider>,
  )
  return { ...utils, onDragEnd, onTaskClick }
}

/** The element carrying each column's drop handlers: the child of the flex row. */
const columnAt = (container: HTMLElement, i: number) =>
  container.querySelector('.min-w-max')!.children[i] as HTMLElement

/** Start a drag on a card, then drop on a column. */
function dragCardToColumn(container: HTMLElement, cardText: string, columnIndex: number) {
  const store: Record<string, string> = {}
  const dataTransfer = {
    effectAllowed: '',
    setData: (k: string, v: string) => { store[k] = v },
    getData: (k: string) => store[k],
  }
  fireEvent.dragStart(screen.getByText(cardText).closest('[draggable]')!, { dataTransfer })
  fireEvent.drop(columnAt(container, columnIndex), { dataTransfer })
}

describe('the board holds the dragged task between the halves', () => {
  it('moves the dragged task to the column it was dropped on', async () => {
    const { container, onDragEnd } = show()
    dragCardToColumn(container as HTMLElement, 'Task t-1', 1)
    await waitFor(() => expect(onDragEnd).toHaveBeenCalled())
    expect(onDragEnd.mock.calls[0][0]).toBe('t-1')
  })

  it('does nothing on a drop that follows no drag', () => {
    // `handleDrop` guards on `draggedTaskId`. Without it, a stray drop — a file dragged in
    // from the desktop, say — would call the store with null and move nothing, noisily.
    const { container, onDragEnd } = show()
    fireEvent.drop(columnAt(container as HTMLElement, 0), { dataTransfer: { getData: () => '' } })
    expect(onDragEnd).not.toHaveBeenCalled()
  })

  it('FORGETS the task when the move is refused', async () => {
    // THE DEFECT THIS FILE FOUND. The resets used to run after the await, so a rejection
    // skipped them and the board kept holding the task with the column still highlighted.
    // The next drop anywhere then moved that task instead of the one being dragged.
    const onDragEnd = vi
      .fn()
      .mockRejectedValueOnce(new Error('WIP limit reached'))
      .mockResolvedValue(undefined)
    const { container } = show({ onDragEnd })
    dragCardToColumn(container as HTMLElement, 'Task t-1', 1)
    await waitFor(() => expect(onDragEnd).toHaveBeenCalledTimes(1))

    // A second drop with NO drag in front of it must do nothing at all.
    fireEvent.drop(columnAt(container as HTMLElement, 0), { dataTransfer: { getData: () => '' } })
    await new Promise((r) => setTimeout(r, 0))
    expect(onDragEnd).toHaveBeenCalledTimes(1)
  })
})

describe('what the board renders', () => {
  it('says so when there is no board rather than rendering an empty one', () => {
    // An empty board and an absent board look identical to a user, and only one of them
    // means "your organisation has no kanban configured".
    show({ board: null })
    expect(screen.getByText(/no board available/i)).toBeInTheDocument()
  })

  it('puts each task in its own column', () => {
    show({ tasks: [task('t-1', 'col-a'), task('t-2', 'col-b')] })
    expect(screen.getByText('Task t-1')).toBeInTheDocument()
    expect(screen.getByText('Task t-2')).toBeInTheDocument()
  })

  it('shows an empty list view without pretending there are tasks', () => {
    show({ viewMode: 'list', tasks: [] })
    expect(screen.getByText(/no tasks found/i)).toBeInTheDocument()
  })

  it('reports which task was clicked', () => {
    const { onTaskClick } = show()
    fireEvent.click(screen.getByText('Task t-1'))
    expect(onTaskClick).toHaveBeenCalledWith('t-1')
  })
})

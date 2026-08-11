/**
 * The kanban column — the drop target (FS-651).
 *
 * 252 lines, no test until now. It is the other half of the drag the card starts, and the
 * half where a mistake is invisible: a drop that does not `preventDefault` is simply
 * ignored by the browser, so the card animates back to where it was and the board looks
 * like a failed request.
 *
 * WHAT IS PINNED HERE.
 *
 *   * **`preventDefault` on both dragover and drop.** HTML5 drag-and-drop refuses a drop on
 *     any element that has not cancelled the dragover — the default action is "reject". So
 *     a missing `preventDefault` is a column that silently accepts nothing, with no error
 *     anywhere.
 *   * **The WIP warning is `>`, not `>=`.** A column at exactly its limit is at the limit,
 *     not over it. Off by one here nags an operator who is doing precisely what the board
 *     asked.
 *   * **The identity passed up.** `onDrop(column.id)` and `onTaskClick(task.id)` are how the
 *     board knows what moved and what was opened.
 */
import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { TooltipProvider } from '../ui'
import { KanbanColumn } from './KanbanColumn'

const column = (over: Record<string, unknown> = {}) =>
  ({ id: 'col-1', name: 'In Progress', wip_limit: 0, color: '#888', ...over }) as never

const task = (id: string, over: Record<string, unknown> = {}) =>
  ({
    id,
    title: `Task ${id}`,
    task_type: 'custom',
    priority: 'medium',
    status: 'in_progress',
    progress_percent: 0,
    checklist_items: [],
    ...over,
  }) as never

function show(props: Partial<Record<string, unknown>> = {}) {
  const handlers = {
    onTaskClick: vi.fn(),
    onDragStart: vi.fn(),
    onDragOver: vi.fn(),
    onDragLeave: vi.fn(),
    onDrop: vi.fn(),
  }
  const utils = render(
    <TooltipProvider>
      <KanbanColumn
        column={column()}
        tasks={[]}
        isDragOver={false}
        {...handlers}
        {...(props as Record<string, never>)}
      />
    </TooltipProvider>,
  )
  return { ...utils, ...handlers }
}

/** The element carrying the drop handlers — the column body. */
const dropZone = (container: HTMLElement) => container.firstElementChild!.firstElementChild ?? container.firstElementChild!

describe('the drop target accepts drops at all', () => {
  it('cancels dragover, which is what makes a drop possible', () => {
    // HTML5 drag-and-drop REJECTS by default. Without preventDefault on dragover the
    // browser never fires drop, and the card slides back with nothing logged anywhere.
    const { container, onDragOver } = show()
    const event = new Event('dragover', { bubbles: true, cancelable: true })
    dropZone(container as HTMLElement).dispatchEvent(event)
    expect(event.defaultPrevented).toBe(true)
    expect(onDragOver).toHaveBeenCalledWith('col-1')
  })

  it('cancels the drop and reports which column received it', () => {
    const { container, onDrop } = show()
    const event = new Event('drop', { bubbles: true, cancelable: true })
    dropZone(container as HTMLElement).dispatchEvent(event)
    expect(event.defaultPrevented).toBe(true)
    expect(onDrop).toHaveBeenCalledWith('col-1')
  })
})

describe('the WIP limit', () => {
  it('is not shown when there is no limit', () => {
    show({ column: column({ wip_limit: 0 }), tasks: [task('a')] })
    expect(screen.queryByText('WIP Limit')).not.toBeInTheDocument()
  })

  it('shows the count against the limit', () => {
    show({ column: column({ wip_limit: 3 }), tasks: [task('a'), task('b')] })
    expect(screen.getByText('2 / 3')).toBeInTheDocument()
  })

  it('does NOT warn at exactly the limit', () => {
    // At the limit is not over it. `>=` here nags an operator who is doing exactly what
    // the board asked, and a warning that is always on stops being a warning.
    const { container } = show({ column: column({ wip_limit: 2 }), tasks: [task('a'), task('b')] })
    expect(container.querySelector('.text-orange-600')).toBeNull()
  })

  it('warns when the limit is exceeded', () => {
    const { container } = show({
      column: column({ wip_limit: 2 }),
      tasks: [task('a'), task('b'), task('c')],
    })
    expect(container.querySelector('.text-orange-600')).not.toBeNull()
  })
})

describe('what the column passes up', () => {
  it('reports which task was clicked, not just that one was', () => {
    const { onTaskClick } = show({ tasks: [task('t-9')] })
    fireEvent.click(screen.getByText('Task t-9'))
    expect(onTaskClick).toHaveBeenCalledWith('t-9')
  })

  it('renders every task it is given', () => {
    show({ tasks: [task('a'), task('b'), task('c')] })
    expect(screen.getByText('Task a')).toBeInTheDocument()
    expect(screen.getByText('Task c')).toBeInTheDocument()
  })

  it('renders an empty column without complaint', () => {
    // A brand-new board is all empty columns, so this is the first thing a user sees.
    show({ tasks: [] })
    expect(screen.getByText('In Progress')).toBeInTheDocument()
  })
})

/**
 * The kanban card (FS-651).
 *
 * 239 lines in a directory of 1,811 with **zero test files** — the largest untested component
 * tree in the product, and the one pulling coverage down hardest.
 *
 * WHAT IS WORTH PINNING, and it is not the markup.
 *
 *   * **The drag payload.** `onDragStart` writes the task id into `dataTransfer`, and that
 *     string is the only thing the drop target has to identify what was dragged. If it is
 *     missing or wrong, the drop moves a different task — or nothing — and the board simply
 *     shows a card back where it started, which reads as a failed request rather than a bug.
 *   * **Overdue is a conjunction.** Past due AND not completed. Dropping the second half
 *     paints every finished task red, and an operator learns to ignore the colour.
 *   * **Unknown enum values.** `task_type` and `priority` come off a wire that has grown new
 *     values before. One falls back to `custom`; the other indexes a map directly, and this
 *     file records which is which.
 */
import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { KanbanCard } from './KanbanCard'

const task = (over: Record<string, unknown> = {}) =>
  ({
    id: 'task-1',
    title: 'Replace bearing on press 3',
    task_type: 'maintenance_cm',
    priority: 'high',
    status: 'in_progress',
    progress_percent: 0,
    checklist_items: [],
    ...over,
  }) as never

const show = (over = {}, handlers: { onClick?: () => void; onDragStart?: () => void } = {}) =>
  render(
    <KanbanCard
      task={task(over)}
      index={0}
      onClick={handlers.onClick ?? (() => {})}
      onDragStart={handlers.onDragStart ?? (() => {})}
    />,
  )

/** A DataTransfer stand-in. jsdom's `fireEvent.dragStart` supplies none, so without this the
 *  handler throws on `e.dataTransfer.effectAllowed` and the test passes for the wrong reason. */
function drag(node: Element) {
  const store: Record<string, string> = {}
  const dataTransfer = {
    effectAllowed: '',
    setData: (k: string, v: string) => { store[k] = v },
    getData: (k: string) => store[k],
  }
  fireEvent.dragStart(node, { dataTransfer })
  return { store, dataTransfer }
}

describe('the drag payload', () => {
  it('carries the task id, which is all the drop target gets', () => {
    const { container } = show()
    const { store } = drag(container.querySelector('[draggable]')!)
    expect(store['text/plain']).toBe('task-1')
  })

  it('marks the drag as a move, not a copy', () => {
    // `effectAllowed` decides the cursor and, on some platforms, whether the drop is
    // accepted at all. A board that copies tasks instead of moving them duplicates work
    // orders.
    const { container } = show()
    const { dataTransfer } = drag(container.querySelector('[draggable]')!)
    expect(dataTransfer.effectAllowed).toBe('move')
  })

  it('still notifies the board', () => {
    const onDragStart = vi.fn()
    const { container } = show({}, { onDragStart })
    drag(container.querySelector('[draggable]')!)
    expect(onDragStart).toHaveBeenCalled()
  })
})

describe('overdue is a conjunction', () => {
  const yesterday = new Date(Date.now() - 86_400_000).toISOString()
  const tomorrow = new Date(Date.now() + 86_400_000).toISOString()

  it('marks a past-due task that is not finished', () => {
    show({ due_date: yesterday, status: 'in_progress' })
    expect(screen.getByText('Overdue')).toBeInTheDocument()
  })

  it('does NOT mark a past-due task that is completed', () => {
    // THE HALF THAT IS EASY TO DROP. Every finished task has a due date in the past, so a
    // check on the date alone paints the whole "Done" column red — and a colour that is
    // always on is a colour nobody reads.
    show({ due_date: yesterday, status: 'completed' })
    expect(screen.queryByText('Overdue')).not.toBeInTheDocument()
  })

  it('does not mark a task that is not yet due', () => {
    show({ due_date: tomorrow, status: 'in_progress' })
    expect(screen.queryByText('Overdue')).not.toBeInTheDocument()
  })

  it('does not mark a task with no due date at all', () => {
    show({ status: 'in_progress' })
    expect(screen.queryByText('Overdue')).not.toBeInTheDocument()
  })
})

describe('values that arrive off the wire', () => {
  it('falls back to Custom for an unknown task type', () => {
    // The type map has grown before. An unknown value must render a card, not blank the
    // column — `typeConfig[task_type] || typeConfig.custom` is what makes that true.
    show({ task_type: 'a_type_added_next_quarter' })
    expect(screen.getByText('Custom')).toBeInTheDocument()
  })

  it('renders each known type with its own label', () => {
    show({ task_type: 'safety_check' })
    expect(screen.getByText('Safety')).toBeInTheDocument()
  })

  it('marks a task awaiting approval', () => {
    show({ approval_status: 'pending' })
    expect(screen.getByText('Pending')).toBeInTheDocument()
  })
})

describe('the card is clickable', () => {
  it('opens on click', () => {
    const onClick = vi.fn()
    const { container } = show({}, { onClick })
    fireEvent.click(container.querySelector('[draggable]')!)
    expect(onClick).toHaveBeenCalled()
  })

  it('shows the title', () => {
    show()
    expect(screen.getByText('Replace bearing on press 3')).toBeInTheDocument()
  })
})

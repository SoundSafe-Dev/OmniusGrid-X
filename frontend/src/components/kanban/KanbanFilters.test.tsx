/**
 * The kanban filter bar (FS-651).
 *
 * 177 lines, previously a `() => null` stub in the page test. Two behaviours here have a
 * wrong answer that looks identical to the right one on screen:
 *
 *   * **Clearing a select must send `undefined`, not `''`.** The handlers are written
 *     `e.target.value || undefined` — because an empty string is a *value*, and the store
 *     forwards any truthy-or-not check it makes to the server as `?priority=`. A board
 *     filtered on the empty string returns nothing, and the user sees an empty board with
 *     the filter reading "All".
 *   * **"Clear all" has to name every field.** It resets by listing them, so a filter added
 *     later and not added there survives the clear — the board stays filtered while the bar
 *     says it is not, which is the one state a user cannot diagnose.
 */
import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { KanbanFilters } from './KanbanFilters'

const show = (filters: Record<string, unknown> = {}) => {
  const onFiltersChange = vi.fn()
  render(
    <KanbanFilters
      filters={{ view_type: 'all', ...filters } as never}
      onFiltersChange={onFiltersChange}
    />,
  )
  return { onFiltersChange }
}

describe('clearing one filter', () => {
  it('sends undefined rather than an empty string', () => {
    // `?priority=` is a filter on the empty string, which matches nothing. The board comes
    // back empty while the control reads "All Priorities" — an empty result the user has
    // no way to attribute.
    const { onFiltersChange } = show({ priority: 'critical' })
    fireEvent.change(screen.getByLabelText(/priority/i), { target: { value: '' } })
    expect(onFiltersChange).toHaveBeenCalledWith({ priority: undefined })
  })

  it('passes a real selection through unchanged', () => {
    const { onFiltersChange } = show()
    fireEvent.change(screen.getByLabelText(/priority/i), { target: { value: 'critical' } })
    expect(onFiltersChange).toHaveBeenCalledWith({ priority: 'critical' })
  })
})

describe('"Clear all"', () => {
  it('is offered only when something is filtered', () => {
    show()
    expect(screen.queryByRole('button', { name: /clear all/i })).not.toBeInTheDocument()
  })

  it('appears once a filter is set', () => {
    show({ status: 'blocked' })
    expect(screen.getByRole('button', { name: /clear all/i })).toBeInTheDocument()
  })

  it('resets every filter the bar can set, not just the visible ones', () => {
    // It clears by NAMING each field. A filter added later and forgotten here survives the
    // clear, so the board stays filtered while the bar says it is not.
    const { onFiltersChange } = show({ status: 'blocked' })
    fireEvent.click(screen.getByRole('button', { name: /clear all/i }))
    const cleared = onFiltersChange.mock.calls[0][0]
    for (const field of [
      'asset_id', 'task_type', 'priority', 'assignee_id', 'status', 'date_from', 'date_to',
    ]) {
      expect(cleared).toHaveProperty(field, undefined)
    }
    expect(cleared.view_type).toBe('all')
  })
})

describe('the controls are labelled', () => {
  it.each([
    [/view/i], [/task type/i], [/priority/i], [/status/i],
  ])('%s is reachable by its label', (label) => {
    // FS-553 gave these `htmlFor`. Without it a screen reader announces "combo box" and
    // nothing else — and a test that queries by label is what keeps the association.
    show()
    expect(screen.getByLabelText(label)).toBeInTheDocument()
  })
})

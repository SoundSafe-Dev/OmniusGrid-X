/**
 * The kanban metrics bar (FS-651).
 *
 * 109 lines, previously a `() => null` stub. Five counts and one duration, all read at a
 * glance and none of them checked until now.
 *
 * THE ONE THAT MATTERED WAS `avg_cycle_time_minutes`. It was rendered behind a truthiness
 * gate — `{metrics.avg_cycle_time_minutes && (…)}` — which hid the panel when the value
 * was **zero** as readily as when it was absent. Fixed to `!= null` here. Those mean different things: absent is "not
 * measured yet", and zero is a board where tasks are closing the moment they open, which is
 * either extraordinary throughput or a workflow that is not being used. Both are worth
 * seeing, and the gate shows neither.
 *
 * That is the same shape as a failed read rendering as an empty list, on a number rather
 * than a collection: **falsy is not absent.**
 */
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { KanbanMetricsBar } from './KanbanMetricsBar'

const metrics = (over: Record<string, unknown> = {}) =>
  ({
    total_tasks: 42,
    tasks_completed_today: 7,
    tasks_awaiting_approval: 2,
    overdue_tasks: 3,
    active_escalations: 1,
    ...over,
  }) as never

describe('the counts', () => {
  it('shows each figure it is given', () => {
    render(<KanbanMetricsBar metrics={metrics()} />)
    for (const n of ['42', '7', '2', '3', '1']) {
      expect(screen.getAllByText(n).length).toBeGreaterThan(0)
    }
  })

  it('renders a zero rather than blanking the tile', () => {
    // A board with nothing overdue should say "0", not go quiet. An absent tile reads as
    // "not measured"; a zero reads as "measured, and none" — which is the good news.
    render(<KanbanMetricsBar metrics={metrics({ overdue_tasks: 0, total_tasks: 0 })} />)
    expect(screen.getAllByText('0').length).toBeGreaterThan(0)
  })
})

describe('cycle time', () => {
  it('reads minutes under an hour', () => {
    render(<KanbanMetricsBar metrics={metrics({ avg_cycle_time_minutes: 45 })} />)
    expect(screen.getByText('45m')).toBeInTheDocument()
  })

  it('reads hours under a day', () => {
    render(<KanbanMetricsBar metrics={metrics({ avg_cycle_time_minutes: 300 })} />)
    expect(screen.getByText('5h')).toBeInTheDocument()
  })

  it('reads days beyond that', () => {
    render(<KanbanMetricsBar metrics={metrics({ avg_cycle_time_minutes: 60 * 24 * 3 })} />)
    expect(screen.getByText('3d')).toBeInTheDocument()
  })

  it('is hidden when the metric is absent', () => {
    render(<KanbanMetricsBar metrics={metrics()} />)
    expect(screen.queryByText(/Avg Cycle Time/i)).not.toBeInTheDocument()
  })

  it('SHOWS a measured zero, because falsy is not absent', () => {
    // The gate was `{metrics.avg_cycle_time_minutes && …}`, which hid zero as readily as
    // absent. Absent means "not measured yet"; zero means tasks are closing the moment they
    // open — extraordinary throughput, or a workflow nobody is using. Both are worth
    // seeing, and truthiness showed neither. Now `!= null`.
    render(<KanbanMetricsBar metrics={metrics({ avg_cycle_time_minutes: 0 })} />)
    expect(screen.getByText(/Avg Cycle Time/i)).toBeInTheDocument()
    expect(screen.getByText('0m')).toBeInTheDocument()
  })
})

describe('a bar showing figures that stopped arriving', () => {
  /**
   * The store polls metrics every 30 seconds and used to swallow a failed poll into the
   * console, keeping the last values it had. So a board whose metrics endpoint died an hour
   * ago rendered hour-old throughput, WIP and cycle time as the current state of the floor.
   *
   * The numbers stay — the last known state is worth more than a blank bar — but they are
   * labelled, because an unlabelled stale reading is the one a supervisor acts on.
   */
  it('says nothing extra while the figures are current', () => {
    render(<KanbanMetricsBar metrics={metrics()} />)
    expect(screen.queryByRole('status')).toBeNull()
  })

  it('says the figures are not updating when they are stale', () => {
    render(<KanbanMetricsBar metrics={metrics()} stale />)
    expect(screen.getByRole('status')).toHaveTextContent(/not updating/i)
  })

  it('still shows the last figures rather than hiding them', () => {
    // Blanking the bar on a failed poll trades a confident wrong answer for no answer, and
    // the operator loses the last thing they knew. The label is what makes keeping them safe.
    render(<KanbanMetricsBar metrics={metrics({ total_tasks: 47 })} stale />)
    expect(screen.getByText('47')).toBeInTheDocument()
  })
})

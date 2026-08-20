/**
 * The schedules page (P9, page-enhancement review).
 *
 * THE BIGGEST HOLE THE SURVEY FOUND: nine endpoints with zero frontend references.
 * `/admin/export-deliveries` showed that a scheduled report had failed while nothing in
 * the product could say what the schedule was, who received it, when it next ran, or how
 * to pause it.
 *
 * What is pinned here is what an admin would be misled by: a failed load must not read as
 * "nothing is scheduled"; a missing SMTP config must be stated rather than inferred from
 * reports that never arrive; a pause that failed must say so, because an admin who
 * believes a report has stopped will not chase it again.
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { DialogProvider } from '../../components/ui'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { describe, expect, it, vi, beforeEach } from 'vitest'

const list = vi.fn()
const listTemplates = vi.fn()
const update = vi.fn()
const remove = vi.fn()
const create = vi.fn()

vi.mock('../../api/exportDeliveries', () => ({
  exportSchedulesApi: {
    list: (...a: unknown[]) => list(...a),
    listTemplates: (...a: unknown[]) => listTemplates(...a),
    update: (...a: unknown[]) => update(...a),
    remove: (...a: unknown[]) => remove(...a),
    create: (...a: unknown[]) => create(...a),
  },
}))

const { ExportSchedules } = await import('./ExportSchedules')

const schedule = (over: Record<string, unknown> = {}) => ({
  id: 's1',
  organization_id: 'org1',
  template_id: 't1',
  name: 'Weekly OEE',
  frequency: 'weekly',
  timezone: 'America/Chicago',
  next_run_at: '2026-08-20T08:00:00Z',
  recipients: ['plant@example.com'],
  is_active: true,
  last_run_at: '2026-08-13T08:00:00Z',
  last_status: 'sent',
  created_at: null,
  updated_at: null,
  ...over,
})

const show = () => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      {/* FS-766. The page confirms destructive actions through `DialogProvider` now
          rather than `window.confirm`, and `useDialog` throws outside its provider on
          purpose — a silent no-op would let a delete proceed unconfirmed. The test tree
          therefore has to include it, exactly as `App.tsx` does. */}
      <DialogProvider><MemoryRouter><ExportSchedules /></MemoryRouter></DialogProvider>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  list.mockReset()
  listTemplates.mockReset()
  update.mockReset()
  remove.mockReset()
  create.mockReset()
  list.mockResolvedValue({ items: [schedule()], total: 1, delivery_configured: true })
  listTemplates.mockResolvedValue({ items: [{ id: 't1', name: 'OEE summary' }], total: 1 })
})

describe('the schedule list', () => {
  it('names the schedule, its template and its recipients', async () => {
    show()
    expect(await screen.findByText('Weekly OEE')).toBeInTheDocument()
    expect(await screen.findByText('OEE summary')).toBeInTheDocument()
    expect(screen.getByText(/plant@example.com/)).toBeInTheDocument()
  })

  it('does not render a failed load as an empty schedule list', async () => {
    list.mockRejectedValue(new Error('500'))
    show()
    expect(await screen.findByText(/could not load scheduled exports/i)).toBeInTheDocument()
    expect(screen.queryByText(/no scheduled exports yet/i)).not.toBeInTheDocument()
  })

  it('says plainly when nothing is scheduled', async () => {
    list.mockResolvedValue({ items: [], total: 0, delivery_configured: true })
    show()
    expect(await screen.findByText(/no scheduled exports yet/i)).toBeInTheDocument()
  })

  it('warns when there is no delivery channel at all', async () => {
    // The server sends `delivery_configured` precisely so this can be stated rather than
    // inferred from reports that never arrive, one by one.
    list.mockResolvedValue({ items: [schedule()], total: 1, delivery_configured: false })
    show()
    expect(await screen.findByText(/no delivery channel is configured/i)).toBeInTheDocument()
  })

  it('shows "paused" instead of a next run that will not happen', async () => {
    list.mockResolvedValue({
      // `last_run_at` nulled so the ONLY date this row could render is the next run —
      // the last-send column legitimately prints one and would mask the assertion.
      items: [
        schedule({
          is_active: false,
          next_run_at: '2026-08-20T08:00:00Z',
          last_run_at: null,
          last_status: null,
        }),
      ],
      total: 1,
      delivery_configured: true,
    })
    show()
    await screen.findByText('Weekly OEE')

    // ASSERT THE ABSENCE, not the presence of the word "paused" — the badge beside the
    // name says "paused" too, so a presence-only check passed with the cell still
    // printing the stale date (caught by mutation). The row must not assert a run
    // nobody is going to get.
    expect(screen.queryAllByText(/2026/)).toEqual([])
  })

  it('does show the next run for a schedule that is actually going to run', async () => {
    // NEGATIVE CONTROL for the assertion above: a column that never printed a date
    // would pass it and be useless.
    list.mockResolvedValue({
      items: [
        schedule({
          is_active: true,
          next_run_at: '2026-08-20T08:00:00Z',
          last_run_at: null,
          last_status: null,
        }),
      ],
      total: 1,
      delivery_configured: true,
    })
    show()
    await screen.findByText('Weekly OEE')
    expect(screen.queryAllByText(/2026/).length).toBeGreaterThan(0)
  })

  it('flags a schedule that delivers to nobody', async () => {
    list.mockResolvedValue({
      items: [schedule({ recipients: [] })],
      total: 1,
      delivery_configured: true,
    })
    show()
    expect(await screen.findByText(/nobody/i)).toBeInTheDocument()
  })
})

describe('pausing and deleting', () => {
  it('pauses through the update endpoint rather than deleting', async () => {
    // An admin who wants a report to stop this month should not have to destroy its
    // definition and remember how to rebuild it.
    show()
    fireEvent.click(await screen.findByRole('button', { name: /pause weekly oee/i }))
    await waitFor(() =>
      expect(update).toHaveBeenCalledWith('s1', { is_active: false }),
    )
    expect(remove).not.toHaveBeenCalled()
  })

  it('says a pause that did not happen', async () => {
    update.mockRejectedValue(new Error('500'))
    show()
    fireEvent.click(await screen.findByRole('button', { name: /pause weekly oee/i }))
    expect((await screen.findByRole('alert')).textContent).toMatch(/could not pause/i)
  })

  it('asks before deleting, and does nothing when refused', async () => {
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(false)
    show()
    fireEvent.click(await screen.findByRole('button', { name: /delete weekly oee/i }))
    expect(remove).not.toHaveBeenCalled()
    confirmSpy.mockRestore()
  })
})

describe('creating a schedule', () => {
  it('creates it paused so the recipient list can be checked first', async () => {
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true)
    create.mockResolvedValue(schedule())
    show()
    fireEvent.click(await screen.findByRole('button', { name: /new schedule/i }))

    fireEvent.change(await screen.findByLabelText(/^template$/i), { target: { value: 't1' } })
    fireEvent.change(screen.getByLabelText(/schedule name/i), { target: { value: 'Nightly' } })
    fireEvent.change(screen.getByLabelText(/first run/i), {
      target: { value: '2026-09-01T08:00' },
    })
    fireEvent.change(screen.getByLabelText(/recipients/i), {
      target: { value: 'a@example.com, b@example.com' },
    })
    fireEvent.click(screen.getByRole('button', { name: /create paused/i }))

    await waitFor(() => expect(create).toHaveBeenCalled())
    expect(create.mock.lastCall?.[0].name).toBe('Nightly')
    expect(create.mock.lastCall?.[0].template_id).toBe('t1')
    confirmSpy.mockRestore()
  })

  it('sends an aware timestamp — the server rejects a naive one', async () => {
    create.mockResolvedValue(schedule())
    show()
    fireEvent.click(await screen.findByRole('button', { name: /new schedule/i }))
    fireEvent.change(await screen.findByLabelText(/^template$/i), { target: { value: 't1' } })
    fireEvent.change(screen.getByLabelText(/schedule name/i), { target: { value: 'Nightly' } })
    fireEvent.change(screen.getByLabelText(/first run/i), {
      target: { value: '2026-09-01T08:00' },
    })
    fireEvent.click(screen.getByRole('button', { name: /create paused/i }))
    await waitFor(() => expect(create).toHaveBeenCalled())
    // A datetime-local input carries no zone; the ISO string must.
    expect(create.mock.lastCall?.[0].next_run_at).toMatch(/Z$|[+-]\d{2}:\d{2}$/)
    expect(create.mock.lastCall?.[0].is_active).toBe(false)
  })

  it('splits the recipient list on commas', async () => {
    create.mockResolvedValue(schedule())
    show()
    fireEvent.click(await screen.findByRole('button', { name: /new schedule/i }))
    fireEvent.change(await screen.findByLabelText(/^template$/i), { target: { value: 't1' } })
    fireEvent.change(screen.getByLabelText(/schedule name/i), { target: { value: 'Nightly' } })
    fireEvent.change(screen.getByLabelText(/first run/i), {
      target: { value: '2026-09-01T08:00' },
    })
    fireEvent.change(screen.getByLabelText(/recipients/i), {
      target: { value: 'a@example.com, b@example.com' },
    })
    fireEvent.click(screen.getByRole('button', { name: /create paused/i }))
    await waitFor(() => expect(create).toHaveBeenCalled())
    expect(create.mock.lastCall?.[0].recipients).toEqual(['a@example.com', 'b@example.com'])
  })
})

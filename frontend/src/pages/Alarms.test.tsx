import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi, beforeEach } from 'vitest'

// Alarms handled loading and an empty state but not fetch errors — a failed
// load rendered the header over an empty list (blank). This locks in an error
// state.

const useAlarms = vi.fn()
const acknowledge = { mutate: vi.fn(), isPending: false }
// Typed explicitly: inferring from the default return narrows `data` to `{ count: number }`,
// and the failure cases below hand it `undefined`. `tsc` caught this; `vitest run` does not
// typecheck, so a test appended after the last typecheck can be green and still not compile.
type ActiveAlarmsResult = { data: { count: number } | undefined; isError: boolean }
const activeAlarms = vi.fn(
  (): ActiveAlarmsResult => ({ data: { count: 0 }, isError: false }),
)
const acknowledgeAll = { mutate: vi.fn(), isPending: false }
const clearAlarm = { mutate: vi.fn(), isPending: false }
vi.mock('../hooks', () => ({
  useAlarms: (args: any) => useAlarms(args),
  useActiveAlarms: () => activeAlarms(),
  useAcknowledgeAlarm: () => acknowledge,
  useAcknowledgeAllAlarms: () => acknowledgeAll,
  useClearAlarm: () => clearAlarm,
  // The asset filter dropdown; empty is a valid fleet.
  useAssets: () => ({ data: { items: [], total: 0, hasMore: false } }),
}))
// A HAND-WRITTEN MODULE MOCK IS A SECOND IMPLEMENTATION, and it drifts (FS-766). This
// listed three exports; the page then imported ErrorState and the suite failed with
// "No ErrorState export is defined on the mock" — a real change reported as a mock defect.
// ErrorState renders its retry control for real here, because the assertion below is about
// whether the user can recover, and a stub would make that assertion meaningless.
vi.mock('../components/ui', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../components/ui')>()),
  Tooltip: ({ children }: any) => <>{children}</>,
  TooltipTrigger: ({ children }: any) => children,
  TooltipContent: () => null,
  useToast: () => ({ success: vi.fn(), error: vi.fn(), info: vi.fn() }),
}))

import Alarms from './Alarms'

const renderAlarms = () => render(<MemoryRouter><Alarms /></MemoryRouter>)

describe('Alarms page states', () => {
  beforeEach(() => useAlarms.mockReset())

  it('shows an error state (not a blank screen) when the fetch fails', () => {
    useAlarms.mockReturnValue({ data: undefined, isLoading: false, isError: true })
    renderAlarms()
    expect(screen.getByRole('alert')).toHaveTextContent(/could not be loaded/i)
  })

  it('lets the operator retry without losing their filters', () => {
    // THE ASSERTION THAT MATTERS (FS-766). The old copy said "Check your connection and
    // try again" and offered no way to try again, so the only recovery was a reload —
    // which discards the filters and time range on the page an operator opens BECAUSE
    // something is wrong. Asserting the message alone passed happily against that.
    const refetch = vi.fn()
    useAlarms.mockReturnValue({
      data: undefined, isLoading: false, isError: true, refetch, isFetching: false,
    })
    renderAlarms()

    // `fireEvent`, matching the rest of this file rather than introducing a second
    // interaction style for one assertion.
    fireEvent.click(screen.getByRole('button', { name: /retry/i }))
    expect(refetch).toHaveBeenCalledTimes(1)
  })

  it('disables the retry control while the retry is in flight', () => {
    // Otherwise a slow backend collects one request per impatient click.
    useAlarms.mockReturnValue({
      data: undefined, isLoading: false, isError: true, refetch: vi.fn(), isFetching: true,
    })
    renderAlarms()
    expect(screen.getByRole('button', { name: /retrying/i })).toBeDisabled()
  })

  it('shows the empty state when there are no alarms', () => {
    useAlarms.mockReturnValue({
      data: { items: [], total: 0, skip: 0, limit: 20 },
      isLoading: false, isError: false,
    })
    renderAlarms()
    expect(screen.getByText(/no alarms/i)).toBeInTheDocument()
  })
})

/**
 * A failed acknowledgement (FS-480).
 *
 * `useAcknowledgeAlarm` lives in `useAlarms.ts`, and both mutation sweeps scanned `.tsx`
 * only — so this was outside them entirely. The page read `isPending` and nothing else: the
 * spinner stopped and the row stayed unacknowledged, which is exactly what it looks like for
 * the moment before the list refetches. The operator's reasonable reading is that it worked,
 * and the alarm nobody owns is the one nobody chases.
 */
describe('an acknowledgement that did not happen', () => {
  // The page reads the camelCase shape the api client already maps to, and the button
  // only renders for an alarm that is active AND not yet acknowledged — which is the only
  // state in which this failure can happen.
  const alarm = {
    id: 'al-1',
    assetId: 'a1',
    assetName: 'Press 1',
    severity: 'critical',
    message: 'Vibration above threshold',
    isActive: true,
    isAcknowledged: false,
    triggeredAt: '2026-08-05T00:00:00Z',
  }

  beforeEach(() => {
    useAlarms.mockReset()
    acknowledge.mutate = vi.fn()
    useAlarms.mockReturnValue({
      data: { items: [alarm], total: 1, skip: 0, limit: 20 },
      isLoading: false,
      isError: false,
    })
  })

  it('says the alarm is still unacknowledged', () => {
    // The page passes a per-call `onError`, so the failure is driven by invoking it.
    acknowledge.mutate = vi.fn((_vars, opts) => opts?.onError?.(new Error('502')))
    renderAlarms()

    fireEvent.click(screen.getByRole('button', { name: /acknowledge/i }))

    const alert = screen.getByRole('alert')
    expect(alert.textContent).toMatch(/could not/i)
    expect(alert.textContent).toMatch(/still unacknowledged|not acknowledged/i)
  })

  it('says nothing when it succeeded', () => {
    // The other direction: a banner on every acknowledgement would make the failure above
    // indistinguishable from the normal case.
    acknowledge.mutate = vi.fn((_vars, opts) => opts?.onSuccess?.())
    renderAlarms()

    fireEvent.click(screen.getByRole('button', { name: /acknowledge/i }))

    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })
})

describe('the summary cards when the active-alarm count is unavailable', () => {
  /**
   * `useActiveAlarms` polls every ten seconds and both cards read only its `data`.
   * `activeAlarms?.count || 0` turns a failure into a zero, so a feed that has never answered
   * rendered **"Active 0"** — and the card beside it computes `total - count`, so it rendered
   * every alarm on the page as **acknowledged**.
   *
   * This is the page an operator opens because they are worried about alarms. Two confident
   * wrong numbers, from one missing `isError`.
   */
  it('shows the count when the feed is answering', async () => {
    activeAlarms.mockReturnValue({ data: { count: 3 }, isError: false })
    render(<MemoryRouter><Alarms /></MemoryRouter>)
    expect(await screen.findByText('3')).toBeInTheDocument()
  })

  it('does not report zero active alarms when the count could not be fetched', async () => {
    activeAlarms.mockReturnValue({ data: undefined, isError: true })
    render(<MemoryRouter><Alarms /></MemoryRouter>)
    await screen.findAllByText('—')
    // A dash is not a number. What matters is that no confident zero is on screen.
    expect(screen.queryByText('0')).toBeNull()
  })

  it('does not report every alarm acknowledged when the count is missing', async () => {
    // The worse of the two: `total - 0` is `total`, so a dead feed said the whole page had
    // been dealt with. Both cards go to a dash together, because one is derived from the other.
    activeAlarms.mockReturnValue({ data: undefined, isError: true })
    render(<MemoryRouter><Alarms /></MemoryRouter>)
    expect((await screen.findAllByText('—')).length).toBe(2)
  })

  it('keeps a stale count out of the cards too', async () => {
    // react-query holds the last successful `data` across a failure, so this is the shape the
    // bug takes after the feed has worked once — a number nobody can date.
    activeAlarms.mockReturnValue({ data: { count: 3 }, isError: true })
    render(<MemoryRouter><Alarms /></MemoryRouter>)
    await screen.findAllByText('—')
    expect(screen.queryByText('3')).toBeNull()
  })
})

/**
 * The filter bar (page-enhancement P1). Every control maps onto a query param
 * `alarmsApi.list` supported for releases while the page sent only `skip` — and the
 * backend silently defaults to the last 24 hours when no range is sent, which made the
 * "Total Alarms" tile a 24h count under an "all history" tooltip. The contract now:
 * an explicit start_time is ALWAYS sent, and changing any filter returns to page one.
 */
describe('the filter bar', () => {
  const alarm = {
    id: 'al-2',
    assetId: 'a1',
    assetName: 'Press 1',
    severity: 'high',
    message: 'Temp high',
    isActive: true,
    isAcknowledged: false,
    occurredAt: '2026-08-05T00:00:00Z',
  }

  beforeEach(() => {
    useAlarms.mockReset()
    useAlarms.mockReturnValue({
      data: { items: [alarm], total: 40, skip: 20, limit: 20, hasMore: true },
      isLoading: false,
      isError: false,
    })
    activeAlarms.mockReturnValue({ data: { count: 1 }, isError: false })
  })

  it('always sends an explicit start time — the 24h default is a choice, not a surprise', () => {
    renderAlarms()
    const filters = useAlarms.mock.calls[useAlarms.mock.calls.length - 1]?.[0]
    expect(filters.startTime).toBeTruthy()
    const age = Date.now() - new Date(filters.startTime).getTime()
    expect(age).toBeGreaterThan(23 * 3600 * 1000)
    expect(age).toBeLessThan(25 * 3600 * 1000)
  })

  it('sends the severity param and resets to page one when the filter changes', () => {
    renderAlarms()
    fireEvent.change(screen.getByLabelText(/severity/i), { target: { value: 'critical' } })
    const filters = useAlarms.mock.calls[useAlarms.mock.calls.length - 1]?.[0]
    expect(filters.severity).toBe('critical')
    expect(filters.skip).toBe(0)
  })

  it('maps the status select onto isActive', () => {
    renderAlarms()
    fireEvent.change(screen.getByLabelText(/status/i), { target: { value: 'cleared' } })
    expect(useAlarms.mock.calls[useAlarms.mock.calls.length - 1]?.[0].isActive).toBe(false)
  })

  it('sends the epoch for all-time so the backend default cannot reassert itself', () => {
    renderAlarms()
    fireEvent.change(screen.getByLabelText(/time range/i), { target: { value: 'all' } })
    const filters = useAlarms.mock.calls[useAlarms.mock.calls.length - 1]?.[0]
    expect(new Date(filters.startTime).getTime()).toBe(0)
  })

  it('the count tile names its window instead of claiming all history', () => {
    renderAlarms()
    expect(screen.getByText(/alarms \(last 24h\)/i)).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText(/time range/i), { target: { value: '7d' } })
    expect(screen.getByText(/alarms \(last 7 days\)/i)).toBeInTheDocument()
  })
})

/**
 * The two dormant mutations, now wired: acknowledge-all (scoped to the severity filter)
 * and per-row clear. Both report failure through the same banner as single
 * acknowledgement — a bulk action that fails silently is FS-480 multiplied by the fleet.
 */
describe('acknowledge-all and clear', () => {
  const ackedAlarm = {
    id: 'al-3',
    assetId: 'a1',
    assetName: 'Press 1',
    severity: 'critical',
    message: 'Vibration above threshold',
    isActive: true,
    isAcknowledged: true,
    occurredAt: '2026-08-05T00:00:00Z',
  }

  beforeEach(() => {
    useAlarms.mockReset()
    useAlarms.mockReturnValue({
      data: { items: [ackedAlarm], total: 1, skip: 0, limit: 20 },
      isLoading: false,
      isError: false,
    })
    activeAlarms.mockReturnValue({ data: { count: 2 }, isError: false })
    acknowledgeAll.mutate = vi.fn()
    clearAlarm.mutate = vi.fn()
  })

  it('scopes acknowledge-all to the severity filter', () => {
    renderAlarms()
    fireEvent.change(screen.getByLabelText(/severity/i), { target: { value: 'critical' } })
    fireEvent.click(screen.getByRole('button', { name: /acknowledge all critical/i }))
    expect(acknowledgeAll.mutate).toHaveBeenCalledWith(
      { severity: 'critical' },
      expect.anything(),
    )
  })

  it('reports an acknowledge-all failure in the banner', () => {
    acknowledgeAll.mutate = vi.fn((_vars: any, opts: any) => opts?.onError?.(new Error('502')))
    renderAlarms()
    fireEvent.click(screen.getByRole('button', { name: /acknowledge all/i }))
    expect(screen.getByRole('alert').textContent).toMatch(/could not acknowledge all/i)
  })

  it('offers clear on an active acknowledged alarm and reports its failure', () => {
    clearAlarm.mutate = vi.fn((_id: any, opts: any) => opts?.onError?.(new Error('502')))
    renderAlarms()
    fireEvent.click(screen.getByRole('button', { name: /^clear$/i }))
    expect(clearAlarm.mutate).toHaveBeenCalledWith('al-3', expect.anything())
    expect(screen.getByRole('alert').textContent).toMatch(/could not clear/i)
  })
})

/** Acknowledge with a note: the one-click path is untouched; "+ note" expands an input
 * whose Enter submits the comment through the same mutation. */
describe('acknowledge with a note', () => {
  const alarm = {
    id: 'al-4',
    assetId: 'a1',
    assetName: 'Press 1',
    severity: 'high',
    message: 'Door open',
    isActive: true,
    isAcknowledged: false,
    occurredAt: '2026-08-05T00:00:00Z',
  }

  beforeEach(() => {
    useAlarms.mockReset()
    useAlarms.mockReturnValue({
      data: { items: [alarm], total: 1, skip: 0, limit: 20 },
      isLoading: false,
      isError: false,
    })
    activeAlarms.mockReturnValue({ data: { count: 1 }, isError: false })
    acknowledge.mutate = vi.fn()
  })

  it('sends the note as the acknowledgement comment', () => {
    renderAlarms()
    fireEvent.click(screen.getByRole('button', { name: /\+ note/i }))
    fireEvent.change(screen.getByLabelText(/acknowledgement note/i), {
      target: { value: 'Cleared jam, restarting' },
    })
    fireEvent.keyDown(screen.getByLabelText(/acknowledgement note/i), { key: 'Enter' })
    expect(acknowledge.mutate).toHaveBeenCalledWith(
      { alarmId: 'al-4', comment: 'Cleared jam, restarting' },
      expect.anything(),
    )
  })

  it('the plain acknowledge stays one-click with no comment', () => {
    renderAlarms()
    fireEvent.click(screen.getByRole('button', { name: /^acknowledge$/i }))
    expect(acknowledge.mutate).toHaveBeenCalledWith(
      { alarmId: 'al-4', comment: undefined },
      expect.anything(),
    )
  })
})

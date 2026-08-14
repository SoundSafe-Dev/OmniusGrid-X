/**
 * The shop-floor page — where a wrong screen becomes a wrong payroll record.
 *
 * The last large routed page from FS-364 with no test. Almost everything here is written
 * with unusual care: every mutation reads `isError` and says what did NOT happen in the
 * operator's own terms ("YOUR CLOCK IS STILL RUNNING and no hours were posted"), the ledger
 * distinguishes a failed load from an empty backlog, and two places deliberately refuse to
 * show a client-side duration next to a payroll or cost claim. Those are asserted here so
 * they stay true.
 *
 * **The one that was wrong** (FS-482). `ClockTime` read `data` and `isLoading` from the
 * open-clock query and not `isError`. On a failed lookup `open` is `undefined` and
 * `isLoading` is `false` — which is the exact shape of "no clock is running". So the card
 * rendered the **Clock in** button to somebody who may already be clocked in.
 *
 * That is the dangerous direction, and the page already knew it: the message under that very
 * button reads "two open clocks produce overlapping hours and payroll cannot tell which is
 * real". A failed read defaulted into the state that causes the thing the page warns about.
 *
 * The fix shows neither button. Offering "Clock out" would be the mirror defect — telling an
 * operator who is not clocked in that they are.
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const openLaborEntry = vi.fn()
const clockIn = vi.fn()
const clockOut = vi.fn()
const listPostings = vi.fn()
const openDowntime = vi.fn()
const startDowntime = vi.fn()
const endDowntime = vi.fn()

vi.mock('../api/shopFloor', () => ({
  shopFloorApi: {
    openLaborEntry: (...a: unknown[]) => openLaborEntry(...a),
    clockIn: (...a: unknown[]) => clockIn(...a),
    clockOut: (...a: unknown[]) => clockOut(...a),
    listPostings: (...a: unknown[]) => listPostings(...a),
    openDowntime: (...a: unknown[]) => openDowntime(...a),
    startDowntime: (...a: unknown[]) => startDowntime(...a),
    endDowntime: (...a: unknown[]) => endDowntime(...a),
    recordProduction: vi.fn(),
    recordQualityEvent: vi.fn(),
    issuePart: vi.fn(),
    acknowledgePosting: vi.fn(),
  },
}))

vi.mock('../api', () => ({
  assetsApi: {
    list: vi.fn().mockResolvedValue({
      items: [
        { id: 'a1', name: 'Press 1' },
        { id: 'a2', name: 'CNC Mill' },
      ],
      total: 2,
      hasMore: false,
    }),
  },
}))

const { default: ShopFloor } = await import('./ShopFloor')

const show = () => {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, refetchInterval: false } },
  })
  return render(
    <QueryClientProvider client={client}>
      <ShopFloor />
    </QueryClientProvider>,
  )
}

const laborEntry = (over: Record<string, unknown> = {}) => ({
  id: 'lab-1',
  workOrderRef: 'WO-88',
  clockInAt: '2026-08-06T07:00:00Z',
  clockOutAt: null,
  ...over,
})

beforeEach(() => {
  openLaborEntry.mockReset()
  clockIn.mockReset()
  clockOut.mockReset()
  listPostings.mockReset()
  openDowntime.mockReset()
  startDowntime.mockReset()
  endDowntime.mockReset()
  openLaborEntry.mockResolvedValue(null)
  listPostings.mockResolvedValue({ items: [], total: 0, truncated: false })
  openDowntime.mockResolvedValue([])
})

describe('a clock lookup that failed is not "no clock running" (FS-482)', () => {
  it('does not offer to clock in', async () => {
    // The sharp assertion. An operator already clocked in, shown a Clock in button, presses
    // it — and payroll now has two overlapping entries and no way to tell which is real.
    openLaborEntry.mockRejectedValue(new Error('502'))
    show()

    await waitFor(() =>
      expect(screen.getByText(/could not check whether you already have a clock/i)).toBeInTheDocument(),
    )
    expect(screen.queryByRole('button', { name: /clock in/i })).not.toBeInTheDocument()
  })

  it('does not offer to clock out either', async () => {
    // The mirror defect. Falling back to the other branch would tell an operator who is not
    // clocked in that they are, which is the same lie pointing the other way.
    openLaborEntry.mockRejectedValue(new Error('502'))
    show()

    await waitFor(() => expect(screen.getByRole('button', { name: /check again/i })).toBeInTheDocument())
    expect(screen.queryByRole('button', { name: /clock out/i })).not.toBeInTheDocument()
  })

  it('offers to clock in when the lookup says there is no open clock', async () => {
    // The other direction: a card that refused to show either button whenever the answer
    // was "none" would pass the two tests above and remove the feature.
    openLaborEntry.mockResolvedValue(null)
    show()

    await waitFor(() =>
      expect(screen.getByRole('button', { name: /clock in/i })).toBeInTheDocument(),
    )
    expect(screen.queryByText(/could not check whether/i)).not.toBeInTheDocument()
  })

  it('offers to clock out when a clock is running, and says since when', async () => {
    openLaborEntry.mockResolvedValue(laborEntry())
    show()

    await waitFor(() =>
      expect(screen.getByRole('button', { name: /clock out/i })).toBeInTheDocument(),
    )
    expect(screen.getByText(/clocked in since/i)).toBeInTheDocument()
    expect(screen.getByText(/WO-88/)).toBeInTheDocument()
  })
})

describe('a failed clock action says what did not happen', () => {
  it('tells an operator leaving the floor that their clock is still running', async () => {
    // Not "an error occurred". The consequence of a failed clock-OUT is that hours keep
    // accruing against them, and the remedy is to not walk away.
    openLaborEntry.mockResolvedValue(laborEntry())
    clockOut.mockRejectedValue(new Error('502'))
    show()

    fireEvent.click(await screen.findByRole('button', { name: /clock out/i }))

    await waitFor(() =>
      expect(screen.getByText(/YOUR CLOCK IS STILL RUNNING/)).toBeInTheDocument(),
    )
    expect(screen.getByText(/no hours were posted/i)).toBeInTheDocument()
  })

  it('warns about the double clock when clocking in fails', async () => {
    openLaborEntry.mockResolvedValue(null)
    clockIn.mockRejectedValue(new Error('409'))
    show()

    fireEvent.click(await screen.findByRole('button', { name: /clock in/i }))

    await waitFor(() =>
      expect(screen.getByText(/two open clocks produce overlapping hours/i)).toBeInTheDocument(),
    )
  })

  it('says nothing when the clock-in succeeded', async () => {
    openLaborEntry.mockResolvedValue(null)
    clockIn.mockResolvedValue(laborEntry())
    show()

    fireEvent.click(await screen.findByRole('button', { name: /clock in/i }))

    await waitFor(() => expect(clockIn).toHaveBeenCalled())
    expect(screen.queryByText(/two open clocks/i)).not.toBeInTheDocument()
  })
})

describe('the ledger distinguishes a failed load from an empty backlog', () => {
  it('says which it was', async () => {
    // An empty table reads as "nothing outstanding", which is the opposite of what a failed
    // load means — and "nothing outstanding" is a reason to go home.
    listPostings.mockRejectedValue(new Error('down'))
    show()

    await waitFor(() =>
      expect(screen.getByText(/not an empty backlog/i)).toBeInTheDocument(),
    )
  })

  it('shows the ledger when it loads', async () => {
    listPostings.mockResolvedValue({ items: [], total: 0, truncated: false })
    show()

    await waitFor(() => expect(screen.getByText(/0 total/)).toBeInTheDocument())
    expect(screen.queryByText(/not an empty backlog/i)).not.toBeInTheDocument()
  })

  it('says when the table is a page of a longer list', async () => {
    listPostings.mockResolvedValue({
      items: [
        {
          id: 'p1',
          postedAt: '2026-08-06T08:00:00Z',
          domain: 'production',
          summary: 'WO-88 quantity 12',
          acknowledgedAt: null,
          acknowledgementRef: null,
        },
      ],
      total: 240,
      truncated: true,
    })
    show()

    await waitFor(() => expect(screen.getByText(/showing the first 1/i)).toBeInTheDocument())
  })
})


/**
 * Open downtime lives on the SERVER, not in component state (P5, page-enhancement
 * review). The open event id used to live in useState, so a page reload stranded an
 * in-progress downtime: the machine stayed recorded as down, the operator who started
 * it could not end it, and no other operator could see it existed.
 */
describe('open downtime survives the browser', () => {
  const downEvent = {
    id: 'dt-1',
    assetId: 'a1',
    downtimeType: 'unplanned',
    reasonCode: 'jam',
    description: null,
    startedAt: '2026-08-13T07:00:00Z',
    endedAt: null,
    durationMinutes: null,
  }

  it('shows a downtime this browser never started, named by machine', async () => {
    openDowntime.mockResolvedValue([downEvent])
    show()
    // findAllBy: "Press 1" appears both in the down-machine row and as a picker option.
    expect((await screen.findAllByText(/press 1/i)).length).toBeGreaterThan(0)
    expect(screen.getByRole('button', { name: /machine is back up/i })).toBeInTheDocument()
  })

  it('any operator can end it, and the list refreshes from the server', async () => {
    openDowntime.mockResolvedValue([downEvent])
    endDowntime.mockResolvedValue({ id: 'dt-1', fanout: null })
    show()
    fireEvent.click(await screen.findByRole('button', { name: /machine is back up/i }))
    await waitFor(() => expect(endDowntime).toHaveBeenCalledWith('dt-1'))
  })

  it('a failed open-downtime load is said, not rendered as an empty floor', async () => {
    // "No machines are down" and "we could not ask" are different statements, and only
    // one of them means the floor is fine.
    openDowntime.mockRejectedValue(new Error('500'))
    show()
    expect(
      await screen.findByText(/could not load open downtime/i),
    ).toBeInTheDocument()
  })

  it('the asset is picked from a list, not typed as a UUID', async () => {
    show()
    // Wait for the option list to load before selecting — changing a <select> to a
    // value with no matching option leaves it at '' and the button disabled.
    await screen.findAllByRole('option', { name: 'CNC Mill' })
    const picker = (await screen.findAllByRole('combobox', { name: /asset/i }))[0]
    fireEvent.change(picker, { target: { value: 'a2' } })
    fireEvent.click(screen.getByRole('button', { name: /start downtime/i }))
    await waitFor(() =>
      expect(startDowntime).toHaveBeenCalledWith(
        expect.objectContaining({ assetId: 'a2' }),
      ),
    )
  })
})

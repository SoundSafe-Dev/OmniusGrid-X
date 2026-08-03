/**
 * The yard page — five queries, one of which used to be a feature that could not exist.
 *
 * `yard.getDockDoors` sent a `workcell_id` the endpoint never declared, and `dock_doors`
 * has no workcell column, so it could never have been honoured. Only the mock branch —
 * filtering fixture data on a field the real model lacks — made it look implemented.
 * Four other yard GETs took `organization_id` as a REQUIRED client-supplied query
 * parameter, which is both the IDOR shape `app/core/tenant.py` forbids and simply broken:
 * no caller sent it, so every one returned 422 to the page below. They now derive the
 * organisation from the token.
 *
 * All of that is asserted server-side. What was never asserted is this page: whether it
 * distinguishes "no trailers in the yard" from "the request failed", and whether its
 * search narrows what the operator sees without quietly dropping rows it should not.
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const getTrailers = vi.fn()
const getDockDoors = vi.fn()
const getAppointments = vi.fn()
const getDetentionAlerts = vi.fn()
const getDwellTimes = vi.fn()

vi.mock('../../api', () => ({
  yardApi: {
    getTrailers: (...a: unknown[]) => getTrailers(...a),
    getDockDoors: (...a: unknown[]) => getDockDoors(...a),
    getAppointments: (...a: unknown[]) => getAppointments(...a),
    getDetentionAlerts: (...a: unknown[]) => getDetentionAlerts(...a),
    getDwellTimes: (...a: unknown[]) => getDwellTimes(...a),
    checkInTrailer: vi.fn(),
  },
}))

import { TooltipProvider } from '../../components/ui'
import { YardManagement } from './YardManagement'

const trailer = (over: Record<string, unknown> = {}) => ({
  id: 't-1',
  trailerId: 'TR-1001',
  carrierName: 'Acme Freight',
  licensePlate: 'ABC-123',
  status: 'checked_in',
  checkedInAt: '2026-07-28T08:00:00Z',
  checkedOutAt: null,
  assignedDoorId: null,
  dwellMinutes: 45,
  ...over,
})

const wrap = () => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <TooltipProvider>
        <YardManagement />
      </TooltipProvider>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  // Shapes taken from the client's own signatures, not guessed: getTrailers and
  // getAppointments return PaginatedResponse envelopes, getDockDoors and
  // getDetentionAlerts return bare arrays, and getDwellTimes returns a summary object.
  // Guessing wrong here throws inside the page ("doors.filter is not a function") and
  // renders an empty document, which reads as a component bug.
  getTrailers.mockResolvedValue({ items: [trailer()], total: 1, skip: 0, limit: 50, hasMore: false })
  getDockDoors.mockResolvedValue([])
  getAppointments.mockResolvedValue({ items: [], total: 0, skip: 0, limit: 50, hasMore: false })
  getDetentionAlerts.mockResolvedValue([])
  getDwellTimes.mockResolvedValue({ avgDwellTime: 45, maxDwellTime: 120, trailersExceedingTarget: 0 })
})

describe('YardManagement', () => {
  it('lists a trailer the yard returned', async () => {
    wrap()
    expect(await screen.findByText('TR-1001')).toBeInTheDocument()
  })

  it('asks for dock doors without a workcell filter', async () => {
    // The endpoint declares no `workcell_id`, and `dock_doors` has no workcell column.
    // FastAPI drops unknown query parameters silently, so passing one returned every
    // door while reading, at the call site, as a filtered request.
    wrap()
    await screen.findByText('TR-1001')
    await waitFor(() => expect(getDockDoors).toHaveBeenCalled())
    expect(JSON.stringify(getDockDoors.mock.calls)).not.toContain('workcell')
  })

  it('sends no tenant identifier on any yard query', async () => {
    // Four of these GETs used to REQUIRE a client-supplied organization_id -- the IDOR
    // shape, and broken besides, since no caller sent it and every request 422'd.
    wrap()
    await screen.findByText('TR-1001')
    await waitFor(() => expect(getDwellTimes).toHaveBeenCalled())
    const everything = JSON.stringify([
      getTrailers.mock.calls,
      getDockDoors.mock.calls,
      getAppointments.mock.calls,
      getDetentionAlerts.mock.calls,
      getDwellTimes.mock.calls,
    ])
    expect(everything).not.toContain('organization_id')
    expect(everything).not.toContain('organizationId')
  })
})

describe('YardManagement — an empty yard is not a failed request', () => {
  it('says the yard is empty when it genuinely is', async () => {
    getTrailers.mockResolvedValue({ items: [], total: 0, skip: 0, limit: 50, hasMore: false })
    wrap()
    expect(await screen.findByText('No trailers found')).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('does not render a failure as an empty yard', async () => {
    // THE ASSERTION THIS BLOCK EXISTS FOR, and the page failed it. There was no error
    // branch, so a rejected query fell through to `trailers.length === 0` and rendered
    // "No trailers found" — which a yard manager reads as an operational fact and acts
    // on. The two states have to say different things.
    //
    // The first version of this test only checked that TR-1001 was absent, which is
    // true in BOTH states, so it passed against the defect. Asserting the two branches
    // by their own text is what made the page's silence visible.
    getTrailers.mockRejectedValue(new Error('yard unreachable'))
    wrap()
    expect(await screen.findByRole('alert')).toBeInTheDocument()
    expect(screen.queryByText('No trailers found')).not.toBeInTheDocument()
  })

  it('offers a retry on failure rather than a dead end', async () => {
    getTrailers.mockRejectedValue(new Error('yard unreachable'))
    wrap()
    await screen.findByRole('alert')
    const before = getTrailers.mock.calls.length
    fireEvent.click(screen.getByRole('button', { name: /retry/i }))
    await waitFor(() => expect(getTrailers.mock.calls.length).toBeGreaterThan(before))
  })
})

describe('YardManagement — search', () => {
  const fleet = [
    trailer({ id: 't-1', trailerId: 'TR-1001', carrierName: 'Acme Freight' }),
    trailer({ id: 't-2', trailerId: 'TR-2002', carrierName: 'Bolt Haulage' }),
  ]

  it('narrows by trailer id', async () => {
    getTrailers.mockResolvedValue({ items: fleet, total: 2, skip: 0, limit: 50, hasMore: false })
    wrap()
    await screen.findByText('TR-1001')
    fireEvent.change(screen.getByPlaceholderText(/search/i), {
      target: { value: 'TR-2002' },
    })
    await waitFor(() => expect(screen.queryByText('TR-1001')).not.toBeInTheDocument())
    expect(screen.getByText('TR-2002')).toBeInTheDocument()
  })

  it('narrows by carrier name, not just id', async () => {
    // The filter reads three fields. Pinning only the id would let a change silently
    // reduce it to one and nobody would notice until an operator searched a carrier.
    getTrailers.mockResolvedValue({ items: fleet, total: 2, skip: 0, limit: 50, hasMore: false })
    wrap()
    await screen.findByText('TR-1001')
    fireEvent.change(screen.getByPlaceholderText(/search/i), {
      target: { value: 'Bolt' },
    })
    await waitFor(() => expect(screen.queryByText('TR-1001')).not.toBeInTheDocument())
    expect(screen.getByText('TR-2002')).toBeInTheDocument()
  })

  it('restores the full list when the search is cleared', async () => {
    getTrailers.mockResolvedValue({ items: fleet, total: 2, skip: 0, limit: 50, hasMore: false })
    wrap()
    await screen.findByText('TR-1001')
    const box = screen.getByPlaceholderText(/search/i)
    fireEvent.change(box, { target: { value: 'TR-2002' } })
    await waitFor(() => expect(screen.queryByText('TR-1001')).not.toBeInTheDocument())
    fireEvent.change(box, { target: { value: '' } })
    expect(await screen.findByText('TR-1001')).toBeInTheDocument()
  })
})


describe('what the operator actually reads', () => {
  // Both of these were found by LOOKING at a screenshot of the running page against seeded
  // data. Every structural check passed: the text was present, there were no console errors,
  // no failed requests, and the page was not blank. It was just wrong.

  it('does not print a raw uuid where a trailer physically is', async () => {
    // A docked trailer has no `yardLocation`, so the Location column fell through to
    // `assignedDoorId` and rendered "88888888-0000-4000-8000-000000000003" in a column an
    // operator reads to go and find the trailer.
    getTrailers.mockResolvedValue({
      items: [trailer({ trailerId: 'TR-2002', status: 'docked', yardLocation: null,
                        assignedDoorId: 'door-uuid-1' })],
      total: 1, skip: 0, limit: 50, hasMore: false,
    })
    getDockDoors.mockResolvedValue([
      { id: 'door-uuid-1', doorNumber: '12', status: 'occupied', doorType: 'inbound' },
    ])
    wrap()

    expect(await screen.findByText('TR-2002')).toBeInTheDocument()
    expect(await screen.findByText('Door 12')).toBeInTheDocument()
    expect(screen.queryByText('door-uuid-1')).not.toBeInTheDocument()
  })

  it('says so rather than showing the id when the door cannot be resolved', async () => {
    getTrailers.mockResolvedValue({
      items: [trailer({ trailerId: 'TR-2003', status: 'docked', yardLocation: null,
                        assignedDoorId: 'missing-door' })],
      total: 1, skip: 0, limit: 50, hasMore: false,
    })
    getDockDoors.mockResolvedValue([])
    wrap()

    expect(await screen.findByText('TR-2003')).toBeInTheDocument()
    expect(await screen.findByText('Door (unknown)')).toBeInTheDocument()
    expect(screen.queryByText('missing-door')).not.toBeInTheDocument()
  })

  it('does not render a floating-point artifact in a detention figure', async () => {
    // The banner read "4h 11.300000000000011m excess" next to a dollar amount the operator
    // is expected to act on. `minutes % 60` on a float from the detention calculator.
    // Shape read off `DetentionAlert` in types/logistics.ts, not invented: the charge field
    // is `currentCharge`, and the banner calls `.toLocaleString()` on it, so a fixture
    // missing it throws and renders an empty document — which reads as a component bug
    // rather than a bad fixture. This test file's own header warns about exactly that.
    getDetentionAlerts.mockResolvedValue([{
      trailerId: 'TR-4482', trailerNumber: 'TR-4482', status: 'detention',
      licensePlate: 'IL TRL4482', carrierName: 'Great Lakes Freight',
      yardLocation: 'Zone A-04', checkInAt: '2026-08-03T12:00:00Z',
      elapsedMinutes: 371.3, freeMinutes: 120,
      detentionMinutes: 251.30000000000001, currentCharge: 209.46,
    }])
    wrap()

    const excess = await screen.findByText(/excess/)
    expect(excess.textContent).toMatch(/^4h 11m excess$/)
    expect(excess.textContent).not.toMatch(/\d\.\d{3,}/)
  })
})

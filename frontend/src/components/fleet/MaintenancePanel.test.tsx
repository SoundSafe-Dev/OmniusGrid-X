/**
 * The maintenance panel, and a number it displayed that no system had ever produced.
 *
 * The row line read `Mileage: {item.currentMileage.toLocaleString()}`. There is no
 * `current_mileage` column and the API has never sent one — the client's adapter filled it
 * from `dueMileage`, the odometer at which the service falls DUE, and from `0` when that
 * was missing too. So the panel printed either the wrong mileage under a label a technician
 * reads as the vehicle's present one (they differ by exactly the distance left before the
 * service) or a vehicle with no miles on it.
 *
 * The priority badge beside it was the same shape: the column did not exist until migration
 * 054, so the adapter substituted the literal `'medium'` — not a member of the declared
 * union — and every row showed it whatever the operator had chosen on the form.
 *
 * AND THE FORM COULD NOT CREATE ANYTHING. `create_schedule` demanded `vehicleId`; this
 * form sends `vehicleNumber`, which is the name the backend itself uses when it reads the
 * row back. Every creation failed with "vehicleId is required" on the real path.
 *
 * NONE OF THIS WAS VISIBLE TO A TEST, because the mock fixtures supplied `currentMileage`
 * and a real `priority`. A mock more generous than the wire hides exactly the class of
 * defect that mock-mode testing exists to surface — so these tests drive the client
 * directly with the shape the API actually returns.
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const getSchedules = vi.fn()
const getActiveRepairOrders = vi.fn()
const getMaintenanceCosts = vi.fn()
const getMaintenanceStatistics = vi.fn()
const createSchedule = vi.fn()

vi.mock('../../api', async () => {
  const actual = await vi.importActual<any>('../../api')
  return {
    ...actual,
    maintenanceApi: {
      getSchedules: (...a: unknown[]) => getSchedules(...a),
      getActiveRepairOrders: (...a: unknown[]) => getActiveRepairOrders(...a),
      getMaintenanceCosts: (...a: unknown[]) => getMaintenanceCosts(...a),
      getMaintenanceStatistics: (...a: unknown[]) => getMaintenanceStatistics(...a),
      createSchedule: (...a: unknown[]) => createSchedule(...a),
    },
  }
})

import { MaintenancePanel } from './MaintenancePanel'

// EXACTLY what `_schedule_out` emits — no currentMileage, no assignedTechnician. Writing
// the fixture from the serializer rather than from the TypeScript type is the whole point:
// the type described fields the wire never carried.
const schedule = (over: Record<string, unknown> = {}) => ({
  id: 'sch-1',
  vehicleId: 'TRK-001',
  vehicleNumber: 'TRK-001',
  serviceType: 'oil_change',
  description: '15,000 mile service',
  scheduledDate: '2026-08-12T00:00:00Z',
  dueMileage: 145000,
  status: 'scheduled',
  priority: 'urgent',
  estimatedCost: 125,
  ...over,
})

// Costs is an OBJECT (`MaintenanceCosts`), not a list, and the panel renders
// `costs.totalYTD.toFixed(...)` unguarded — an array fixture throws during render and
// yields an empty document, which reads as a broken component rather than a bad fixture.
// That has now cost time on four separate page tests in this repo; the rule is to copy
// the shape from the client's declared return type, never to guess it.
const COSTS = {
  totalYTD: 12500,
  monthlyAverage: 1040,
  costPerVehicle: 3125,
  upcomingEstimated: 800,
  byCategory: { oil_change: 500 },
  monthlyBreakdown: [{ month: 'Jul', cost: 1040 }],
}

// The panel reads these four names; the client adapts the backend's own keys into them.
const STATS = { totalSchedules: 1, overdue: 0, activeROs: 0, urgentROs: 0 }

beforeEach(() => {
  vi.clearAllMocks()
  getSchedules.mockResolvedValue([schedule()])
  getActiveRepairOrders.mockResolvedValue([])
  getMaintenanceCosts.mockResolvedValue(COSTS)
  getMaintenanceStatistics.mockResolvedValue(STATS)
  createSchedule.mockResolvedValue({ id: 'sch-2' })
})

describe('MaintenancePanel — the mileage it prints', () => {
  it('labels the due odometer as the due odometer', async () => {
    render(<MaintenancePanel />)
    expect(await screen.findByText('15,000 mile service')).toBeInTheDocument()
    expect(screen.getByText(/Due at 145,000 mi/)).toBeInTheDocument()
  })

  it('does not present it as the vehicle’s current mileage', async () => {
    // THE ASSERTION THIS FILE EXISTS FOR. "Mileage: 145,000" and "Due at 145,000 mi" are
    // the same number meaning two different things, and only one of them is true.
    render(<MaintenancePanel />)
    await screen.findByText('15,000 mile service')
    expect(screen.queryByText(/^Mileage:/)).not.toBeInTheDocument()
  })

  it('prints no mileage at all when the schedule carries none', async () => {
    // It printed "Mileage: 0" — a reading, and a vehicle with no miles on it. Absence is
    // not zero, and here the honest render is nothing.
    getSchedules.mockResolvedValue([schedule({ dueMileage: undefined })])
    render(<MaintenancePanel />)
    await screen.findByText('15,000 mile service')
    expect(screen.queryByText(/Due at/)).not.toBeInTheDocument()
    expect(screen.queryByText(/\b0\b mi/)).not.toBeInTheDocument()
  })
})

describe('MaintenancePanel — the priority it shows', () => {
  it('shows the priority the schedule actually carries', async () => {
    render(<MaintenancePanel />)
    await screen.findByText('15,000 mile service')
    expect(screen.getAllByText('urgent').length).toBeGreaterThan(0)
  })

  it('does not substitute a value that is not in the union', async () => {
    // Every row used to render 'medium' — the adapter's invention, and not one of
    // low | normal | high | urgent.
    render(<MaintenancePanel />)
    await screen.findByText('15,000 mile service')
    expect(screen.queryByText('medium')).not.toBeInTheDocument()
  })

  it('distinguishes one priority from another', async () => {
    // The control that rules out a hardcoded badge: a panel printing 'urgent' for
    // everything would satisfy both tests above.
    getSchedules.mockResolvedValue([schedule({ priority: 'low' })])
    render(<MaintenancePanel />)
    await screen.findByText('15,000 mile service')
    expect(screen.getAllByText('low').length).toBeGreaterThan(0)
    expect(screen.queryByText('urgent')).not.toBeInTheDocument()
  })
})

describe('MaintenancePanel — the repair orders tab', () => {
  // EXACTLY what `_order_out` emits. `repair_orders` has no work-order number, no parts
  // list, no labour hours and no technician — the adapter used to manufacture the first
  // two and the panel renders the rest conditionally.
  const order = (over: Record<string, unknown> = {}) => ({
    id: '9f1c2b7e-4a3d-4e55-b1aa-77c0e5d13f42',
    vehicleId: 'TRK-001',
    vehicleNumber: 'TRK-001',
    title: 'Brake pads worn past limit',
    issueDescription: 'Brake pads worn past limit',
    status: 'in_progress',
    priority: 'high',
    vendor: 'Acme Brakes',
    cost: 480,
    category: 'brakes',
    openedAt: '2026-07-20T00:00:00Z',
    reportedDate: '2026-07-20T00:00:00Z',
    partsUsed: [],
    ...over,
  })

  const openRepairs = async (o = order()) => {
    getActiveRepairOrders.mockResolvedValue([o])
    render(<MaintenancePanel />)
    await screen.findByText('15,000 mile service')
    fireEvent.click(screen.getByRole('button', { name: /repair orders/i }))
    // findAllBy: the description is the row's body text, and is also its heading when a
    // real work-order number exists, so the singular query is ambiguous by design.
    await screen.findAllByText('Brake pads worn past limit')
  }

  it('shows the recorded cost as a cost, not as an estimate', async () => {
    await openRepairs()
    expect(screen.getByText('$480')).toBeInTheDocument()
    expect(screen.getByText('cost')).toBeInTheDocument()
    // It was fed from `repair_orders.cost` — what the repair COST — under a caption
    // reading "estimated". Nobody estimated anything.
    expect(screen.queryByText('estimated')).not.toBeInTheDocument()
  })

  it('shows no figure at all for a repair with no cost recorded', async () => {
    // THE ASSERTION THIS BLOCK EXISTS FOR. `?? 0` rendered "$0 estimated" — a free
    // repair, and an estimate nobody made.
    await openRepairs(order({ cost: undefined }))
    expect(screen.queryByText('$0')).not.toBeInTheDocument()
    expect(screen.queryByText('cost')).not.toBeInTheDocument()
  })

  it('does not head the row with an identifier no system issued', async () => {
    // `workOrderNumber` was `id.slice(0, 8)` — eight characters of a UUID, rendered as
    // the heading a technician would quote to a vendor. With no real number the heading
    // is simply absent; the description below already identifies the row.
    await openRepairs()
    expect(screen.queryByText('9f1c2b7e')).not.toBeInTheDocument()
    expect(screen.getAllByText('Brake pads worn past limit')).toHaveLength(1)
  })

  it('uses a real work-order number when one is supplied', async () => {
    // The positive control: dropping the field entirely would satisfy the test above.
    await openRepairs(order({ workOrderNumber: 'WO-2026-0042' }))
    expect(screen.getByText('WO-2026-0042')).toBeInTheDocument()
  })
})

describe('MaintenancePanel — the costs tab', () => {
  // The server sends `ytdTotal` and `byCategory`. Nothing else. Three of the five figures
  // on this tab were manufactured in the client: two hardcoded to 0 and one as `ytd / 12`
  // regardless of the month.
  const WIRE_COSTS = { totalYTD: 12000, byCategory: { brakes: 3000 }, monthlyBreakdown: [] }

  const openCosts = async (c: Record<string, unknown> = WIRE_COSTS) => {
    getMaintenanceCosts.mockResolvedValue(c)
    render(<MaintenancePanel />)
    await screen.findByText('15,000 mile service')
    fireEvent.click(screen.getByRole('button', { name: /cost analysis/i }))
  }

  it('shows the YTD total the server reported', async () => {
    // The positive control for the omissions below.
    await openCosts()
    expect(await screen.findByText('Total YTD')).toBeInTheDocument()
    expect(screen.getAllByText('$12,000').length).toBeGreaterThan(0)
  })

  it('does not report a per-vehicle cost of zero', async () => {
    // `costPerVehicle: 0`, hardcoded, rendered as "Per Vehicle $0" — a fleet whose
    // maintenance costs nothing per vehicle.
    await openCosts()
    await screen.findByText('Total YTD')
    expect(screen.queryByText('Per Vehicle')).not.toBeInTheDocument()
  })

  it('does not report zero upcoming cost in a highlighted box', async () => {
    // The sharper of the two: highlighted, so it reads as "nothing is coming up" rather
    // than "nobody calculated this".
    await openCosts()
    await screen.findByText('Total YTD')
    expect(screen.queryByText(/Upcoming \(Est\.\)/)).not.toBeInTheDocument()
  })

  it('does not divide the year-to-date total by twelve', async () => {
    // `ytd / 12` is wrong in every month but December — in February it understates the
    // real monthly average roughly sixfold.
    await openCosts()
    await screen.findByText('Total YTD')
    expect(screen.queryByText('Monthly Average')).not.toBeInTheDocument()
    expect(screen.queryByText('$1,000')).not.toBeInTheDocument()
  })

  it('says the missing figures are not reported rather than leaving a gap', async () => {
    await openCosts()
    expect(
      await screen.findByText(/not reported by this deployment/i),
    ).toBeInTheDocument()
  })

  it('shows the figures when a deployment does report them', async () => {
    // The control that keeps the omission honest: these rows must appear when the data
    // exists, or the fix has deleted a feature rather than stopped a fabrication.
    await openCosts({ ...WIRE_COSTS, monthlyAverage: 950, costPerVehicle: 400, upcomingEstimated: 275 })
    expect(await screen.findByText('Monthly Average')).toBeInTheDocument()
    expect(screen.getByText('Per Vehicle')).toBeInTheDocument()
    expect(screen.getByText('$400')).toBeInTheDocument()
  })

  it('does not print NaN when the year-to-date total is zero', async () => {
    // `amount / 0` is Infinity and `NaN.toFixed(1)` renders the literal string "NaN",
    // both reachable exactly when a category breakdown means least.
    await openCosts({ totalYTD: 0, byCategory: { brakes: 0 }, monthlyBreakdown: [] })
    await screen.findByText('Costs by Category')
    expect(screen.queryByText(/NaN/)).not.toBeInTheDocument()
    expect(screen.queryByText(/Infinity/)).not.toBeInTheDocument()
  })
})

describe('MaintenancePanel — creating a schedule', () => {
  // QUERIED BY PLACEHOLDER AND INPUT TYPE, not by label. The form's `<label>`s carry no
  // `htmlFor` and its inputs no `id`, so `getByLabelText` cannot associate them — which
  // is a real accessibility defect, and one that belongs to the `htmlFor`/`aria-label`
  // sweep already assigned elsewhere. Not fixed here; worked around, and said so. The
  // one exception is the mileage field, which this change was editing anyway and now
  // carries a proper label association.
  const openForm = async () => {
    const view = render(<MaintenancePanel />)
    await screen.findByText('15,000 mile service')
    fireEvent.click(screen.getByRole('button', { name: /add maintenance schedule/i }))
    return view
  }

  const fillRequired = (container: HTMLElement) => {
    fireEvent.change(screen.getByPlaceholderText('TRK-104'), {
      target: { value: 'TRK-009' },
    })
    const date = container.querySelector('input[type="date"]') as HTMLInputElement
    fireEvent.change(date, { target: { value: '2026-09-01' } })
  }

  it('sends a vehicle identifier the endpoint accepts', async () => {
    // The form only ever knew the number it was shown. Creation failed every time with
    // "vehicleId is required" — the backend read the column out as `vehicleNumber` and
    // refused to take it back under that name.
    const { container } = await openForm()
    fillRequired(container)
    fireEvent.click(screen.getByRole('button', { name: /create schedule/i }))
    await waitFor(() => expect(createSchedule).toHaveBeenCalled())
    expect(createSchedule.mock.calls[0][0]).toMatchObject({ vehicleId: 'TRK-009' })
  })

  it('sends the mileage as the due mileage, which is the field that exists', async () => {
    const { container } = await openForm()
    fillRequired(container)
    fireEvent.change(screen.getByLabelText(/due at mileage/i), { target: { value: '150000' } })
    fireEvent.click(screen.getByRole('button', { name: /create schedule/i }))
    await waitFor(() => expect(createSchedule).toHaveBeenCalled())
    const payload = createSchedule.mock.calls[0][0]
    expect(payload.dueMileage).toBe(150000)
    expect(payload).not.toHaveProperty('currentMileage')
  })

  it('omits the mileage entirely when the field is left blank', async () => {
    // `Number('') || 0` sent a real zero, which the schema would now store as "due at
    // zero miles" — a fabricated threshold rather than an absent one.
    const { container } = await openForm()
    fillRequired(container)
    fireEvent.click(screen.getByRole('button', { name: /create schedule/i }))
    await waitFor(() => expect(createSchedule).toHaveBeenCalled())
    expect(createSchedule.mock.calls[0][0]).not.toHaveProperty('dueMileage')
  })
})

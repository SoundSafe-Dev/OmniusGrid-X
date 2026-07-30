import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { loadInRealMode, restoreMockMode } from '../test/realMode'

/**
 * REAL-MODE tests for the maintenance client.
 *
 * WHY THIS MODULE. `MaintenanceSchedule.currentMileage` was the entry point for the whole
 * declared-but-unsent sweep: the adapter filled it from `dueMileage` — the odometer at which
 * the service falls DUE — and the panel printed it as "Mileage: 128,500", which a technician
 * reads as where the vehicle IS. Every fix since has been in this file or the panel beside it,
 * and none of it was covered by a test that ran the real branch, because
 * `src/test/setup.ts` forces `VITE_USE_MOCK='true'` before any module evaluates.
 *
 * WHAT THESE PIN, and it is the harder half: that the adapters do NOT invent. Most tests
 * assert a value is present; the defect class here is a value that is present and made up, so
 * these feed the adapters exactly what the serializer emits and assert nothing else appears.
 *
 * `test_frontend_fields_exist_on_the_wire.py` catches a reintroduction from the backend's side
 * by comparing declarations against the tree. This catches it where the change would actually
 * be made, and it catches the one thing that guard cannot: a field the adapter SYNTHESISES at
 * runtime, which is invisible to a static read of the types.
 */

const get = vi.fn()
const post = vi.fn()
const patch = vi.fn()

vi.mock('./client', () => ({
  api: {
    get: (...args: unknown[]) => get(...args),
    post: (...args: unknown[]) => post(...args),
    patch: (...args: unknown[]) => patch(...args),
  },
}))
vi.mock('./transformRegistry', () => ({ registerTransform: vi.fn() }))

type AnyApi = Record<string, (...args: any[]) => Promise<any>>

async function maintenance(): Promise<AnyApi> {
  const mod = await loadInRealMode(() => import('./maintenance'))
  return (mod as unknown as { maintenanceApi: AnyApi }).maintenanceApi
}

/** EXACTLY what `_order_out` emits — id, vehicleId, title, description, status, priority,
 *  vendor, cost, category, openedAt, completedAt. Nothing else. */
const WIRE_ORDER = {
  id: '9f1c2b7e-4a3d-4e55-b1aa-77c0e5d13f42',
  vehicleId: 'veh-1',
  title: 'Brake pads worn past limit',
  description: 'Both front pads below 2mm.',
  status: 'in_progress',
  priority: 'high',
  vendor: 'Acme Brakes',
  cost: 480,
  category: 'brakes',
  openedAt: '2026-07-20T00:00:00Z',
  completedAt: null,
}

/** EXACTLY what `_schedule_out` emits. */
const WIRE_SCHEDULE = {
  id: 'sch-1',
  vehicleId: 'veh-1',
  vehicleNumber: 'veh-1',
  serviceType: 'oil_change',
  description: '15,000 mile service',
  scheduledDate: '2026-08-15T00:00:00Z',
  dueMileage: 150000,
  status: 'scheduled',
  priority: 'normal',
  estimatedCost: 240,
}

beforeEach(() => {
  vi.clearAllMocks()
})

afterEach(() => {
  restoreMockMode()
})

describe('the repair-order adapter invents nothing', () => {
  it('passes through exactly what the serializer sent', async () => {
    get.mockResolvedValue({ data: [WIRE_ORDER] })
    const api = await maintenance()

    const [order] = await api.getRepairOrders()

    // `vehicleNumber` is the ONE legitimate client-side derivation: the serializer does not
    // send it, and the card needs something to label the row with.
    const { vehicleNumber, ...rest } = order
    expect(vehicleNumber).toBe('veh-1')
    expect(rest).toEqual(WIRE_ORDER)
  })

  it('does not synthesise a work-order number from the id', async () => {
    // THE ASSERTION THIS FILE EXISTS FOR. `workOrderNumber: o.id.slice(0, 8)` — eight
    // characters of a UUID, rendered as the heading a technician would quote to a vendor. No
    // system in this product issues one.
    get.mockResolvedValue({ data: [WIRE_ORDER] })
    const api = await maintenance()

    const [order] = await api.getRepairOrders()

    expect(order).not.toHaveProperty('workOrderNumber')
    // The id naturally contains its own first eight characters, so scanning the whole object
    // for them flags the `id` field itself — the first version of this test did exactly that.
    // The claim is that no OTHER field is a truncation of the id.
    const derivedFromId = Object.entries(order).filter(
      ([key, value]) =>
        key !== 'id' && typeof value === 'string' && WIRE_ORDER.id.startsWith(value),
    )
    expect(derivedFromId).toEqual([])
  })

  it('does not manufacture a technician, parts list or labour hours', async () => {
    // None of these is a column on `repair_orders`. `partsUsed` was defaulted to `[]`, which
    // is not a fabrication in itself but declared a parts feature that does not exist.
    get.mockResolvedValue({ data: [WIRE_ORDER] })
    const api = await maintenance()

    const [order] = await api.getRepairOrders()

    for (const field of ['assignedTechnician', 'partsUsed', 'laborHours', 'actualCost']) {
      expect(order).not.toHaveProperty(field)
    }
  })

  it('leaves a missing cost absent rather than zero', async () => {
    // `estimatedCost: … ?? 0` printed "$0" under a caption reading "estimated". A repair with
    // no cost recorded is not a free repair.
    //
    // `null` rather than `undefined`: the serializer sends `null` and the adapter passes it
    // through unchanged, which is the point — the panel's guard is `!= null`, so both read as
    // absent and neither renders a figure. Asserting `undefined` here would have been
    // asserting a coercion nobody performs.
    get.mockResolvedValue({ data: [{ ...WIRE_ORDER, cost: null }] })
    const api = await maintenance()

    const [order] = await api.getRepairOrders()

    expect(order.cost ?? null).toBeNull()
    expect(order.cost).not.toBe(0)
  })

  it('keeps a genuine zero cost as zero', async () => {
    // The control on the test above: a warranty repair really did cost nothing, and
    // collapsing that to undefined is the same error inverted.
    get.mockResolvedValue({ data: [{ ...WIRE_ORDER, cost: 0 }] })
    const api = await maintenance()

    const [order] = await api.getRepairOrders()

    expect(order.cost).toBe(0)
  })

  it('does not invent a work-order number when creating one either', async () => {
    // The mock branch minted `WO-YYYY-NNNN` here, so the mock path produced an identifier the
    // real path never could — which is how a synthesised number came to look like a feature.
    post.mockResolvedValue({ data: WIRE_ORDER })
    const api = await maintenance()

    const created = await api.createRepairOrder({ title: 'New' })

    expect(post).toHaveBeenCalledWith('/api/v1/maintenance/repair-orders', { title: 'New' })
    expect(created).not.toHaveProperty('workOrderNumber')
  })
})

describe('the schedule adapter invents nothing', () => {
  it('passes through exactly what the serializer sent', async () => {
    get.mockResolvedValue({ data: [WIRE_SCHEDULE] })
    const api = await maintenance()

    const [schedule] = await api.getSchedules()

    expect(schedule).toEqual(WIRE_SCHEDULE)
  })

  it('does not fill a current mileage from the due mileage', async () => {
    // THE ORIGINAL DEFECT. `currentMileage: s?.currentMileage ?? s?.dueMileage ?? 0` — the
    // odometer at which the service falls DUE, printed as where the vehicle is now, or "0"
    // when neither existed.
    get.mockResolvedValue({ data: [WIRE_SCHEDULE] })
    const api = await maintenance()

    const [schedule] = await api.getSchedules()

    expect(schedule).not.toHaveProperty('currentMileage')
    expect(schedule.dueMileage).toBe(150000)
  })

  it('does not default the priority to a value the operator did not choose', async () => {
    // `priority: s?.priority ?? 'medium'` overwrote whatever came back — and 'medium' is not
    // even a member of the declared union. Migration 054 added the column; the adapter has to
    // stop covering for its absence.
    get.mockResolvedValue({ data: [{ ...WIRE_SCHEDULE, priority: 'urgent' }] })
    const api = await maintenance()

    const [schedule] = await api.getSchedules()

    expect(schedule.priority).toBe('urgent')
  })

  it('does not supply a priority the response omitted', async () => {
    // The case above cannot catch `?? 'medium'`, because the fallback only fires when the
    // field is ABSENT — and the server has sent it since migration 054, so the realistic
    // fixture never exercises the branch. This one omits it, which is the only shape under
    // which the default was ever visible: every schedule rendering as 'medium', a value that
    // is not even a member of the declared union.
    const { priority, ...withoutPriority } = WIRE_SCHEDULE
    get.mockResolvedValue({ data: [withoutPriority] })
    const api = await maintenance()

    const [schedule] = await api.getSchedules()

    expect(schedule).not.toHaveProperty('priority')
  })

  it('does not invent a technician the schedule has no column for', async () => {
    get.mockResolvedValue({ data: [WIRE_SCHEDULE] })
    const api = await maintenance()

    const [schedule] = await api.getSchedules()

    expect(schedule).not.toHaveProperty('assignedTechnician')
  })
})

describe('the costs adapter passes the server figures through', () => {
  const WIRE_COSTS = {
    ytdTotal: 12000,
    byCategory: { brakes: 3000 },
    monthlyBreakdown: [{ month: '2026-01', cost: 5000 }],
    monthlyAverage: 950,
    costPerVehicle: 400,
    upcomingEstimated: 275,
  }

  it('reports every figure the endpoint computes', async () => {
    get.mockResolvedValue({ data: WIRE_COSTS })
    const api = await maintenance()

    expect(await api.getMaintenanceCosts()).toEqual(WIRE_COSTS)
  })

  it('omits a figure an older backend does not send, rather than zeroing it', async () => {
    // `costPerVehicle: 0` and `upcomingEstimated: 0` were hardcoded here, the second rendered
    // in a highlighted box reading "Upcoming (Est.) $0" — which says "nothing is coming up"
    // rather than "nobody calculated this".
    get.mockResolvedValue({ data: { ytdTotal: 12000, byCategory: {} } })
    const api = await maintenance()

    const costs = await api.getMaintenanceCosts()

    expect(costs).not.toHaveProperty('costPerVehicle')
    expect(costs).not.toHaveProperty('upcomingEstimated')
    expect(costs).not.toHaveProperty('monthlyAverage')
    expect(costs.monthlyBreakdown).toEqual([])
  })

  it('does not divide the year-to-date total by twelve', async () => {
    // `monthlyAverage: ytd / 12`, computed in January as readily as in December. The server
    // divides by the months that have ELAPSED; the client must not second-guess it.
    get.mockResolvedValue({ data: { ytdTotal: 12000, byCategory: {}, monthlyAverage: 4000 } })
    const api = await maintenance()

    expect((await api.getMaintenanceCosts()).monthlyAverage).toBe(4000)
  })

  it('keeps a genuine zero cost-per-vehicle', async () => {
    // The control on the omission test: `null` means "no fleet to divide by" and is dropped,
    // but a real 0 is a fleet that has spent nothing and must survive.
    get.mockResolvedValue({ data: { ...WIRE_COSTS, costPerVehicle: 0 } })
    const api = await maintenance()

    expect((await api.getMaintenanceCosts()).costPerVehicle).toBe(0)
  })
})

describe('the requests go where the backend serves them', () => {
  it('lists schedules from the maintenance router', async () => {
    get.mockResolvedValue({ data: [] })
    const api = await maintenance()

    await api.getSchedules()

    expect(get).toHaveBeenCalledWith('/api/v1/maintenance/schedules')
  })

  it('asks for active repair orders with the status the endpoint accepts', async () => {
    get.mockResolvedValue({ data: [] })
    const api = await maintenance()

    await api.getActiveRepairOrders()

    expect(get).toHaveBeenCalledWith('/api/v1/maintenance/repair-orders?status=active')
  })

  it('reads costs from the endpoint that computes them', async () => {
    get.mockResolvedValue({ data: { ytdTotal: 0, byCategory: {} } })
    const api = await maintenance()

    await api.getMaintenanceCosts()

    expect(get).toHaveBeenCalledWith('/api/v1/maintenance/costs')
  })
})

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { loadInRealMode, restoreMockMode } from '../test/realMode'

/**
 * REAL-MODE tests for the transportation and yard clients.
 *
 * WHAT THESE PIN. Both clients used to send `organization_id` (transportation) and
 * `workcell_id` (yard dock doors) as query parameters. Neither is accepted any more:
 *
 *   * `organization_id` was a REQUIRED client-supplied parameter on carriers, drivers,
 *     shipments and routes — the IDOR shape — and it did not even work, because those
 *     tables have FORCE row-level security while the handler set no tenant GUC, so the
 *     policy filtered every row. Every one of those endpoints returned an empty list to
 *     every caller, including for its own organization. The org now comes from the JWT.
 *
 *   * `workcell_id` was never declared by `GET /yard/dock/doors`, and `dock_doors` has
 *     no workcell column, so it could never have been honoured. FastAPI ignores unknown
 *     query parameters SILENTLY — the request succeeds and returns the unfiltered set,
 *     which the caller then renders as though it were filtered. Only the mock branch,
 *     filtering fixture data on a field the real model lacks, made it look implemented.
 *
 * `test_frontend_query_params_are_declared.py` catches a reintroduction from the
 * backend's side. This catches it from the frontend's, and unlike that guard it runs in
 * the frontend suite where the change would actually be made.
 */

const get = vi.fn()
const post = vi.fn()

vi.mock('./client', () => ({
  api: {
    get: (...args: unknown[]) => get(...args),
    post: (...args: unknown[]) => post(...args),
  },
}))
vi.mock('./transformRegistry', () => ({ registerTransform: vi.fn() }))

type AnyApi = Record<string, (...args: any[]) => Promise<any>>

async function transportApi(): Promise<AnyApi> {
  const mod = await loadInRealMode(() => import('./transportation'))
  return (mod as unknown as { transportationApi: AnyApi }).transportationApi
}

async function yardApi(): Promise<AnyApi> {
  const mod = await loadInRealMode(() => import('./yard'))
  return (mod as unknown as { yardApi: AnyApi }).yardApi
}

function paramsOf(call: unknown[]): Record<string, unknown> {
  const config = call[call.length - 1] as { params?: Record<string, unknown> } | undefined
  return (config && typeof config === 'object' && config.params) || {}
}

beforeEach(() => {
  vi.clearAllMocks()
})

afterEach(() => {
  restoreMockMode()
})

describe('transportationApi in real mode', () => {
  it('does not send organization_id when listing carriers', async () => {
    get.mockResolvedValue({ data: [] })
    const api = await transportApi()

    await api.getCarriers()

    expect(get).toHaveBeenCalledTimes(1)
    const [url] = get.mock.calls[0] as [string]
    expect(url).toBe('/api/v1/transportation/carriers')
    expect(paramsOf(get.mock.calls[0])).not.toHaveProperty('organization_id')
  })

  it('does not send organization_id when listing drivers, but keeps carrier_id', async () => {
    get.mockResolvedValue({ data: [] })
    const api = await transportApi()

    await api.getDrivers('carrier-1')

    const params = paramsOf(get.mock.calls[0])
    expect(params).not.toHaveProperty('organization_id')
    expect(params.carrier_id).toBe('carrier-1')
  })

  it('does not send organization_id when listing shipments', async () => {
    get.mockResolvedValue({ data: { items: [], meta: { total: 0, skip: 0, limit: 0 } } })
    const api = await transportApi()

    await api.getShipments()

    expect(paramsOf(get.mock.calls[0])).not.toHaveProperty('organization_id')
  })
})

describe('yardApi in real mode', () => {
  it('requests dock doors with no query parameters at all', async () => {
    // `workcell_id` was silently ignored by the server, so a filtered request returned
    // every door and looked like a filtered result.
    get.mockResolvedValue({ data: [] })
    const api = await yardApi()

    await api.getDockDoors()

    expect(get).toHaveBeenCalledTimes(1)
    const [url, config] = get.mock.calls[0] as [string, unknown]
    expect(url).toBe('/api/v1/yard/dock/doors')
    expect(config).toBeUndefined()
  })

  it('takes no filter argument, because the column it filtered on does not exist', async () => {
    const api = await yardApi()
    expect(api.getDockDoors.length).toBe(0)
  })
})

/**
 * FS-394 — the delivery-efficiency tiles, one blank pair and one wrong by 100×.
 *
 * `getDeliveryEfficiency` declared `{onTimeRate, avgTransitTime, totalDeliveries,
 * lateDeliveries}` and returned `response.data` unchanged. Three of those four names have
 * never been on the wire: the aggregate sends `avgTransitHours`, `deliveredToday` and
 * `totalDelivered`. The backend had already recorded this in `DeliveryEfficiencyOut` and
 * deliberately did NOT reconcile from that side, because declaring the client's names there
 * would have made the schema agree with the type and disagree with the payload.
 *
 * Measured on the running page before the fix: "Average Transit Time" rendered as a bare
 * `h`, "Deliveries Today" was blank, and the "N late" line could never appear.
 *
 * AND THE ONE TILE THAT DID RENDER WAS WRONG. `onTimeRate` is a ratio 0..1 on the wire; the
 * page printed `.toFixed(1)` with a `%`, so 0.3333 displayed as **0.3%** for a real 33.3%
 * on-time rate — and the `>= 90` green threshold could never fire. The mock returned a
 * percentage for the same field, so development looked correct.
 */
describe('transportationApi.getDeliveryEfficiency in real mode', () => {
  const wire = {
    onTimeRate: 0.3333,      // RATIO, as the endpoint sends it
    avgTransitHours: 19.2,
    deliveredToday: 0,
    totalDelivered: 3,
  }

  it('converts the ratio to a percentage exactly once', async () => {
    get.mockResolvedValue({ data: wire })
    const api = await transportApi()
    const result = await api.getDeliveryEfficiency()
    // The measured payload: 33.33%, not 0.3% and not 3333%.
    expect(result.onTimeRatePct).toBeCloseTo(33.33, 2)
  })

  it('maps the field names the endpoint actually sends', async () => {
    get.mockResolvedValue({ data: wire })
    const api = await transportApi()
    expect(await api.getDeliveryEfficiency()).toEqual({
      onTimeRatePct: 33.33,
      avgTransitHours: 19.2,
      deliveredToday: 0,
      totalDelivered: 3,
    })
  })

  it('does not surface the three names that were never on the wire', async () => {
    // Stated in the negative too: a client that returned BOTH shapes would satisfy the
    // assertions above while leaving the dead names available to a new caller.
    get.mockResolvedValue({ data: wire })
    const api = await transportApi()
    const result = await api.getDeliveryEfficiency()
    for (const dead of ['avgTransitTime', 'totalDeliveries', 'lateDeliveries']) {
      expect(result).not.toHaveProperty(dead)
    }
  })

  it('reads an empty fleet as 100% on time, not 100× that', async () => {
    // The endpoint returns 1.0 for an empty fleet — "nothing was late" — which must become
    // 100%, and is the value most likely to be mishandled by a naive conversion.
    get.mockResolvedValue({ data: { onTimeRate: 1.0, avgTransitHours: 0, deliveredToday: 0, totalDelivered: 0 } })
    const api = await transportApi()
    expect((await api.getDeliveryEfficiency()).onTimeRatePct).toBe(100)
  })

  it('reports a missing figure as null rather than defaulting it', async () => {
    // THE FIRST VERSION OF THIS FIX USED `?? 0` AND `?? 1`, and
    // `apiClientsDoNotDefaultResponses` rejected it — correctly. `?? 1` on the ratio renders
    // **100% on time** whenever the payload is unusable: a green all-clear generated by the
    // absence of the data that decides it, which is the class this repo has already found
    // twice on HOS hours and once on `activeViolations`.
    //
    // The endpoint's own 1.0 means something different — it computed over zero deliveries —
    // and only it is entitled to say that. All four fields are required on
    // `DeliveryEfficiencyOut`, so null here means the response was malformed, and the page
    // renders an em dash.
    get.mockResolvedValue({ data: {} })
    const api = await transportApi()
    const result = await api.getDeliveryEfficiency()
    expect(result.onTimeRatePct).toBeNull()
    expect(result.avgTransitHours).toBeNull()
    expect(result.deliveredToday).toBeNull()
    expect(result.totalDelivered).toBeNull()
  })

  it('does not treat a real zero as missing', async () => {
    // The control on the null handling: `deliveredToday: 0` is a measurement — nothing was
    // delivered today — and a truthiness check would erase it into an em dash.
    get.mockResolvedValue({ data: { onTimeRate: 0, avgTransitHours: 0, deliveredToday: 0, totalDelivered: 0 } })
    const api = await transportApi()
    const result = await api.getDeliveryEfficiency()
    expect(result.deliveredToday).toBe(0)
    expect(result.onTimeRatePct).toBe(0)
  })
})

/**
 * FS-395 — the HOS client declared four names the wire does not have, and dropped the two
 * that say whether the answer is trustworthy.
 *
 * `DriverHOSOut` sends `driver_id`, `is_compliant`, `assessable`, `missing_data`,
 * `violations`, `warnings` and a nested `hours_summary`. The client declared
 * `{driveHoursRemaining, dutyHoursRemaining, cycleHoursUsed, currentStatus, violations}` and
 * returned `response.data` unchanged, so only `violations` resolved.
 *
 * WHAT WAS MISSING MATTERS MORE THAN WHAT WAS WRONG. `assessable` and `missingData` exist
 * because "no violations" and "nobody could tell" are different facts — the backend's words:
 * "A driver with no medical certificate on file has not broken a rule; nobody knows whether
 * they have." A type carrying only `violations` makes the second unrenderable, so the first
 * caller of this method would have painted an unassessable driver as clear. Measured against
 * the seeded fleet: `assessable: false`, `missing_data: ["No medical certificate on file"]`.
 *
 * Nothing consumes this yet, which is exactly why it is worth fixing now — it is the FS-367
 * shape, a trap waiting for its first caller.
 */
describe('transportationApi.getDriverHOS in real mode', () => {
  const wire = {
    driverId: 'drv-1',
    isCompliant: false,
    assessable: false,
    missingData: ['No medical certificate on file'],
    violations: [],
    warnings: ['Drive time nearing limit: 10.6h'],
    hoursSummary: {
      driveHoursToday: 10.6,
      onDutyHoursToday: 12.9,
      cycleHours: 61.0,
      driveHoursRemaining: 0.4,
      onDutyHoursRemaining: 1.1,
      cycleHoursRemaining: 9.0,
    },
  }

  it('surfaces the assessability caveat, not just the violations', async () => {
    get.mockResolvedValue({ data: wire })
    const api = await transportApi()
    const result = await api.getDriverHOS('drv-1')

    expect(result.assessable).toBe(false)
    expect(result.missingData).toEqual(['No medical certificate on file'])
    // The trap it replaces: an empty violations list beside `assessable: false` is NOT a
    // clean bill, and a consumer needs both to say so.
    expect(result.violations).toEqual([])
    expect(result.isCompliant).toBe(false)
  })

  it('reads the hours from where the endpoint puts them', async () => {
    get.mockResolvedValue({ data: wire })
    const api = await transportApi()
    const result = await api.getDriverHOS('drv-1')
    expect(result.hoursSummary.driveHoursRemaining).toBe(0.4)
    expect(result.hoursSummary.cycleHours).toBe(61.0)
  })

  it('no longer offers the four top-level names that were never sent', async () => {
    get.mockResolvedValue({ data: wire })
    const api = await transportApi()
    const result = await api.getDriverHOS('drv-1')
    for (const dead of ['driveHoursRemaining', 'dutyHoursRemaining', 'cycleHoursUsed', 'currentStatus']) {
      expect(result).not.toHaveProperty(dead)
    }
  })

  it('keeps null distinct from zero on the hours', async () => {
    // The distinction the old `|| 0` mock destroyed, and the reason this codebase has found
    // the same HOS defect three times: NULL means the driver has not reported, 0 means out
    // of hours. One is unknown, the other is a violation.
    get.mockResolvedValue({
      data: { ...wire, hoursSummary: { ...wire.hoursSummary, driveHoursRemaining: null, cycleHours: 0 } },
    })
    const api = await transportApi()
    const result = await api.getDriverHOS('drv-1')
    expect(result.hoursSummary.driveHoursRemaining).toBeNull()
    expect(result.hoursSummary.cycleHours).toBe(0)
  })
})

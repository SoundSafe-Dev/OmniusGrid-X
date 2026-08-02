import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { loadInRealMode, restoreMockMode } from '../test/realMode'

/**
 * REAL-MODE tests for the yard client's read paths.
 *
 * WHY, and it is a sharper reason than "coverage". `adaptTrailer` was still synthesising
 * `contents` and `poNumber` — fishing them out of the free-form `meta_data` blob — for a while
 * AFTER both fields were deleted from `YardTrailer`, and `tsc --noEmit` was clean throughout.
 *
 * TypeScript relaxes excess-property checking for an object literal that spreads an `any`, so
 * `{ ...t, contents: … }` keeps compiling once the type stops declaring `contents`. That is
 * precisely why an adapter's inventions are invisible to a sweep over the type declarations,
 * and why these tests assert the adapter's OUTPUT.
 *
 * They also pin the two fields the server now joins in — `driverPhone` on the trailer and on
 * the appointment — which were declared, rendered in three places, and sent by nothing.
 */

const get = vi.fn()

vi.mock('./client', () => ({
  api: {
    get: (...args: unknown[]) => get(...args),
    post: vi.fn(),
    patch: vi.fn(),
    put: vi.fn(),
    delete: vi.fn(),
  },
}))
vi.mock('./transformRegistry', () => ({ registerTransform: vi.fn() }))

type AnyApi = Record<string, (...args: any[]) => Promise<any>>

async function yard(): Promise<AnyApi> {
  const mod = await loadInRealMode(() => import('./yard'))
  return (mod as unknown as { yardApi: AnyApi }).yardApi
}

/** What `/api/v1/yard/trailers` emits per row, after the casing seam. */
const WIRE_TRAILER = {
  id: 'trl-1',
  trailerId: 'TRL-9001',
  licensePlate: 'GHI-3456',
  carrierId: 'car-1',
  carrierName: 'Swift Transportation',
  trailerType: 'dry_van',
  status: 'checked_in',
  yardLocation: 'ZONE-A-05',
  checkedInAt: '2026-07-30T04:00:00Z',
  detentionRisk: 'low',
  detentionCost: 0,
  sealNumber: 'SEAL-77',
  driverPhone: '+1-555-0142',
  metadata: {},
  createdAt: '2026-07-30T04:00:00Z',
  updatedAt: '2026-07-30T04:00:00Z',
}

const envelope = (items: unknown[]) => ({
  data: { items, meta: { total: items.length, skip: 0, limit: 50, hasMore: false } },
})

beforeEach(() => {
  vi.clearAllMocks()
})

afterEach(() => {
  restoreMockMode()
})

describe('the trailer adapter invents nothing', () => {
  it('passes through exactly what the serializer sent', async () => {
    get.mockResolvedValue(envelope([WIRE_TRAILER]))
    const api = await yard()

    const page = await api.getTrailers()

    expect(page.items).toEqual([WIRE_TRAILER])
  })

  it('does not fish contents or a PO number out of the metadata blob', async () => {
    // THE ASSERTION THIS FILE EXISTS FOR. `yard_trailers` records what the trailer IS and
    // nothing about what is inside it; neither key is ever written into `meta_data` either.
    // The inventory table printed a dash on every row under a column headed "Contents".
    get.mockResolvedValue(
      envelope([{ ...WIRE_TRAILER, metadata: { contents: 'Palletised electronics', po_number: 'PO-99' } }]),
    )
    const api = await yard()

    const [trailer] = (await api.getTrailers()).items

    expect(trailer).not.toHaveProperty('contents')
    expect(trailer).not.toHaveProperty('poNumber')
  })

  it('carries the driver phone the server joins in', async () => {
    // Declared, rendered on the card and in the detail panel, and sent by nothing until the
    // `drivers.phone` join was added.
    get.mockResolvedValue(envelope([WIRE_TRAILER]))
    const api = await yard()

    const [trailer] = (await api.getTrailers()).items

    expect(trailer.driverPhone).toBe('+1-555-0142')
  })

  it('leaves a driver with no number recorded as null', async () => {
    // The control: `drivers.phone` is nullable, and the panel omits the line on null. An
    // empty string would render a blank line under a heading.
    get.mockResolvedValue(envelope([{ ...WIRE_TRAILER, driverPhone: null }]))
    const api = await yard()

    const [trailer] = (await api.getTrailers()).items

    expect(trailer.driverPhone).toBeNull()
  })
})

describe('the detention alerts arrive in the shape the banner reads', () => {
  const WIRE_ALERT = {
    trailerId: 'trl-1',
    trailerNumber: 'TRL-9001',
    status: 'detention',
    licensePlate: 'GHI-3456',
    yardLocation: 'ZONE-A-05',
    carrierName: 'Swift Transportation',
    checkInAt: '2026-07-30T04:00:00Z',
    elapsedMinutes: 360,
    freeMinutes: 120,
    detentionMinutes: 240,
    currentCharge: 450,
    hourlyRate: 112.5,
  }

  it('passes the endpoint payload straight through', async () => {
    // The banner appears only when a trailer is at risk or already accruing charges — only
    // when it matters — and every field it rendered used to be undefined, including the React
    // key. There is no adapter here and there should not be one: the type names the wire.
    get.mockResolvedValue({ data: [WIRE_ALERT] })
    const api = await yard()

    expect(await api.getDetentionAlerts()).toEqual([WIRE_ALERT])
    expect(get).toHaveBeenCalledWith('/api/v1/yard/detention-alerts')
  })
})

describe('the requests go where the backend serves them', () => {
  it('does not send an organization_id when listing trailers', async () => {
    // It was a REQUIRED client-supplied query parameter — the IDOR shape — and being required
    // with no default, every frontend call got a 422. The org comes from the token.
    get.mockResolvedValue(envelope([]))
    const api = await yard()

    await api.getTrailers()

    const [url, config] = get.mock.calls[0] as [string, { params?: Record<string, unknown> }]
    expect(url).toBe('/api/v1/yard/trailers')
    expect(config?.params ?? {}).not.toHaveProperty('organization_id')
  })
})

/**
 * FS-393 — `getDwellTimes` declared a summary the endpoint does not send.
 *
 * `GET /api/v1/yard/dwell-times` is `response_model=List[DwellTimeAnalytics]`: one row per
 * trailer with `dwell_hours`. This function declared, and in real mode returned,
 * `{ avgDwellTime, maxDwellTime, trailersExceedingTarget }` — so `response.data` was an
 * array and `YardManagement` read `dwellTimes.trailersExceedingTarget` on it. `undefined`,
 * so `undefined > 0` is false, so THE DWELL WARNING BANNER NEVER RENDERED against the real
 * API. The mock returned the summary shape, so it rendered in development and only there.
 *
 * Verified against a running backend before the fix: the endpoint returned a list whose
 * first row was TRL-9017 at 23 dwell hours — eleven times past the 120-minute target, on
 * the page whose banner exists to say exactly that.
 *
 * Third instance of this shape today, after StrategicRecommendation (FS-366) and the engine
 * status types (FS-367). The mock agreeing with a declaration neither the server nor
 * anything else can satisfy is the circularity `test_frontend_fields_exist_on_the_wire.py`
 * exists to break, and it does not reach a client's RETURN type.
 */
describe('yardApi.getDwellTimes in real mode', () => {
  const row = (trailerNumber: string, dwellHours: number) => ({
    trailerId: `id-${trailerNumber}`,
    trailerNumber,
    dwellHours,
    isDetention: dwellHours > 2,
    detentionCharge: null,
  })

  it('summarises the LIST the endpoint actually returns', async () => {
    get.mockResolvedValue({ data: [row('A', 1), row('B', 3), row('C', 5)] })
    const api = await yard()
    const result = await api.getDwellTimes()

    expect(get).toHaveBeenCalledWith('/api/v1/yard/dwell-times')
    // 60, 180, 300 minutes -> mean 180, max 300, two past the 120-minute target.
    expect(result).toEqual({
      avgDwellTime: 180,
      maxDwellTime: 300,
      trailersExceedingTarget: 2,
    })
  })

  it('counts against the 120-minute target the page names', async () => {
    // Exactly at target is not exceeding it — the banner says "Target: 120 min", and a
    // trailer sitting at exactly 120 has not passed it.
    get.mockResolvedValue({ data: [row('A', 2), row('B', 2.01)] })
    const api = await yard()
    expect((await api.getDwellTimes()).trailersExceedingTarget).toBe(1)
  })

  it('returns zeroes rather than NaN for an empty yard', async () => {
    // `Math.max()` of nothing is -Infinity and a mean over zero rows is NaN; either would
    // reach `formatDuration` and render as garbage in the banner.
    get.mockResolvedValue({ data: [] })
    const api = await yard()
    expect(await api.getDwellTimes()).toEqual({
      avgDwellTime: 0,
      maxDwellTime: 0,
      trailersExceedingTarget: 0,
    })
  })

  it('survives a payload that is not a list', async () => {
    // Defensive, and cheap: this function spent its life assuming the wrong shape, so it
    // should not throw if it meets an unexpected one again.
    get.mockResolvedValue({ data: { unexpected: true } })
    const api = await yard()
    expect((await api.getDwellTimes()).trailersExceedingTarget).toBe(0)
  })

  it('does not return the raw array', async () => {
    // The defect stated directly: whatever this returns must be the summary its callers
    // read, not the payload.
    get.mockResolvedValue({ data: [row('A', 9)] })
    const api = await yard()
    const result = await api.getDwellTimes()
    expect(Array.isArray(result)).toBe(false)
    expect(result.trailersExceedingTarget).toBe(1)
  })
})

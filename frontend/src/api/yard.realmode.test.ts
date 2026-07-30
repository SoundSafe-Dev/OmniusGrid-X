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

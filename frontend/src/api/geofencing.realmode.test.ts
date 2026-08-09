import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { loadInRealMode, restoreMockMode } from '../test/realMode'
import { circleRenderableZones } from '../components/fleet/GeofencingPanel'

/**
 * REAL-MODE tests for the geofencing client.
 *
 * WHAT THESE EXIST FOR. `adaptZone` and `adaptAlert` coerced absent values into plausible
 * ones, and in three places that defeated null-handling written deliberately on BOTH sides of
 * them — the serializer chose to send `null`, the panel was written to detect it, and the
 * adapter in between replaced it with something that looked like data.
 *
 *   * `geofenceName: … ?? a?.zoneId ?? ''`. `_alert_out` sends `null` when the zone join does
 *     not resolve, under a comment reading *"the panel must be able to tell a zone it could
 *     not resolve from one with an empty name."* The panel does
 *     `geofenceName ?? 'Zone name unavailable'`. **`'' ?? x` is `''`** — nullish coalescing
 *     does not treat the empty string as absent — so the fallback could never fire and the row
 *     rendered a blank line. Before reaching `''` it would print the zone's UUID under a
 *     heading that reads like a name.
 *
 *   * `alertType: … ?? 'violation'` — the ORIGINAL defect as a fallback. "Every geofence alert
 *     read Violation" is what started this thread; the panel now refuses to guess an
 *     unrecognised value, which requires it to see the absence.
 *
 *   * `center: { latitude: … ?? 0, … }` and `radius: … ?? 0`. `center_lat`, `center_lng` and
 *     `radius_meters` are nullable and are genuinely NULL for a POLYGON zone.
 *     `circleRenderableZones` filters on `typeof z.center.latitude === 'number'` precisely to
 *     exclude those — and a coerced `0` passes it. A zero-radius circle at 0°N 0°E, in the
 *     Gulf of Guinea, on the fleet map.
 *
 * The whole frontend suite was green before this file and after the fix: 417 tests, none of
 * which could see any of it. A coercion is invisible to every test that supplies complete data.
 */

const get = vi.fn()

vi.mock('./client', () => ({
  api: {
    get: (...args: unknown[]) => get(...args),
    post: vi.fn(),
    put: vi.fn(),
    delete: vi.fn(),
  },
}))
vi.mock('./transformRegistry', () => ({ registerTransform: vi.fn() }))

type AnyApi = Record<string, (...args: any[]) => Promise<any>>

async function geofencing(): Promise<AnyApi> {
  const mod = await loadInRealMode(() => import('./geofencing'))
  return (mod as unknown as { geofencingApi: AnyApi }).geofencingApi
}

/** A POLYGON zone as `_zone_out` emits it: no centre, no radius — both columns are NULL. */
const WIRE_POLYGON_ZONE = {
  id: 'zone-poly',
  name: 'Restricted Yard',
  zoneType: 'polygon',
  center: { lat: null, lng: null },
  radiusMeters: null,
  polygon: [[1, 2], [3, 4]],
  triggerOn: 'both',
  severity: 'critical',
  isActive: true,
}

const WIRE_CIRCLE_ZONE = {
  id: 'zone-circle',
  name: 'Depot',
  zoneType: 'circle',
  center: { lat: 51.5, lng: -0.12 },
  radiusMeters: 500,
  polygon: null,
  triggerOn: 'entry',
  severity: 'warning',
  isActive: true,
}

/** An alert whose zone and vehicle joins did not resolve — the server sends nulls. */
const WIRE_UNRESOLVED_ALERT = {
  id: 'alert-1',
  geofenceId: 'zone-gone',
  geofenceName: null,
  vehicleId: 'veh-gone',
  vehicleNumber: null,
  alertType: 'entry',
  severity: 'info',
  location: {},
  acknowledged: false,
  timestamp: '2026-07-30T04:00:00Z',
}

beforeEach(() => {
  vi.clearAllMocks()
})

afterEach(() => {
  restoreMockMode()
})

describe('the alert adapter preserves what the server chose to say was missing', () => {
  it('leaves an unresolved zone name absent instead of substituting the id', async () => {
    // THE ASSERTION THIS FILE EXISTS FOR. The panel's `?? 'Zone name unavailable'` is dead
    // code unless this holds — and it was dead, because `''` is not nullish.
    get.mockResolvedValue({ data: [WIRE_UNRESOLVED_ALERT] })
    const api = await geofencing()

    const [alert] = (await api.getAlerts()).items

    expect(alert.geofenceName ?? null).toBeNull()
    expect(alert.geofenceName).not.toBe('')
    expect(alert.geofenceName).not.toBe('zone-gone')
  })

  it('leaves an unresolved vehicle number absent instead of substituting the id', async () => {
    get.mockResolvedValue({ data: [WIRE_UNRESOLVED_ALERT] })
    const api = await geofencing()

    const [alert] = (await api.getAlerts()).items

    expect(alert.vehicleNumber ?? null).toBeNull()
    expect(alert.vehicleNumber).not.toBe('veh-gone')
  })

  it('does not call an alert a violation when the type did not arrive', async () => {
    // "Every geofence alert read Violation" — the defect that started this thread — survived
    // as `?? 'violation'` in the adapter long after the field name was fixed server-side.
    const { alertType, ...withoutType } = WIRE_UNRESOLVED_ALERT
    get.mockResolvedValue({ data: [withoutType] })
    const api = await geofencing()

    const [alert] = (await api.getAlerts()).items

    expect(alert.alertType ?? null).toBeNull()
  })

  it('does not call an alert informational when the severity did not arrive', async () => {
    const { severity, ...withoutSeverity } = WIRE_UNRESOLVED_ALERT
    get.mockResolvedValue({ data: [withoutSeverity] })
    const api = await geofencing()

    const [alert] = (await api.getAlerts()).items

    expect(alert.severity ?? null).toBeNull()
  })

  it('still passes real values through', async () => {
    // The control. An adapter that dropped everything would satisfy all four tests above.
    get.mockResolvedValue({
      data: [{ ...WIRE_UNRESOLVED_ALERT, geofenceName: 'Depot', vehicleNumber: 'TRK-1' }],
    })
    const api = await geofencing()

    const [alert] = (await api.getAlerts()).items

    expect(alert.geofenceName).toBe('Depot')
    expect(alert.vehicleNumber).toBe('TRK-1')
    expect(alert.alertType).toBe('entry')
    expect(alert.severity).toBe('info')
  })

  it('accepts the legacy zoneId/eventType spellings the endpoint used to send', async () => {
    // The rename was made on the producer, and these fallbacks are the compatibility half.
    // They are renames, not defaults — they must survive the removal of the defaults.
    get.mockResolvedValue({
      data: [{ id: 'a', zoneId: 'z-1', eventType: 'exit', acknowledged: false }],
    })
    const api = await geofencing()

    const [alert] = (await api.getAlerts()).items

    expect(alert.geofenceId).toBe('z-1')
    expect(alert.alertType).toBe('exit')
  })
})

describe('the zone adapter does not place a polygon at Null Island', () => {
  it('leaves a polygon zone with no centre and no radius', async () => {
    // `?? 0` on both coordinates put a NULL-centred zone at 0°N 0°E with a radius of zero.
    // `circleRenderableZones` filters on `typeof latitude === 'number'` to exclude exactly
    // this, and a coerced 0 sails through the filter.
    get.mockResolvedValue({ data: [WIRE_POLYGON_ZONE] })
    const api = await geofencing()

    const [zone] = await api.getZones()

    expect(zone.center).toBeUndefined()
    expect(zone.radius ?? null).toBeNull()
    expect(zone.type).toBe('polygon')
  })

  it('keeps a real centre and radius', async () => {
    // The control: refusing to coerce must not mean refusing to map.
    get.mockResolvedValue({ data: [WIRE_CIRCLE_ZONE] })
    const api = await geofencing()

    const [zone] = await api.getZones()

    expect(zone.center).toEqual({ latitude: 51.5, longitude: -0.12, timestamp: '' })
    expect(zone.radius).toBe(500)
  })

  it('does not claim a zone contains zero vehicles', async () => {
    // `vehiclesInside: … ?? []` made the panel print "0 vehicles inside" on every zone. The
    // endpoint does not send it and nothing computes it, so that is a count reported for a
    // figure nobody measured.
    get.mockResolvedValue({ data: [WIRE_CIRCLE_ZONE] })
    const api = await geofencing()

    const [zone] = await api.getZones()

    expect(zone.vehiclesInside).toBeUndefined()
  })

  it('does not invent empty timestamps that render as "Invalid Date"', async () => {
    get.mockResolvedValue({ data: [WIRE_CIRCLE_ZONE] })
    const api = await geofencing()

    const [zone] = await api.getZones()

    expect(zone.createdAt).toBeUndefined()
    expect(zone.updatedAt).toBeUndefined()
  })

  it('still derives the entry/exit flags from triggerOn', async () => {
    // A DERIVATION, not a default: `trigger_on` is sent and 'entry' really does mean
    // onEntry-and-not-onExit. Removing the defaults must not remove this.
    get.mockResolvedValue({ data: [WIRE_CIRCLE_ZONE] })
    const api = await geofencing()

    const [zone] = await api.getZones()

    expect(zone.alertRules).toEqual({ onEntry: true, onExit: false, notifyRoles: [] })
    expect(zone.color).toBe('yellow')
  })
})

describe('what the map is actually handed', () => {
  it('draws nothing for a polygon zone whose centre columns are NULL', async () => {
    // THE END-TO-END LINK, and the assertion that was missing on both sides.
    //
    // `GeofencingPanel.zones.test.ts` covers `circleRenderableZones` thoroughly — including a
    // `center: undefined` case — and passed throughout, because the ADAPTER never produced an
    // undefined centre. It produced `{ latitude: 0, longitude: 0 }`, which is a perfectly
    // numeric pair, so the filter kept the zone and the map drew a zero-radius circle in the
    // Gulf of Guinea.
    //
    // Each layer was tested against inputs the other layer could not send it. This runs the
    // real adapter's output into the real filter.
    get.mockResolvedValue({ data: [WIRE_POLYGON_ZONE, WIRE_CIRCLE_ZONE] })
    const api = await geofencing()

    const zones = await api.getZones()

    expect(circleRenderableZones(zones).map((z) => z.id)).toEqual(['zone-circle'])
  })
})

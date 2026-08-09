import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { loadInRealMode, restoreMockMode } from '../test/realMode'

/**
 * REAL-MODE tests for the fleet health & security client (FS-486).
 *
 * Thirteen `USE_MOCK` forks, and this file's real branch has a documented history of being
 * the one nobody ran: `getHealthStatistics` had no return type at all, so `response.data`
 * was `any`, and `HealthSecurityPanel` assigned an endpoint payload with four keys into a
 * state object that read eight different ones. All four tiles rendered blank in real mode
 * while the mock returned the eight-key shape and development looked complete (FS-398).
 * `PATCH /security/events/{id}` was wired to a button and served by nothing (FS-238).
 *
 * Both are fixed. What has never had a test is the code that shipped them: the paths, the
 * query parameters that decide WHICH events an operator is shown, and the acknowledge body.
 *
 * THE FILTERS ARE THE SHARP PART. `getUnacknowledgedSecurityEvents` and
 * `getCriticalSecurityEvents` differ from `getSecurityEvents` by a query string alone. The
 * backend declares both parameters and filters on them — but a client that dropped or
 * misspelled one gets **200 and the full list**, not an error. A panel headed "unacknowledged
 * security events" would then show acknowledged ones, and the mock branch, which filters the
 * fixture in JavaScript, would look right throughout.
 *
 * THE SHAPE DIVERGENCE IS DELIBERATE, AND ASSERTED AS SUCH. `getHealthStatistics`'s mock
 * returns the panel's eight-key object mapped down to three; the wire returns three. That is
 * on purpose and documented in the client — the endpoint cannot compute a fleet size, because
 * `GeoTabDiagnostic.vehicle_id` has no foreign key to `vehicles`. The real branch must return
 * the wire's three fields and invent nothing.
 */

const get = vi.fn()
const patch = vi.fn()

vi.mock('./client', () => ({
  api: {
    get: (...args: unknown[]) => get(...args),
    patch: (...args: unknown[]) => patch(...args),
    post: vi.fn(),
    put: vi.fn(),
    delete: vi.fn(),
  },
}))

type AnyApi = Record<string, (...args: any[]) => Promise<any>>

async function fleetHealth(): Promise<AnyApi> {
  const mod = await loadInRealMode(() => import('./fleetHealth'))
  return (mod as unknown as { fleetHealthApi: AnyApi }).fleetHealthApi
}

/** What `GET /api/v1/fleet/security/events` emits per row, after the casing seam. */
const SECURITY_EVENT = {
  id: 'sec-1',
  vehicleId: 'veh-1',
  eventType: 'unauthorized_access',
  severity: 'critical',
  acknowledged: false,
  detectedAt: '2026-08-06T09:00:00Z',
}

const VEHICLE_HEALTH = {
  vehicleId: 'veh-1',
  status: 'warning',
  safetyScore: 82,
  lastSeenAt: '2026-08-06T09:00:00Z',
}

beforeEach(() => {
  get.mockReset()
  patch.mockReset()
})

afterEach(() => {
  restoreMockMode()
})

describe('the filtered security lists really are filtered', () => {
  it('asks for unacknowledged events, not all of them', async () => {
    // A dropped parameter returns 200 and the full list. The panel is headed
    // "unacknowledged", so the operator reads acknowledged events as outstanding work —
    // and the mock branch filters the fixture in JavaScript, so it looks right in
    // development either way.
    get.mockResolvedValue({ data: [SECURITY_EVENT] })
    const api = await fleetHealth()

    await api.getUnacknowledgedSecurityEvents()

    expect(get.mock.calls[0][0]).toContain('acknowledged=false')
  })

  it('asks for critical events by severity', async () => {
    get.mockResolvedValue({ data: [SECURITY_EVENT] })
    const api = await fleetHealth()

    await api.getCriticalSecurityEvents()

    expect(get.mock.calls[0][0]).toContain('severity=critical')
  })

  it('asks for everything when nothing was filtered', async () => {
    // The other direction. A client that always sent a filter would pass both tests above
    // while the unfiltered list quietly stopped being unfiltered.
    get.mockResolvedValue({ data: [SECURITY_EVENT] })
    const api = await fleetHealth()

    await api.getSecurityEvents()

    expect(get.mock.calls[0][0]).toBe('/api/v1/fleet/security/events')
  })

  it('returns the rows the server sent, unaltered', async () => {
    get.mockResolvedValue({ data: [SECURITY_EVENT] })
    const api = await fleetHealth()

    expect(await api.getSecurityEvents()).toEqual([SECURITY_EVENT])
  })
})

describe('acknowledging an event says what it means', () => {
  it('patches the event with the acknowledged flag', async () => {
    // This endpoint was called by a button and served by nothing for a while: the 404
    // rejected, the optimistic update never ran, and an operator saw nothing happen.
    patch.mockResolvedValue({ data: SECURITY_EVENT })
    const api = await fleetHealth()

    await api.acknowledgeSecurityEvent('sec-9')

    expect(patch).toHaveBeenCalledWith('/api/v1/fleet/security/events/sec-9', {
      acknowledged: true,
    })
  })

  it('lets a failure reach the caller rather than resolving quietly', async () => {
    // The panel's catch is what puts "Could not acknowledge that security event" on screen.
    // A client that swallowed the rejection would take that away and restore the original
    // defect — a button that does nothing and admits nothing.
    patch.mockRejectedValue(new Error('403'))
    const api = await fleetHealth()

    await expect(api.acknowledgeSecurityEvent('sec-9')).rejects.toThrow()
  })
})

describe('the statistics endpoint is read for what it computes', () => {
  it('returns the three fields the wire carries', async () => {
    get.mockResolvedValue({
      data: { activeDtcs: 7, criticalDtcs: 2, vehiclesWithIssues: 3 },
    })
    const api = await fleetHealth()

    expect(await api.getHealthStatistics()).toEqual({
      activeDtcs: 7,
      criticalDtcs: 2,
      vehiclesWithIssues: 3,
    })
  })

  it('invents no total-vehicles figure', async () => {
    // Deliberately absent (FS-398). The endpoint computes it as the size of the active
    // diagnostics set, so it equals `vehiclesWithIssues` by construction and a healthy
    // fleet would report zero total vehicles. `GeoTabDiagnostic.vehicle_id` has no foreign
    // key to `vehicles`, so the table cannot know the fleet size at all.
    get.mockResolvedValue({ data: { activeDtcs: 0, criticalDtcs: 0, vehiclesWithIssues: 0 } })
    const api = await fleetHealth()

    expect(await api.getHealthStatistics()).not.toHaveProperty('totalVehicles')
  })

  it('asks the statistics endpoint, not the vehicle list', async () => {
    get.mockResolvedValue({ data: { activeDtcs: 0, criticalDtcs: 0, vehiclesWithIssues: 0 } })
    const api = await fleetHealth()

    await api.getHealthStatistics()

    expect(get).toHaveBeenCalledWith('/api/v1/fleet/health/statistics')
  })
})

describe('the three lists the panel actually loads', () => {
  it('reads vehicle health from the fleet health endpoint', async () => {
    get.mockResolvedValue({ data: [VEHICLE_HEALTH] })
    const api = await fleetHealth()

    expect(await api.getAllVehicleHealth()).toEqual([VEHICLE_HEALTH])
    expect(get).toHaveBeenCalledWith('/api/v1/fleet/health')
  })

  it('reads DTCs without filtering them client-side', async () => {
    // The mock branch drops cleared codes with `.filter(d => !d.cleared)`; the real branch
    // must not, because the server decides what is active and a second opinion here would
    // disagree with the count the statistics endpoint returns.
    const cleared = { code: 'P0420', cleared: true, vehicleId: 'veh-1' }
    get.mockResolvedValue({ data: [cleared] })
    const api = await fleetHealth()

    expect(await api.getAllDTCs()).toEqual([cleared])
    expect(get).toHaveBeenCalledWith('/api/v1/fleet/dtcs')
  })

  it('reads driver safety metrics from the safety endpoint', async () => {
    get.mockResolvedValue({ data: [{ driverId: 'drv-1', safetyScore: 91 }] })
    const api = await fleetHealth()

    await api.getDriverSafetyMetrics()

    expect(get).toHaveBeenCalledWith('/api/v1/fleet/safety/drivers')
  })
})

describe('the harness is not testing the mock branch by accident', () => {
  it('reaches the http client at all', async () => {
    // If `loadInRealMode` stopped working, every assertion above would run against the
    // fixture branch and pass while proving nothing about the code that ships.
    get.mockResolvedValue({ data: [] })
    const api = await fleetHealth()

    await api.getSecurityEvents()

    expect(get).toHaveBeenCalled()
  })
})

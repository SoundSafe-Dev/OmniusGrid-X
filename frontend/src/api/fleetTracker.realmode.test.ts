import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { loadInRealMode, restoreMockMode } from '../test/realMode'

/**
 * REAL-MODE tests for the fleet-tracker client (FS-488).
 *
 * FS-487 gave `subscribeToUpdates` an `onError` callback and tested the MAP that consumes it.
 * That is a component test in a different file, and it does not exercise this client at all —
 * which is why `fleetTracker` was still on the real-mode list after being "done". The count
 * was wrong twice before it was derived rather than recalled.
 *
 * WHAT THE MOCK BRANCH DOES INSTEAD OF FETCHING. `getAllVehiclePositions` calls
 * `simulateVehicleMovement`, which advances the fixture's coordinates on every call — so in
 * demo mode the fleet always moves, the poll always succeeds, and neither of the two failures
 * FS-487 was about can occur.
 *
 * The subscription tests below use fake timers, because the failure this client had is
 * defined by what happens on a TICK: the poll rejects, `console.error` is called, and before
 * FS-487 nothing else happened at all. Asserting the callback fires with the error — and
 * fires with `null` on recovery, so a caller's warning can clear — is the whole contract.
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

type AnyApi = Record<string, (...args: any[]) => any>

async function tracker(): Promise<AnyApi> {
  const mod = await loadInRealMode(() => import('./fleetTracker'))
  return (mod as unknown as { fleetTrackerApi: AnyApi }).fleetTrackerApi
}

const POSITION = {
  deviceId: 'dev-1',
  vehicleId: 'veh-1',
  position: { latitude: 41.88, longitude: -87.63 },
  status: 'moving',
  speed: 55,
  heading: 90,
  lastUpdate: '2026-08-06T09:00:00Z',
}

beforeEach(() => {
  get.mockReset()
  get.mockResolvedValue({ data: [POSITION] })
})

afterEach(() => {
  restoreMockMode()
  vi.useRealTimers()
})

describe('the read paths', () => {
  it('reads all positions from the locations endpoint', async () => {
    const api = await tracker()

    expect(await api.getAllVehiclePositions()).toEqual([POSITION])
    expect(get).toHaveBeenCalledWith('/api/v1/fleet/vehicles/locations')
  })

  it('reads one vehicle by device id', async () => {
    get.mockResolvedValue({ data: POSITION })
    const api = await tracker()

    await api.getVehiclePosition('dev-9')

    expect(get).toHaveBeenCalledWith('/api/v1/fleet/vehicles/dev-9/location')
  })

  it('reads active shipment routes and geofences from their own endpoints', async () => {
    get.mockResolvedValue({ data: [] })
    const api = await tracker()

    await api.getActiveShipmentRoutes()
    await api.getGeofenceZones()

    expect(get.mock.calls[0][0]).toBe('/api/v1/fleet/shipments/active-routes')
    expect(get.mock.calls[1][0]).toBe('/api/v1/fleet/geofences')
  })

  it('does not move the vehicles it was given', async () => {
    // The mock branch runs `simulateVehicleMovement`, which advances coordinates on every
    // call. A real path doing anything of the kind would draw a fleet that is not there.
    const api = await tracker()

    const positions = await api.getAllVehiclePositions()

    expect(positions[0].position).toEqual({ latitude: 41.88, longitude: -87.63 })
  })
})

describe('the poll reports its own failure (FS-487)', () => {
  it('calls onError when a tick rejects', async () => {
    // Before FS-487 this reached `console.error` and stopped, so the map kept drawing the
    // last positions it received for as long as the tab stayed open.
    vi.useFakeTimers()
    const api = await tracker()
    const onError = vi.fn()
    get.mockRejectedValue(new Error('network'))

    const stop = api.subscribeToUpdates(vi.fn(), onError)
    await vi.advanceTimersByTimeAsync(30_000)
    stop()

    expect(onError).toHaveBeenCalledWith(expect.any(Error))
  })

  it('calls onError with null when a tick succeeds, so a warning can clear', async () => {
    // Without this a recovered poll leaves a permanent banner, and a banner that survives
    // recovery is one people learn to ignore.
    vi.useFakeTimers()
    const api = await tracker()
    const onError = vi.fn()

    const stop = api.subscribeToUpdates(vi.fn(), onError)
    await vi.advanceTimersByTimeAsync(30_000)
    stop()

    expect(onError).toHaveBeenCalledWith(null)
  })

  it('delivers an update per vehicle on a good tick', async () => {
    vi.useFakeTimers()
    const api = await tracker()
    const onUpdate = vi.fn()

    const stop = api.subscribeToUpdates(onUpdate)
    await vi.advanceTimersByTimeAsync(30_000)
    stop()

    expect(onUpdate).toHaveBeenCalledWith(
      expect.objectContaining({ type: 'vehicle_position', data: POSITION }),
    )
  })

  it('works without an onError, because it is optional', async () => {
    // Every existing caller passed one argument. Making the second required would have been
    // a breaking change dressed as a fix.
    vi.useFakeTimers()
    const api = await tracker()
    get.mockRejectedValue(new Error('network'))

    const stop = api.subscribeToUpdates(vi.fn())
    await expect(vi.advanceTimersByTimeAsync(30_000)).resolves.not.toThrow()
    stop()
  })

  it('stops polling once unsubscribed', async () => {
    vi.useFakeTimers()
    const api = await tracker()

    const stop = api.subscribeToUpdates(vi.fn(), vi.fn())
    await vi.advanceTimersByTimeAsync(30_000)
    const afterFirst = get.mock.calls.length
    stop()
    await vi.advanceTimersByTimeAsync(90_000)

    expect(get.mock.calls.length).toBe(afterFirst)
  })
})

describe('the harness is not testing the mock branch by accident', () => {
  it('reaches the http client at all', async () => {
    const api = await tracker()

    await api.getAllVehiclePositions()

    expect(get).toHaveBeenCalled()
  })
})

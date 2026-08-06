/**
 * The live fleet map — and the two ways it can be wrong while looking right.
 *
 * The map draws pins. Pins have no error state, so both of the failures below render as an
 * ordinary map and neither reaches anyone (FS-487).
 *
 * **A failed initial load draws an empty map.** Empty means "nothing is being tracked",
 * which is a statement about the fleet. The truth was that the request failed, which is a
 * statement about the system, and only one of those is ever a reason to stop looking.
 *
 * **A failed poll leaves the pins where they were.** This is the worse one. There is no
 * WebSocket — `/ws/fleet-tracking` does not exist on the backend, so `subscribeToUpdates`
 * polls every thirty seconds — and the poll's catch used to end at `console.error`. The map
 * then showed the last positions it received for as long as the tab stayed open. **An
 * operator looking at a live map that has stopped updating is looking at where the vehicles
 * were, with every reason to believe it is where they are.** A stationary fleet and a frozen
 * map are the same picture.
 *
 * `subscribeToUpdates` reports failure through an `onError` callback rather than a rejected
 * promise, because a subscription has no promise for a caller to catch and the failure
 * happens thirty seconds after anyone was watching.
 */
import { render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const getAllVehiclePositions = vi.fn()
const getActiveShipmentRoutes = vi.fn()
const getGeofenceZones = vi.fn()
const subscribeToUpdates = vi.fn()

vi.mock('../../api/fleetTracker', () => ({
  fleetTrackerApi: {
    getAllVehiclePositions: (...a: unknown[]) => getAllVehiclePositions(...a),
    getActiveShipmentRoutes: (...a: unknown[]) => getActiveShipmentRoutes(...a),
    getGeofenceZones: (...a: unknown[]) => getGeofenceZones(...a),
    subscribeToUpdates: (...a: unknown[]) => subscribeToUpdates(...a),
  },
}))

/** react-leaflet renders a real map into a real DOM node and jsdom has no layout, so the
 *  tiles are stubbed to plain elements. Nothing here asserts on the map itself — the
 *  subject is what the component says ABOUT the map. */
vi.mock('react-leaflet', () => ({
  MapContainer: ({ children }: { children?: React.ReactNode }) => <div data-testid="map">{children}</div>,
  TileLayer: () => null,
  Marker: ({ children }: { children?: React.ReactNode }) => <div>{children}</div>,
  Popup: ({ children }: { children?: React.ReactNode }) => <div>{children}</div>,
  Circle: () => null,
  Polyline: () => null,
  useMap: () => ({ on: vi.fn(), off: vi.fn(), setView: vi.fn(), fitBounds: vi.fn() }),
  useMapEvents: () => ({}),
}))

const { FleetTrackerMap } = await import('./FleetTrackerMap')

// Shape from `src/types/logistics.ts`, not guessed: the coordinates live under `position`,
// a `GeoLocation`. A flat {latitude, longitude} throws inside the map and renders an empty
// document, which reads as a broken component rather than a made-up fixture.
const vehicle = (over: Record<string, unknown> = {}) => ({
  deviceId: 'dev-1',
  vehicleId: 'veh-1',
  driverName: 'A. Driver',
  position: { latitude: 41.88, longitude: -87.63 },
  status: 'idle',
  speed: 0,
  heading: 90,
  lastUpdate: '2026-08-06T09:00:00Z',
  ...over,
})

/** Hand the component a subscription and keep its error callback, so a poll failure can be
 *  triggered the way the real client triggers it. */
let reportPollError: ((error: unknown) => void) | undefined

beforeEach(() => {
  getAllVehiclePositions.mockReset()
  getActiveShipmentRoutes.mockReset()
  getGeofenceZones.mockReset()
  subscribeToUpdates.mockReset()
  reportPollError = undefined

  getAllVehiclePositions.mockResolvedValue([vehicle()])
  getActiveShipmentRoutes.mockResolvedValue([])
  getGeofenceZones.mockResolvedValue([])
  subscribeToUpdates.mockImplementation((_onUpdate, onError) => {
    reportPollError = onError
    return () => {}
  })
})

describe('an empty map is not an untracked fleet (FS-487)', () => {
  it('says the positions could not be loaded', async () => {
    getAllVehiclePositions.mockRejectedValue(new Error('502'))
    render(<FleetTrackerMap />)

    const alert = await screen.findByRole('alert')
    expect(alert.textContent).toMatch(/could not be loaded/i)
    expect(alert.textContent).toMatch(/not because nothing is being tracked/i)
  })

  it('says nothing when the fleet loaded', async () => {
    render(<FleetTrackerMap />)

    await waitFor(() => expect(getAllVehiclePositions).toHaveBeenCalled())
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('says nothing when the fleet is genuinely empty', async () => {
    // A tracked fleet with no vehicles in it is a fact, not a failure, and claiming
    // otherwise would make the real failure above unreadable.
    getAllVehiclePositions.mockResolvedValue([])
    render(<FleetTrackerMap />)

    await waitFor(() => expect(getAllVehiclePositions).toHaveBeenCalled())
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })
})

describe('a frozen map does not pass for a live one (FS-487)', () => {
  it('says live updates have stopped when the poll fails', async () => {
    // The sharp one. The pins do not move and do not change colour; there is nothing in the
    // map itself from which a stalled poll could be inferred.
    render(<FleetTrackerMap />)
    await waitFor(() => expect(reportPollError).toBeTypeOf('function'))

    reportPollError!(new Error('network'))

    const alert = await screen.findByRole('alert')
    expect(alert.textContent).toMatch(/live updates have stopped/i)
    expect(alert.textContent).toMatch(/may be out of date/i)
  })

  it('clears the warning once a poll succeeds again', async () => {
    // A network blip should not leave a permanent warning on a map that has recovered —
    // and a warning nobody can clear is one people learn to ignore.
    render(<FleetTrackerMap />)
    await waitFor(() => expect(reportPollError).toBeTypeOf('function'))

    reportPollError!(new Error('network'))
    await screen.findByRole('alert')

    reportPollError!(null)
    await waitFor(() => expect(screen.queryByRole('alert')).not.toBeInTheDocument())
  })

  it('says nothing while polling is working', async () => {
    render(<FleetTrackerMap />)
    await waitFor(() => expect(subscribeToUpdates).toHaveBeenCalled())

    expect(screen.queryByText(/live updates have stopped/i)).not.toBeInTheDocument()
  })

  it('does not stack the stall warning on top of the load failure', async () => {
    // Both true at once means the map never loaded AND is not updating. "Could not be
    // loaded" is the one that explains the empty map; adding "positions may be out of date"
    // beside it describes positions that do not exist.
    getAllVehiclePositions.mockRejectedValue(new Error('502'))
    render(<FleetTrackerMap />)
    await waitFor(() => expect(reportPollError).toBeTypeOf('function'))

    reportPollError!(new Error('network'))

    await waitFor(() => expect(screen.getAllByRole('alert')).toHaveLength(1))
    expect(screen.getByRole('alert').textContent).toMatch(/could not be loaded/i)
  })
})

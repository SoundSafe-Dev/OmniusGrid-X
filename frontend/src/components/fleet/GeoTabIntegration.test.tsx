import { render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

vi.mock('../../api', () => ({
  websocketManager: {
    subscribe: vi.fn().mockReturnValue(() => {}),
  },
}))

// Leaflet needs real layout/tiles; stub the react wrapper for jsdom.
vi.mock('react-leaflet', () => ({
  MapContainer: ({ children }: { children?: React.ReactNode }) => (
    <div data-testid="map">{children}</div>
  ),
  TileLayer: () => null,
  Marker: ({ children }: { children?: React.ReactNode }) => <div>{children}</div>,
  Popup: ({ children }: { children?: React.ReactNode }) => <div>{children}</div>,
  Polyline: () => null,
  Circle: () => null,
}))

vi.mock('../../api/fleetTracker', () => ({
  fleetTrackerApi: {
    getAllVehiclePositions: vi.fn().mockResolvedValue([
      {
        deviceId: 'gt-1',
        vehicleId: 'TRUCK-1',
        position: { latitude: 41.88, longitude: -87.63, timestamp: '2026-07-10T12:00:00Z' },
        status: 'moving',
        speed: 65,
        heading: 270,
        lastUpdate: '2026-07-10T12:00:00Z',
      },
    ]),
    getGeofenceZones: vi.fn().mockResolvedValue([
      {
        id: 'gf-1',
        name: 'Chicago Hub',
        type: 'circle',
        center: { latitude: 41.88, longitude: -87.63 },
        radius: 5000,
        color: 'green',
      },
    ]),
  },
}))

import { GeoTabIntegration } from './GeoTabIntegration'

describe('GeoTabIntegration', () => {
  it('renders the tracking header and loads vehicles via the shared api client', async () => {
    const { fleetTrackerApi } = await import('../../api/fleetTracker')
    render(<GeoTabIntegration organizationId="org-1" />)

    expect(screen.getByText('GeoTab Fleet Tracking')).toBeInTheDocument()
    expect(screen.getByTestId('map')).toBeInTheDocument()

    await waitFor(() => expect(fleetTrackerApi.getAllVehiclePositions).toHaveBeenCalled())
    await waitFor(() => expect(screen.getByText('1 Vehicles')).toBeInTheDocument())
    expect(screen.getByText('Vehicles (1)')).toBeInTheDocument()
    expect(fleetTrackerApi.getGeofenceZones).toHaveBeenCalled()
  })
})

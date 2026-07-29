/**
 * The transportation page, and the sharpest instance of "a failure is not a fact".
 *
 * The compliance tab computes HOS violations client-side:
 *
 *     drivers.filter(d => d.hosDriveHoursRemaining === 0).length === 0
 *
 * On a failed drivers query `drivers` is `[]`, so that is true, and the page rendered a
 * GREEN CHECKMARK reading "No HOS violations detected". Hours of Service is
 * DOT-regulated. A compliance officer reads a green tick as clearance, and it was
 * produced by a request that never returned.
 *
 * Unknown is not clear. That distinction is what these tests exist to hold, and it is
 * why the failure state here is deliberately alarming rather than neutral — a grey
 * "could not load" next to a compliance heading still reads as "nothing to worry about".
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const getShipments = vi.fn()
const getCarriers = vi.fn()
const getDrivers = vi.fn()
const getVehicles = vi.fn()
const getDeliveryEfficiency = vi.fn()
const getComplianceSummary = vi.fn()
const getFleetSummary = vi.fn()

vi.mock('../../api', () => ({
  transportationApi: {
    getShipments: (...a: unknown[]) => getShipments(...a),
    getCarriers: (...a: unknown[]) => getCarriers(...a),
    getDrivers: (...a: unknown[]) => getDrivers(...a),
    getVehicles: (...a: unknown[]) => getVehicles(...a),
    getDeliveryEfficiency: (...a: unknown[]) => getDeliveryEfficiency(...a),
    getComplianceSummary: (...a: unknown[]) => getComplianceSummary(...a),
    getShipmentCosts: vi.fn(),
    dispatchShipment: vi.fn(),
    updateShipmentStatus: vi.fn(),
  },
  geoTabApi: { getFleetSummary: (...a: unknown[]) => getFleetSummary(...a) },
}))

import { TooltipProvider } from '../../components/ui'
import { TransportationManagement } from './TransportationManagement'

const page = (over: Record<string, unknown> = {}) => ({
  items: [] as unknown[],
  total: 0,
  skip: 0,
  limit: 50,
  hasMore: false,
  ...over,
})

const driver = (over: Record<string, unknown> = {}) => ({
  id: 'd-1',
  name: 'Dana Driver',
  status: 'available',
  hosDriveHoursRemaining: 8,
  ...over,
})

const wrap = () => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <TooltipProvider>
        <TransportationManagement />
      </TooltipProvider>
    </QueryClientProvider>,
  )
}

const openCompliance = async () => {
  const tab = await screen.findByRole('button', { name: /compliance/i })
  fireEvent.click(tab)
}

beforeEach(() => {
  vi.clearAllMocks()
  getShipments.mockResolvedValue(page())
  getCarriers.mockResolvedValue(page())
  getDrivers.mockResolvedValue(page({ items: [driver()], total: 1 }))
  getVehicles.mockResolvedValue(page())
  // Shapes copied from the client's declared return types, not invented. The page
  // formats several of these with `.toFixed()` unguarded, so a missing field throws
  // during render and returns an empty document — which reads as a component bug rather
  // than a bad fixture. That has now cost time on three separate page tests.
  getDeliveryEfficiency.mockResolvedValue({
    onTimeRate: 95,
    avgTransitTime: 12.5,
    totalDeliveries: 10,
    lateDeliveries: 0,
  })
  getComplianceSummary.mockResolvedValue({
    totalCarriers: 4,
    ctpatCertified: 3,
    activeViolations: 0,
    safetyAlerts: 0,
  })
  getFleetSummary.mockResolvedValue({
    totalVehicles: 3,
    vehiclesMoving: 2,
    vehiclesIdle: 1,
  })
})

describe('TransportationManagement — HOS compliance', () => {
  it('clears the fleet when the drivers really do have hours left', async () => {
    // The positive control. Without it, every assertion below is satisfied by a page
    // that never shows the green tick at all.
    wrap()
    await openCompliance()
    expect(await screen.findByText('No HOS violations detected')).toBeInTheDocument()
  })

  it('does NOT clear the fleet when the drivers could not be loaded', async () => {
    // THE ASSERTION THIS FILE EXISTS FOR. `drivers` is [] on failure, the filter finds
    // nothing, and the page used to conclude compliance from an empty array.
    getDrivers.mockRejectedValue(new Error('driver service unreachable'))
    wrap()
    await openCompliance()
    await waitFor(() =>
      expect(screen.queryByText('No HOS violations detected')).not.toBeInTheDocument(),
    )
    expect(await screen.findByText(/HOS status unknown/i)).toBeInTheDocument()
  })

  it('says plainly that this is not a clean bill of compliance', async () => {
    // A neutral "could not load" beside a compliance heading still reads as reassurance.
    // The wording has to refuse the inference, not merely withhold the tick.
    getDrivers.mockRejectedValue(new Error('driver service unreachable'))
    wrap()
    await openCompliance()
    const notice = await screen.findByRole('alert')
    expect(notice.textContent).toMatch(/not a clean bill of compliance/i)
  })

  it('still reports a real violation as a violation', async () => {
    // The other direction: the failure branch must not swallow genuine findings.
    getDrivers.mockResolvedValue(
      page({ items: [driver({ hosDriveHoursRemaining: 0 })], total: 1 }),
    )
    wrap()
    await openCompliance()
    await waitFor(() =>
      expect(screen.queryByText('No HOS violations detected')).not.toBeInTheDocument(),
    )
    expect(screen.queryByText(/HOS status unknown/i)).not.toBeInTheDocument()
  })
})

describe('TransportationManagement — a failed list is not an empty one', () => {
  it('distinguishes an empty shipment board from an unreadable one', async () => {
    wrap()
    expect(await screen.findByText('No shipments found')).toBeInTheDocument()

    getShipments.mockRejectedValue(new Error('unreachable'))
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(
      <QueryClientProvider client={qc}>
        <TooltipProvider>
          <TransportationManagement />
        </TooltipProvider>
      </QueryClientProvider>,
    )
    await waitFor(() => expect(screen.getAllByRole('alert').length).toBeGreaterThan(0))
  })

  it('sends no tenant identifier on any transportation query', async () => {
    // get_carriers and get_drivers used to take a client-supplied organization_id, and
    // get_carrier fetched by id with no org check at all.
    wrap()
    await waitFor(() => expect(getDrivers).toHaveBeenCalled())
    const everything = JSON.stringify([
      getShipments.mock.calls,
      getCarriers.mock.calls,
      getDrivers.mock.calls,
      getVehicles.mock.calls,
    ])
    expect(everything).not.toContain('organization_id')
    expect(everything).not.toContain('organizationId')
  })
})

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

// The drivers TABLE reads more than the compliance tab does, and three of its cells call
// `.toFixed()`. A fixture missing any of them throws during render and empties the
// document, which reads as a component bug rather than a thin fixture — the same trap
// that has now cost time on five page tests here.
const driver = (over: Record<string, unknown> = {}) => ({
  id: 'd-1',
  name: 'Dana Driver',
  firstName: 'Dana',
  lastName: 'Driver',
  carrierName: 'Acme Freight',
  cdlClass: 'A',
  currentHosStatus: 'off_duty',
  status: 'available',
  hosDriveHoursRemaining: 8,
  hosDutyHoursRemaining: 10,
  hosCycleHoursUsed: 42,
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

// This page issues SEVEN queries before the compliance tab can settle, and the default
// `findBy*` timeout is one second. Under a full parallel run that is not enough — the
// suite failed intermittently on two different assertions here, at ~2.2s, which is a
// defect in the test rather than in the page. Every wait that depends on those queries
// gets a realistic budget.
const SETTLE = { timeout: 10000 }

const openCompliance = async () => {
  // WAIT FOR THE DATA BEFORE SWITCHING TABS. Clicking straight away is a race: the tab
  // renders immediately, but the compliance panel is computed from `drivers`, and if the
  // click lands while that query is still in flight the panel renders once from an empty
  // list and the assertion races the refresh. Padding the timeout did not fix it — one
  // run still failed at 5021ms — because the problem was ordering, not budget.
  await waitFor(() => expect(getDrivers).toHaveBeenCalled(), SETTLE)
  await waitFor(() => expect(getDrivers.mock.results.length).toBeGreaterThan(0), SETTLE)
  const tab = await screen.findByRole('button', { name: /compliance/i }, SETTLE)
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
  // THE SHAPE THE CLIENT NOW RETURNS, which is mapped from what the endpoint actually
  // sends (`total_devices`, `active_devices`, `total_miles_today`, …). The old fixture used
  // `vehiclesMoving`/`vehiclesIdle`/`avgSpeed`, names that appeared in the client's declared
  // return type and in no server response — so the card's six figures were all undefined on
  // the real path while this fixture kept the tests green.
  getFleetSummary.mockResolvedValue({
    totalDevices: 3,
    activeDevices: 2,
    totalDrivers: 4,
    driversOnDuty: 2,
    totalMilesToday: 1250,
    averageFuelEfficiency: 7.4,
    simulated: false,
  })
})

describe('TransportationManagement — HOS compliance', () => {
  it('clears the fleet when the drivers really do have hours left', async () => {
    // The positive control. Without it, every assertion below is satisfied by a page
    // that never shows the green tick at all.
    wrap()
    await openCompliance()
    expect(
      await screen.findByText('No HOS violations detected', undefined, SETTLE),
    ).toBeInTheDocument()
  })

  it('does NOT clear the fleet when the drivers could not be loaded', async () => {
    // THE ASSERTION THIS FILE EXISTS FOR. `drivers` is [] on failure, the filter finds
    // nothing, and the page used to conclude compliance from an empty array.
    getDrivers.mockRejectedValue(new Error('driver service unreachable'))
    wrap()
    await openCompliance()
    expect(
      await screen.findByText(/HOS status unknown/i, undefined, SETTLE),
    ).toBeInTheDocument()
    expect(screen.queryByText('No HOS violations detected')).not.toBeInTheDocument()
  })

  it('says plainly that this is not a clean bill of compliance', async () => {
    // A neutral "could not load" beside a compliance heading still reads as reassurance.
    // The wording has to refuse the inference, not merely withhold the tick.
    getDrivers.mockRejectedValue(new Error('driver service unreachable'))
    wrap()
    await openCompliance()
    const notice = await screen.findByRole('alert', undefined, SETTLE)
    expect(notice.textContent).toMatch(/not a clean bill of compliance/i)
  })

  it('does NOT clear the fleet when a driver has never reported hours', async () => {
    // THE SECOND WAY THIS PAGE WAS WRONG, found by the wire-vocabulary sweep long after
    // the failed-query branch was fixed. `hos_drive_hours_remaining` was added by
    // migration 042 with no default and no backfill, and NOTHING has ever written to it,
    // so it is null for every driver. The violation test is `=== 0`, and `null === 0` is
    // false — every fleet came back clean, on the SUCCESS path, with the data loaded.
    //
    // The API now derives the value from `hos_drive_hours_today` and leaves it null only
    // when that is missing too. Null must read as unassessable, never as compliant.
    getDrivers.mockResolvedValue(
      page({ items: [driver({ hosDriveHoursRemaining: null })], total: 1 }),
    )
    wrap()
    await openCompliance()
    const notice = await screen.findByRole('alert', undefined, SETTLE)
    expect(notice.textContent).toMatch(/no reported hours/i)
    expect(screen.queryByText('No HOS violations detected')).not.toBeInTheDocument()
  })

  it('says missing data is not a violation either', async () => {
    // Trading a false clearance for a false accusation is not a fix. An operator chasing
    // a phantom breach stops trusting the number in both directions — the same rule the
    // server-side carrier roll-up already follows.
    getDrivers.mockResolvedValue(
      page({ items: [driver({ hosDriveHoursRemaining: null })], total: 1 }),
    )
    wrap()
    await openCompliance()
    const notice = await screen.findByRole('alert', undefined, SETTLE)
    expect(notice.textContent).toMatch(/not a clean record — and not a violation either/i)
    expect(screen.queryByText(/Drive Limit Exceeded/i)).not.toBeInTheDocument()
  })

  it('shows a driver with no reported hours as not reported, not as nearly out', async () => {
    // `null < 2` is `0 < 2`, so the table painted an unreported driver amber — the colour
    // reserved for a driver running short of hours.
    getDrivers.mockResolvedValue(
      page({ items: [driver({ hosDriveHoursRemaining: null })], total: 1 }),
    )
    wrap()
    await waitFor(() => expect(getDrivers).toHaveBeenCalled(), SETTLE)
    const tab = await screen.findByRole('button', { name: /drivers/i }, SETTLE)
    fireEvent.click(tab)
    expect(await screen.findByText('not reported', undefined, SETTLE)).toBeInTheDocument()
  })

  it('still reports a real violation as a violation', async () => {
    // The other direction: the failure branch must not swallow genuine findings.
    getDrivers.mockResolvedValue(
      page({ items: [driver({ hosDriveHoursRemaining: 0 })], total: 1 }),
    )
    wrap()
    await openCompliance()
    await waitFor(
      () => expect(screen.queryByText('No HOS violations detected')).not.toBeInTheDocument(),
      SETTLE,
    )
    expect(screen.queryByText(/HOS status unknown/i)).not.toBeInTheDocument()
  })
})

describe('TransportationManagement — device identifiers', () => {
  // TWO DIFFERENT DEFECTS BEHIND ONE FIELD NAME. Both detail panels showed a
  // "GeoTab Device ID" row reading `x.geoTabDeviceId`:
  //
  //   * Vehicles DO have one — `vehicles.geotab_device_id` — but the casing seam produces
  //     `geotabDeviceId` with a lower-case t, so the declared name matched nothing.
  //   * Drivers do NOT. The column is `eld_device_id`: an ELD, a different system with
  //     different compliance meaning. The row could never populate, while the id the driver
  //     actually has was being sent and never displayed.
  //
  // Both rows are conditional, so neither made a false claim — they were simply never
  // there, which is why nothing ever reported them.
  // The device rows live in a DETAIL panel, which opens on selecting a row — reaching the
  // tab is not enough, and a test that stopped there passed for the wrong reason (the row
  // it was looking for had not been rendered yet, not because the id was correct).
  const openDetail = async (tab: RegExp, rowText: string | RegExp) => {
    await waitFor(() => expect(getDrivers).toHaveBeenCalled(), SETTLE)
    fireEvent.click(await screen.findByRole('button', { name: tab }, SETTLE))
    fireEvent.click(await screen.findByText(rowText, undefined, SETTLE))
  }

  it("shows a vehicle's GeoTab device id", async () => {
    getVehicles.mockResolvedValue(
      page({ items: [{ id: 'v-1', vehicleNumber: 'TRK-1', status: 'available',
                       geotabDeviceId: 'gt-device-77' }], total: 1 }),
    )
    wrap()
    // One tab holds both lists: "Fleet & Drivers". `/vehicles/i` matched no tab at all,
    // and the test then timed out looking for the row rather than for the tab.
    await openDetail(/fleet/i, 'TRK-1')
    expect(await screen.findByText('gt-device-77', undefined, SETTLE)).toBeInTheDocument()
  })

  it("shows a driver's ELD device id, labelled as an ELD", async () => {
    getDrivers.mockResolvedValue(
      page({ items: [driver({ eldDeviceId: 'eld-device-42' })], total: 1 }),
    )
    wrap()
    await openDetail(/fleet/i, 'Dana Driver')
    expect(await screen.findByText('eld-device-42', undefined, SETTLE)).toBeInTheDocument()
    expect(screen.getByText('ELD Device ID')).toBeInTheDocument()
    // The panel must not call an ELD a GeoTab device: they are different systems, and on a
    // driver record the distinction is a compliance one.
    expect(screen.queryByText('GeoTab Device ID')).not.toBeInTheDocument()
  })

  it('shows no device row when the driver has no ELD id', async () => {
    // The control: a row that always renders would satisfy the test above and print an
    // empty identifier for every driver.
    getDrivers.mockResolvedValue(page({ items: [driver()], total: 1 }))
    wrap()
    await openDetail(/fleet/i, 'Dana Driver')
    expect(screen.queryByText('ELD Device ID')).not.toBeInTheDocument()
  })
})

describe('TransportationManagement — the fleet card', () => {
  it('shows the figures the endpoint actually reports', async () => {
    // The positive control. Six tiles used to render blank because the client declared
    // names — totalVehicles, vehiclesMoving, avgSpeed, fuelConsumedToday — that no server
    // response has ever carried.
    wrap()
    expect(await screen.findByText('Devices', undefined, SETTLE)).toBeInTheDocument()
    expect(screen.getByText('3')).toBeInTheDocument()
    expect(screen.getByText('1250 mi')).toBeInTheDocument()
  })

  it('renders a dash rather than a bare unit for a figure it does not have', async () => {
    // It printed "{undefined} mi" — a label, a space and a unit — which reads as a
    // measurement rather than an absent one.
    getFleetSummary.mockResolvedValue({ totalDevices: 3, simulated: false })
    wrap()
    await screen.findByText('Devices', undefined, SETTLE)
    expect(screen.queryByText(/^\s*mi$/)).not.toBeInTheDocument()
    expect(screen.getAllByText('—').length).toBeGreaterThan(0)
  })

  it('does not call simulated telematics live', async () => {
    // THE ASSERTION THIS BLOCK EXISTS FOR. Every GeoTab payload carries `simulated: true`
    // and a warning that the figures are not valid for DOT/ELD compliance — stamped
    // server-side so a consumer could tell — and the heading said "GeoTab Live".
    getFleetSummary.mockResolvedValue({
      totalDevices: 3,
      simulated: true,
      dataSourceWarning: 'Simulated telematics. Not measured from a device and not valid for DOT/ELD compliance reporting.',
    })
    wrap()
    expect(await screen.findByText(/Fleet Status \(simulated\)/, undefined, SETTLE)).toBeInTheDocument()
    expect(screen.queryByText(/GeoTab Live/)).not.toBeInTheDocument()
    expect(screen.getByText(/not valid for DOT\/ELD compliance/i)).toBeInTheDocument()
  })

  it('still says Live when the data is not simulated', async () => {
    // The control that keeps the warning meaningful: labelling everything "simulated"
    // would satisfy the test above and make the distinction worthless.
    getFleetSummary.mockResolvedValue({ totalDevices: 3, simulated: false })
    wrap()
    expect(await screen.findByText(/GeoTab Live/, undefined, SETTLE)).toBeInTheDocument()
    expect(screen.queryByText(/not valid for DOT/i)).not.toBeInTheDocument()
  })
})

describe('TransportationManagement — a failed list is not an empty one', () => {
  it('distinguishes an empty shipment board from an unreadable one', async () => {
    wrap()
    expect(await screen.findByText('No shipments found', undefined, SETTLE)).toBeInTheDocument()

    getShipments.mockRejectedValue(new Error('unreachable'))
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(
      <QueryClientProvider client={qc}>
        <TooltipProvider>
          <TransportationManagement />
        </TooltipProvider>
      </QueryClientProvider>,
    )
    await waitFor(() => expect(screen.getAllByRole('alert').length).toBeGreaterThan(0), SETTLE)
  })

  it('sends no tenant identifier on any transportation query', async () => {
    // get_carriers and get_drivers used to take a client-supplied organization_id, and
    // get_carrier fetched by id with no org check at all.
    wrap()
    await waitFor(() => expect(getDrivers).toHaveBeenCalled(), SETTLE)
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

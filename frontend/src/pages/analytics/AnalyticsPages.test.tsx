/**
 * The three analytics pages, and the chart that must not draw a bar at zero.
 *
 * `/dashboard/fleet/oee` used to return `0` for a fleet with no assets — an average of
 * nothing — and this page rendered it through `asPct(v) = Math.round((v ?? 0) * …)`,
 * producing a 0% availability bar: a fleet-wide outage drawn from an empty fleet. The API
 * now returns `null`, and the coercion here would have turned it straight back into zero,
 * so both halves had to change. That is the property the OEE block below holds.
 *
 * `AssetHealth` and `PredictiveMaintenance` are covered for the distinction this codebase
 * keeps getting wrong in both directions: an empty result and a failed request must not
 * render the same way.
 */
import { render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const listAssets = vi.fn()
const getFleetOEE = vi.fn()
const getHistoryPage = vi.fn()
const getUpcomingMaintenance = vi.fn()

vi.mock('../../api', () => ({
  assetsApi: { list: (...a: unknown[]) => listAssets(...a) },
  dashboardApi: { getFleetOEE: (...a: unknown[]) => getFleetOEE(...a) },
  telemetryApi: { getHistoryPage: (...a: unknown[]) => getHistoryPage(...a) },
  maintenanceApi: {
    getUpcomingMaintenance: (...a: unknown[]) => getUpcomingMaintenance(...a),
  },
}))
vi.mock('../../components/charts', () => ({
  AnnotatedChart: () => null,
  FacilityHeatmap: () => null,
}))

// Recharts draws nothing in jsdom — it measures its container and a zero-size container
// yields an empty SVG. Asserting on rendered chart output therefore passes whatever the
// data is, in BOTH directions, which is exactly the vacuity trap this repo keeps hitting.
// These stubs expose the `data` prop as text so the assertions are about what the page
// decided to plot, which is the actual property.
vi.mock('recharts', () => {
  const Chart = ({ data, children }: any) => (
    <div data-testid="chart" data-series={JSON.stringify(data ?? [])}>
      {children}
    </div>
  )
  const Noop = () => null
  return {
    LineChart: Chart,
    BarChart: Chart,
    AreaChart: Chart,
    PieChart: Chart,
    ResponsiveContainer: ({ children }: any) => <div>{children}</div>,
    Line: Noop,
    Bar: Noop,
    Area: Noop,
    Pie: Noop,
    Cell: Noop,
    XAxis: Noop,
    YAxis: Noop,
    CartesianGrid: Noop,
    Tooltip: Noop,
    Legend: Noop,
  }
})

import { TooltipProvider } from '../../components/ui'
import { AssetHealth, PredictiveMaintenance, TelemetryCharts } from './AnalyticsPages'

// `AssetHealth` only names an asset in its At-Risk card, and "at risk" is decided by
// PackML state, not by a health score: AT_RISK_STATES is Held/Holding/Suspended/
// Aborted/Aborting/Stopped/Stopping. A fixture in `Execute` renders no name at all,
// which reads as a broken page rather than a healthy one.
const asset = (over: Record<string, unknown> = {}) => ({
  id: 'a-1',
  name: 'CNC Mill #1',
  assetType: 'machine',
  isActive: true,
  currentPackmlState: 'Held',
  healthScore: 0.4,
  ...over,
})

const assetsPage = (items: unknown[] = [asset()]) => ({
  items,
  total: items.length,
  skip: 0,
  limit: 500,
  hasMore: false,
})

const wrap = (ui: React.ReactElement) => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <TooltipProvider>{ui}</TooltipProvider>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  listAssets.mockResolvedValue(assetsPage())
  getFleetOEE.mockResolvedValue({
    timeRange: 'Last 24 hours',
    assetCount: 1,
    fleetAverageAvailability: 0.9,
    assetsMeasured: 1,
    availabilityOnly: true,
    assets: [],
  })
  // The {items, meta} envelope since FS-486 — the page reads meta.hasMore to say when the
  // chart is a slice of the window it is labelled with.
  getHistoryPage.mockResolvedValue({ items: [], meta: { hasMore: false, count: 0 } })
  getUpcomingMaintenance.mockResolvedValue([])
})

describe('AssetHealth', () => {
  it('lists an asset the API returned', async () => {
    wrap(<AssetHealth />)
    expect(await screen.findByText('CNC Mill #1')).toBeInTheDocument()
  })

  it('asks for a bounded page rather than the whole estate', async () => {
    wrap(<AssetHealth />)
    await screen.findByText('CNC Mill #1')
    expect(listAssets).toHaveBeenCalledWith(expect.objectContaining({ limit: 500 }))
  })

  it('sends no tenant identifier', async () => {
    // `AssetListParams` used to declare an `organizationId` the endpoint never accepted,
    // so it was dropped in silence while reading as a tenant filter at the call site.
    wrap(<AssetHealth />)
    await screen.findByText('CNC Mill #1')
    expect(JSON.stringify(listAssets.mock.calls)).not.toContain('rganization')
  })

  it('does not render a failed load as an empty estate', async () => {
    listAssets.mockRejectedValue(new Error('unreachable'))
    const { container } = wrap(<AssetHealth />)
    await waitFor(() => expect(container.textContent).toMatch(/failed|error|couldn/i))
    expect(screen.queryByText('CNC Mill #1')).not.toBeInTheDocument()
  })
})

describe('PredictiveMaintenance (analytics)', () => {
  it('says the schedule is clear when it genuinely is', async () => {
    wrap(<PredictiveMaintenance />)
    expect(
      await screen.findByText('No maintenance scheduled in the next 30 days.'),
    ).toBeInTheDocument()
  })

  it('does not render a failed load as a clear schedule', async () => {
    // "Nothing scheduled" is something a planner acts on. A failed request that looked
    // identical would tell them the next 30 days are free when nobody knows. The page
    // has both branches; these assert they say different things.
    getUpcomingMaintenance.mockRejectedValue(new Error('unreachable'))
    wrap(<PredictiveMaintenance />)
    expect(
      await screen.findByText(/Failed to load maintenance schedule/i),
    ).toBeInTheDocument()
    expect(
      screen.queryByText('No maintenance scheduled in the next 30 days.'),
    ).not.toBeInTheDocument()
  })
})

describe('TelemetryCharts — an unmeasured fleet draws no bar', () => {
  const seriesOf = () =>
    screen
      .queryAllByTestId('chart')
      .map((el) => JSON.parse(el.getAttribute('data-series') ?? '[]'))
      .filter((rows) => rows.some((r: any) => 'availability' in r))

  it('plots the fleet average when there is one', async () => {
    // The positive control. Without it, "no bar is drawn" is satisfied by a chart that
    // never draws anything — which is precisely what Recharts does under jsdom.
    wrap(<TelemetryCharts />)
    await waitFor(() => expect(seriesOf()).toHaveLength(1))
    expect(seriesOf()[0]).toEqual([{ time: 'Current', availability: 90 }])
  })

  it('renders without a fleet average rather than plotting zero', async () => {
    // THE ASSERTION THIS FILE EXISTS FOR. `asPct(null)` would round to 0 and draw a bar
    // at 0% availability — a fleet-wide outage inferred from an empty fleet, and the
    // exact defect the API had just been fixed for.
    getFleetOEE.mockResolvedValue({
      timeRange: 'Last 24 hours',
      assetCount: 0,
      fleetAverageAvailability: null,
      assetsMeasured: 0,
      availabilityOnly: true,
      assets: [],
    })
    wrap(<TelemetryCharts />)
    // WAIT FOR THE PAGE TO SETTLE FIRST. Asserting straight after the query is CALLED
    // passed against the old code too: the component was still in its loading branch, no
    // chart existed, and "no availability series" was true because nothing had rendered
    // at all. Rule 21 — a negative assertion is satisfied by every reason the thing is
    // absent, including the page not being there yet.
    await waitFor(() => expect(screen.queryAllByTestId('chart').length).toBeGreaterThan(0), {
      timeout: 5000,
    })
    // The chart is rendered and its series carries no availability row — as opposed to
    // carrying one that reads zero.
    expect(seriesOf()).toEqual([])
  })
})

describe('a chart of part of the range says so (FS-486)', () => {
  it('warns when the server capped the readings', async () => {
    // The server caps at 1000 points; a 30-day range at minute resolution is ten times
    // that. A trend read off one end of a window is a wrong trend, not a partial one.
    getHistoryPage.mockResolvedValue({
      items: [
        { timestamp: '2026-08-06T09:00:00Z', metricName: 'temperature', value: 41 },
        { timestamp: '2026-08-06T09:01:00Z', metricName: 'temperature', value: 42 },
      ],
      meta: { hasMore: true, count: 2 },
    })
    wrap(<TelemetryCharts />)

    const note = await screen.findByRole('status')
    expect(note.textContent).toMatch(/more exist/i)
    expect(note.textContent).toMatch(/not all of it/i)
  })

  it('says nothing when the whole range came back', async () => {
    // The other direction. A permanent caveat would make the capped case indistinguishable
    // from the complete one.
    getHistoryPage.mockResolvedValue({
      items: [{ timestamp: '2026-08-06T09:00:00Z', metricName: 'temperature', value: 41 }],
      meta: { hasMore: false, count: 1 },
    })
    wrap(<TelemetryCharts />)

    await waitFor(() => expect(getHistoryPage).toHaveBeenCalled())
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
  })
})

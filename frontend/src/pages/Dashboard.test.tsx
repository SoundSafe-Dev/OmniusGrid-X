// FS-766. Spread the real module rather than listing exports. A hand-written barrel mock is
// a second implementation of `components/ui`, and it drifts the moment the page imports a
// primitive the list does not name — three suites failed with "No ErrorState export is
// defined on the mock", which reads as a mock defect and is actually a real change arriving.
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { axe } from 'jest-axe'
import { describe, expect, it, vi, beforeEach } from 'vitest'

// The landing page had NO test despite being the first thing every user sees —
// and it shipped rendering all-zeros for months because nothing asserted it
// showed real data (that was a backend tenancy bug, FS-191). These lock in the
// things that were actually broken: that each widget degrades on its own rather
// than blanking the page, and that the time range really drives the queries.

const getOverview = vi.fn()
const getActive = vi.fn()
const getAvailabilityTrend = vi.fn()
const getThroughput = vi.fn()
const getAlarmTrend = vi.fn()
const getHealthDistribution = vi.fn()
const getAssetsAtRisk = vi.fn()

const useQuerySpy = vi.fn()
vi.mock('@tanstack/react-query', async (orig) => {
  const actual = await orig<any>()
  return {
    ...actual,
    // Records the OPTIONS each query was created with, then delegates. Asserting on
    // options is the honest level here: waiting on a real interval would test
    // react-query's scheduler, not this page's configuration.
    useQuery: (options: any) => {
      useQuerySpy(options)
      return actual.useQuery(options)
    },
  }
})

const getDashboardSummary = vi.fn()
const acknowledgeMock = { mutate: vi.fn(), isPending: false }
vi.mock('../api', () => ({
  dashboardApi: { getOverview: () => getOverview() },
  alarmsApi: { getActive: () => getActive() },
  oeeApi: { getDashboardSummary: (...a: unknown[]) => getDashboardSummary(...a) },
}))
vi.mock('../hooks', () => ({ useAcknowledgeAlarm: () => acknowledgeMock }))

vi.mock('../api/dashboardAnalytics', () => ({
  dashboardAnalyticsApi: {
    getAvailabilityTrend: (h: number, b: string) => getAvailabilityTrend(h, b),
    getThroughput: (h: number, b: string) => getThroughput(h, b),
    getAlarmTrend: (h: number, b: string) => getAlarmTrend(h, b),
    getHealthDistribution: (h: number) => getHealthDistribution(h),
    getAssetsAtRisk: (h: number, l: number) => getAssetsAtRisk(h, l),
  },
}))

vi.mock('../components/ui', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../components/ui')>()),
  Tooltip: ({ children }: any) => <>{children}</>,
  TooltipTrigger: ({ children }: any) => children,
  TooltipContent: () => null,
}))

// Recharts' ResponsiveContainer measures its parent, which is 0x0 in jsdom, so
// nothing inside it would ever render. Give it a fixed box so the charts mount.
vi.mock('recharts', async () => {
  const actual = await vi.importActual<any>('recharts')
  return {
    ...actual,
    ResponsiveContainer: ({ children }: any) => (
      <div style={{ width: 600, height: 200 }}>{children}</div>
    ),
  }
})

import Dashboard from './Dashboard'

const OVERVIEW = {
  totalAssets: 24,
  activeAssets: 18,
  assetsByState: { Execute: 9, Idle: 6 },
  activeAlarms: 3,
  criticalAlarms: 1,
}

const AVAILABILITY = {
  bucket: '1hour',
  hours: 24,
  availabilityOnly: true,
  assetCount: 8,
  series: [
    { timestamp: '2026-07-24T10:00:00Z', availabilityPct: 80 },
    { timestamp: '2026-07-24T11:00:00Z', availabilityPct: 85 },
  ],
  averageAvailabilityPct: 82.5,
}

const THROUGHPUT = {
  bucket: '1hour',
  hours: 24,
  series: [
    { timestamp: '2026-07-24T10:00:00Z', totalParts: 100, goodParts: 94 },
    { timestamp: '2026-07-24T11:00:00Z', totalParts: 120, goodParts: 112 },
  ],
  totals: { totalParts: 220, goodParts: 206, qualityPct: 93.6 },
}

const ALARM_TREND = {
  bucket: '1hour',
  hours: 24,
  severities: ['critical', 'low'],
  series: [
    { timestamp: '2026-07-24T10:00:00Z', critical: 1, low: 2, total: 3 },
    { timestamp: '2026-07-24T11:00:00Z', critical: 0, low: 1, total: 1 },
  ],
}

const HEALTH = {
  hours: 24,
  assetCount: 8,
  bands: [
    { band: 'critical', min: 0, max: 40, count: 1 },
    { band: 'healthy', min: 80, max: 100.01, count: 7 },
  ],
  averageHealth: 67.4,
}

const AT_RISK = {
  hours: 24,
  assetCount: 1,
  items: [
    {
      assetId: 'a-1',
      assetName: 'CNC Mill #1',
      healthScore: 38.5,
      confidence: 0.2,
      availabilityPct: 62.1,
      alarmRatePerHour: 1.4,
      drivers: [],
    },
  ],
}

const ALARMS = {
  count: 1,
  alarms: [
    {
      id: 'al-1',
      severity: 'high',
      message: 'Nozzle temperature exceeds safe threshold',
      assetName: 'Printer #3',
      occurredAt: '2026-07-24T11:30:00Z',
    },
  ],
}

function happyPath() {
  getOverview.mockResolvedValue(OVERVIEW)
  getDashboardSummary.mockResolvedValue({
    organizationId: 'org-1',
    timestamp: '2026-08-14T10:00:00Z',
    aggregate: {
      avgOee: 68.4,
      avgAvailability: 88,
      avgPerformance: 91,
      avgQuality: 85,
      assetCount: 10,
      assetsMeasured: 8,
      assetsUnavailable: 2,
    },
  })
  getActive.mockResolvedValue(ALARMS)
  getAvailabilityTrend.mockResolvedValue(AVAILABILITY)
  getThroughput.mockResolvedValue(THROUGHPUT)
  getAlarmTrend.mockResolvedValue(ALARM_TREND)
  getHealthDistribution.mockResolvedValue(HEALTH)
  getAssetsAtRisk.mockResolvedValue(AT_RISK)
}

function renderDashboard() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <Dashboard />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('Dashboard', () => {
  beforeEach(() => {
    const mocks = [
      getOverview, getActive, getAvailabilityTrend, getThroughput,
      getAlarmTrend, getHealthDistribution, getAssetsAtRisk,
    ]
    mocks.forEach((m) => m.mockReset())
  })

  it('renders the headline numbers once loaded', async () => {
    happyPath()
    renderDashboard()

    // The regression this page shipped with: every tile rendered 0.
    expect(await screen.findByText('24')).toBeInTheDocument()
    expect(screen.getByText('18')).toBeInTheDocument()
    await waitFor(() => expect(screen.getByText('82.5%')).toBeInTheDocument())
    expect(screen.getByText('220')).toBeInTheDocument()
  })

  it('shows a loading state before data arrives', () => {
    happyPath()
    renderDashboard()
    expect(screen.getAllByRole('status').length).toBeGreaterThan(0)
  })

  it('stops counting alarms in the heading when the count did not arrive', async () => {
    // The body handled the error and the TITLE did not: `Active alarms (${count ?? 0})`
    // rendered "Active alarms (0)" beside a panel reading "Couldn't load this data". Two
    // contradictory statements, and the more specific one was false.
    //
    // The heading is also this section's aria-label, so a screen-reader user navigating
    // by landmark hears "Active alarms 0" and need never reach the body that disagrees.
    // Rule 24 — handling isError and acting on it are different jobs.
    happyPath()
    getActive.mockRejectedValue(new Error('boom'))
    renderDashboard()

    const alarms = await screen.findByRole('region', { name: 'Active alarms' })
    await waitFor(() =>
      expect(within(alarms).getByRole('alert')).toHaveTextContent(/couldn’t load/i),
    )
    // Named exactly: `{ name: /active alarms/i }` would match "Active alarms (0)" too and
    // the query above would pass against the defect.
    expect(screen.queryByRole('region', { name: /active alarms \(/ })).toBeNull()
  })

  it('shows the alarm count in the heading when there is one', async () => {
    // The positive control. Without it, "no count in the heading" is satisfied by a page
    // that never puts one there.
    happyPath()
    renderDashboard()
    expect(
      await screen.findByRole('region', { name: 'Active alarms (1)' }),
    ).toBeInTheDocument()
  })

  it('degrades ONE widget on failure, leaving the rest of the page usable', async () => {
    happyPath()
    getThroughput.mockRejectedValue(new Error('boom'))
    renderDashboard()

    const throughput = await screen.findByRole('region', { name: /throughput/i })
    await waitFor(() =>
      expect(within(throughput).getByRole('alert')).toHaveTextContent(/couldn’t load/i),
    )

    // Neighbours still rendered — a dead widget must not blank the page.
    expect(await screen.findByText('24')).toBeInTheDocument()
    const availability = screen.getByRole('region', { name: /fleet availability/i })
    expect(within(availability).queryByRole('alert')).not.toBeInTheDocument()
  })

  it('shows an explicit empty state rather than an empty plot', async () => {
    happyPath()
    getAlarmTrend.mockResolvedValue({ ...ALARM_TREND, series: [] })
    renderDashboard()

    const alarms = await screen.findByRole('region', { name: /alarms over time/i })
    await waitFor(() =>
      expect(within(alarms).getByText(/no alarms in this window/i)).toBeInTheDocument(),
    )
  })

  it('labels availability honestly — never as OEE', async () => {
    happyPath()
    renderDashboard()
    const availability = await screen.findByRole('region', { name: /fleet availability/i })
    expect(within(availability).getByText(/not full OEE/i)).toBeInTheDocument()
  })

  it('the time range actually drives the queries', async () => {
    happyPath()
    renderDashboard()
    await screen.findByText('24')

    expect(getAvailabilityTrend).toHaveBeenCalledWith(24, '1hour')

    await userEvent.click(screen.getByRole('button', { name: '30d' }))

    // Bucket must widen with the range — 720 hourly points would be neither
    // readable nor cheap.
    await waitFor(() =>
      expect(getAvailabilityTrend).toHaveBeenCalledWith(720, '1day'),
    )
    expect(screen.getByText(/last 30d/i)).toBeInTheDocument()
  })

  it('has no axe violations', async () => {
    happyPath()
    const { container } = renderDashboard()
    await screen.findByText('24')
    expect(await axe(container)).toHaveNoViolations()
  })
})

/**
 * The trend charts poll (P14, page-enhancement review).
 *
 * The two KPI queries had `refetchInterval: 30000` and the five trend queries had none,
 * so on a wall display the tiles refreshed all day over charts frozen at mount — live
 * counts above hours-old trends, with nothing on the page to say the halves disagreed.
 *
 * Asserted at the query options rather than by waiting on a timer: a test that advanced
 * fake timers 60 seconds would be testing react-query's scheduler, and would pass just
 * as well against an interval of one second — which would be a different defect.
 */
describe('the trend charts do not freeze at mount', () => {
  beforeEach(() => {
    useQuerySpy.mockClear()
    happyPath()
    renderDashboard()
  })

  it('polls every trend query', () => {
    const intervals = useQuerySpy.mock.calls
      .map((call) => call[0])
      .filter((options: any) =>
        ['dash-availability', 'dash-throughput', 'dash-alarm-trend', 'dash-health', 'dash-at-risk']
          .includes(options?.queryKey?.[0]),
      )
    expect(intervals.length).toBe(5)
    for (const options of intervals) {
      expect(options.refetchInterval).toBeGreaterThan(0)
    }
  })

  it('polls the trends more slowly than the live counts', () => {
    // A trend bucket does not move in 30 seconds and each of these is an aggregate
    // query; matching the KPI cadence would be five extra aggregations a minute for a
    // chart that cannot have changed.
    const byKey = (key: string) =>
      useQuerySpy.mock.calls.map((c) => c[0]).find((o: any) => o?.queryKey?.[0] === key)
    expect(byKey('dash-availability').refetchInterval).toBeGreaterThan(
      byKey('active-alarms').refetchInterval,
    )
  })
})

/**
 * A real fleet OEE tile, and acknowledging without leaving the page.
 *
 * The survey suggested feeding an OEE tile from `dashboardApi.getFleetOEE(hours)`. That
 * would have been the FS-399 overstatement a third time: that endpoint reports
 * availability only and sets `availabilityOnly: true` to say so, which is exactly why the
 * tile beside this one is carefully named "Availability" (FS-192). The figure comes from
 * `/oee/dashboard/summary`, which multiplies the three factors — and returns null rather
 * than zero when nothing was measured, because a fleet-wide 0% OEE is an emergency.
 */
describe('the fleet OEE tile', () => {
  beforeEach(() => {
    happyPath()
  })

  it('shows the three-factor average', async () => {
    renderDashboard()
    expect(await screen.findByText('Fleet OEE')).toBeInTheDocument()
    expect(await screen.findByText('68.4%')).toBeInTheDocument()
  })

  it('shows a dash, never a zero, when nothing was measured', async () => {
    // The average of an empty set is not zero. A 0% here reads as a stopped factory.
    getDashboardSummary.mockResolvedValue({
      organizationId: 'org-1',
      timestamp: '2026-08-14T10:00:00Z',
      aggregate: {
        avgOee: null, avgAvailability: null, avgPerformance: null, avgQuality: null,
        assetCount: 3, assetsMeasured: 0, assetsUnavailable: 3,
      },
    })
    renderDashboard()
    await screen.findByText('Fleet OEE')
    expect(screen.queryByText('0%')).not.toBeInTheDocument()
  })

  it('shows a dash when the request failed, rather than the last good number', async () => {
    getDashboardSummary.mockRejectedValue(new Error('500'))
    renderDashboard()
    await screen.findByText('Fleet OEE')
    expect(screen.queryByText('68.4%')).not.toBeInTheDocument()
  })
})

describe('acknowledging from the dashboard', () => {
  beforeEach(() => {
    happyPath()
    acknowledgeMock.mutate = vi.fn()
  })

  it('acknowledges an alarm without navigating away', async () => {
    renderDashboard()
    const ack = await screen.findAllByRole('button', { name: /^acknowledge /i })
    fireEvent.click(ack[0])
    expect(acknowledgeMock.mutate).toHaveBeenCalled()
  })

  it('says an acknowledgement that did not happen', async () => {
    // FS-480: a row that stays exactly as it was is what success looks like for the
    // moment before the list refetches, so silence on failure reads as success.
    acknowledgeMock.mutate = vi.fn((_vars: any, opts: any) => opts?.onError?.(new Error('502')))
    renderDashboard()
    const ack = await screen.findAllByRole('button', { name: /^acknowledge /i })
    fireEvent.click(ack[0])
    expect((await screen.findByRole('alert')).textContent).toMatch(/could not acknowledge/i)
  })
})

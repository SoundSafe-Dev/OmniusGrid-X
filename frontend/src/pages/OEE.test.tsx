import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { describe, expect, it, vi } from 'vitest'

// The row used to advertise "Click to view detailed OEE metrics" via a tooltip
// but had no handler — a dead click. These lock in that a row expands an inline
// per-asset OEE breakdown (fetched lazily) and collapses again.

const fleet = {
  timeRange: 'Last 24 hours',
  assetCount: 1,
  fleetAverageAvailability: 0,
  fleetAverageOee: 0,
  assets: [{ assetId: 'a1', assetName: 'CNC Mill #1', availability: 0, oee: 0 }],
}

const detail = {
  assetId: 'a1',
  assetName: 'CNC Mill #1',
  timeRange: 'Last 24 hours',
  availability: 0.9,
  performance: 1.0,
  quality: 0.95,
  oee: 0.855,
  stateDurations: { Execute: 3600, Idle: 600 },
  totalPlannedTimeSeconds: 86400,
}

const getFleetOEE = vi.fn().mockResolvedValue(fleet)
const getAssetOEE = vi.fn().mockResolvedValue(detail)

vi.mock('../api', () => ({
  dashboardApi: {
    getFleetOEE: () => getFleetOEE(),
    getAssetOEE: (id: string) => getAssetOEE(id),
  },
}))
vi.mock('../hooks/useAuth', () => ({ useAuth: () => ({ isAdmin: true }) }))
vi.mock('../components/common', () => ({ ExportButton: () => null }))
// The Radix tooltip needs a provider; pass-through keeps this test on the
// click→expand behavior, not tooltip plumbing.
vi.mock('../components/ui', () => ({
  Tooltip: ({ children }: any) => <>{children}</>,
  TooltipTrigger: ({ children }: any) => children,
  TooltipContent: () => null,
}))

import OEE from './OEE'

const wrap = (ui: React.ReactElement) => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>)
}

describe('OEE page — row expands detailed metrics', () => {
  it('renders the asset row without fetching per-asset detail until clicked', async () => {
    wrap(<OEE />)
    await waitFor(() => expect(screen.getByText('CNC Mill #1')).toBeInTheDocument())
    expect(getAssetOEE).not.toHaveBeenCalled()
  })

  it('expands an inline OEE breakdown on click and collapses on a second click', async () => {
    wrap(<OEE />)
    await waitFor(() => expect(screen.getByText('CNC Mill #1')).toBeInTheDocument())

    fireEvent.click(screen.getByText('CNC Mill #1'))

    // Lazily fetches the per-asset detail and renders the breakdown.
    await waitFor(() => expect(getAssetOEE).toHaveBeenCalledWith('a1'))
    expect(await screen.findByText(/State breakdown/)).toBeInTheDocument()
    expect(screen.getByText('85.5%')).toBeInTheDocument() // oee 0.855
    expect(screen.getByText('Execute')).toBeInTheDocument() // a recorded state

    fireEvent.click(screen.getByText('CNC Mill #1'))
    await waitFor(() =>
      expect(screen.queryByText(/State breakdown/)).not.toBeInTheDocument(),
    )
  })
})

// A factor the server could not measure comes back as 1.0 — the neutral multiplier for
// the OEE product. That is the right arithmetic and the wrong thing to print: "100%"
// reads as a perfect score when it is the absence of a measurement. The API has sent
// `quality_measured` / `performance_measured` since FS-234 and nothing read them, so an
// asset with no part counters displayed flawless quality and an OEE that could only be
// an upper bound.
describe('OEE page — an unmeasured factor is not shown as 100%', () => {
  // Read one factor tile by its label. Asserting on a bare "100.0%" matched the
  // fleet-level tiles above the panel as well, which is a different number entirely.
  // Matched on the tile's own <p>, not any element: "OEE" is also a table column
  // header, and "Quality" could become one.
  const tileValue = (label: string) => {
    const tag = screen
      .getAllByText(label)
      .find((el) => el.tagName === 'P' && el.className.includes('text-xs'))
    return tag?.parentElement?.querySelectorAll('p')[1]?.textContent
  }

  const expandDetail = async (over: Record<string, unknown>) => {
    getAssetOEE.mockResolvedValueOnce({ ...detail, ...over })
    wrap(<OEE />)
    await waitFor(() => expect(screen.getByText('CNC Mill #1')).toBeInTheDocument())
    fireEvent.click(screen.getByText('CNC Mill #1'))
    await screen.findByText(/State breakdown/)
  }

  it('shows a dash instead of a perfect score when quality was not measured', async () => {
    await expandDetail({ quality: 1.0, qualityMeasured: false })
    expect(tileValue('Quality')).toBe('—')
  })

  it('says why the factor is missing', async () => {
    await expandDetail({ quality: 1.0, qualityMeasured: false })
    expect(screen.getByText(/No part counters reporting/)).toBeInTheDocument()
  })

  it('labels OEE an upper bound when a factor was stood in for', async () => {
    await expandDetail({ quality: 1.0, qualityMeasured: false })
    expect(screen.getByText(/OEE \(upper bound\)/)).toBeInTheDocument()
    expect(screen.getByText(/the real figure is lower/)).toBeInTheDocument()
  })

  it('handles an unmeasured performance factor the same way', async () => {
    await expandDetail({ performance: 1.0, performanceMeasured: false })
    expect(screen.getByText(/No ideal cycle time recorded/)).toBeInTheDocument()
  })

  it('shows real numbers when both factors were measured', async () => {
    // The negative control: marking everything unmeasured would satisfy the assertions
    // above and make the panel useless on a fully instrumented asset.
    await expandDetail({
      quality: 0.95,
      qualityMeasured: true,
      performanceMeasured: true,
      goodParts: 1228,
      totalParts: 1240,
    })
    expect(tileValue('Quality')).toBe('95.0%')
    expect(screen.getByText(/1228\/1240/)).toBeInTheDocument()
    expect(screen.queryByText(/upper bound/)).not.toBeInTheDocument()
  })

  it('treats an older response with no flags as measured', async () => {
    // Defaulting the other way would put "—" on every asset in a deployment whose
    // backend predates the flags and is otherwise fine.
    await expandDetail({})
    expect(tileValue('OEE')).toBe('85.5%')
    expect(tileValue('Quality')).toBe('95.0%')
    expect(screen.queryByText('—')).not.toBeInTheDocument()
  })
})


// An average of nothing is not zero. The API returned 0 for a fleet with no assets,
// which renders as 0% availability -- a fleet-wide outage reported because there was
// nothing to average. It now returns null, and the page has to show that rather than
// coercing it back with `|| 0`, which is exactly what it used to do.
describe('OEE page — an unmeasured fleet is not a fleet at zero', () => {
  it('shows a dash when the API reports no measurable assets', async () => {
    getFleetOEE.mockReset()
    getFleetOEE.mockResolvedValue({
      ...fleet,
      assetCount: 0,
      assets: [],
      fleetAverageAvailability: null,
      assetsMeasured: 0,
    })
    const { container } = wrap(<OEE />)
    await waitFor(() =>
      expect(container.textContent).toContain('Availability'),
    )
    expect(screen.queryByText('0.0%')).not.toBeInTheDocument()
    expect(container.textContent).toContain('\u2014')
  })

  it('still shows a real fleet average as a percentage', async () => {
    // The negative control: rendering a dash unconditionally would satisfy the test
    // above and remove the number the page exists to show.
    getFleetOEE.mockReset()
    getFleetOEE.mockResolvedValue({
      ...fleet,
      fleetAverageAvailability: 0.873,
      assetsMeasured: 4,
    })
    const { container } = wrap(<OEE />)
    await waitFor(() => expect(container.textContent).toContain('87.3%'))
  })
})

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

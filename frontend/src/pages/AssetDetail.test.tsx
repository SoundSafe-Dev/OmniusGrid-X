import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi, beforeEach } from 'vitest'

// AssetDetail handled loading and a bare `!asset` fallback, so a FETCH failure
// showed "Asset not found" — indistinguishable from a real 404. These lock in a
// distinct error state vs. not-found.

const assetResult: { current: any } = { current: {} }
vi.mock('@tanstack/react-query', () => ({
  useQuery: ({ queryKey }: any) =>
    queryKey[0] === 'asset' ? assetResult.current : { data: undefined },
}))
vi.mock('react-router-dom', async (orig) => ({
  ...(await orig<any>()),
  useParams: () => ({ id: 'a1' }),
}))
vi.mock('../hooks/useAuth', () => ({ useAuth: () => ({ isAdmin: true, isOperator: true }) }))
vi.mock('../components/ui', () => ({
  Tooltip: ({ children }: any) => <>{children}</>,
  TooltipTrigger: ({ children }: any) => children,
  TooltipContent: () => null,
}))
vi.mock('../components/charts', () => ({
  RealtimeTelemetryChart: () => null,
  TelemetryHistoryChart: () => null,
}))
vi.mock('../components/assets/SensorPanels', () => ({ SensorPanels: () => null }))
vi.mock('../components/commands', () => ({ CommandPanel: () => null }))
vi.mock('../components/common', () => ({ ExportButton: () => null }))
vi.mock('../api', () => ({ assetsApi: {}, telemetryApi: {} }))

import AssetDetail from './AssetDetail'

const renderPage = () => render(<MemoryRouter><AssetDetail /></MemoryRouter>)

describe('AssetDetail page states', () => {
  beforeEach(() => { assetResult.current = {} })

  it('shows a distinct error state (not "not found") when the fetch fails', () => {
    assetResult.current = { data: undefined, isLoading: false, isError: true }
    renderPage()
    expect(screen.getByText(/failed to load/i)).toBeInTheDocument()
    expect(screen.queryByText(/not found/i)).not.toBeInTheDocument()
  })

  it('shows not-found when the asset genuinely does not exist', () => {
    assetResult.current = { data: undefined, isLoading: false, isError: false }
    renderPage()
    expect(screen.getByText(/not found/i)).toBeInTheDocument()
  })

  it('renders the asset when loaded', () => {
    assetResult.current = {
      data: { id: 'a1', name: 'CNC Mill #1', currentPackmlState: 'Idle' },
      isLoading: false, isError: false,
    }
    renderPage()
    expect(screen.getByText('CNC Mill #1')).toBeInTheDocument()
  })
})

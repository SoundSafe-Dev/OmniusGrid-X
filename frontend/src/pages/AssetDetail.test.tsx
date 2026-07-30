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
  // Renders its children so the maintenance badge's text is assertable. Stubbed rather
  // than left real because this mock replaces the whole module — a missing export here is
  // `undefined` used as a component, which React reports as an obscure element-type error
  // rather than as the missing mock it is.
  Badge: ({ children }: any) => <span>{children}</span>,
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

describe('AssetDetail — maintenance mode', () => {
  // MAINTENANCE MODE HAD NO READ PATH. Migration 053 added `assets.maintenance_mode`, the
  // admin endpoint writes it, and `TacticalEngine._is_maintenance_mode` reads it before
  // dispatching a control command — but `AssetResponse` did not declare it, and FastAPI
  // drops whatever the schema omits. So an operator could take a machine out of service,
  // have the engine correctly stop commanding it, and see no sign of either anywhere.
  //
  // The frontend had a name for it (`isInMaintenance`, a required boolean populated only
  // by the mock fixtures) that no endpoint has ever sent. Renamed to `maintenanceMode`,
  // which is what `/api/v1/assets` now delivers through the casing seam.
  beforeEach(() => { assetResult.current = {} })

  const asset = (over: Record<string, unknown> = {}) => ({
    data: {
      id: 'a1', name: 'CNC Mill #1', currentPackmlState: 'Execute',
      isActive: true, maintenanceMode: false, ...over,
    },
    isLoading: false, isError: false,
  })

  it('marks an asset that is in maintenance', () => {
    assetResult.current = asset({ maintenanceMode: true })
    renderPage()
    expect(screen.getByText('Maintenance')).toBeInTheDocument()
  })

  it('does not mark an asset that is not', () => {
    // The control. Without it "the badge appears" is satisfied by a badge that always
    // appears, which would tell an operator every machine is out of service.
    assetResult.current = asset({ maintenanceMode: false })
    renderPage()
    expect(screen.queryByText('Maintenance')).not.toBeInTheDocument()
  })

  it('does not mark it when the field is absent', () => {
    // An older deployment whose AssetResponse predates the field sends nothing. Undefined
    // must read as "not in maintenance" rather than throwing or showing the badge —
    // there is no third state to render here, because the PackML state beside it is the
    // page's actual subject.
    assetResult.current = asset({ maintenanceMode: undefined })
    renderPage()
    expect(screen.queryByText('Maintenance')).not.toBeInTheDocument()
    expect(screen.getByText('Execute')).toBeInTheDocument()
  })

  it('keeps showing the PackML state alongside it', () => {
    // The state keeps ticking over while an asset is in maintenance, which is exactly why
    // the omission mattered: the header looked like it was telling you everything.
    assetResult.current = asset({ maintenanceMode: true })
    renderPage()
    expect(screen.getByText('Maintenance')).toBeInTheDocument()
    expect(screen.getByText('Execute')).toBeInTheDocument()
  })
})

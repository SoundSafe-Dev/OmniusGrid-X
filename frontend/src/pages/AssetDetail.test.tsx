// FS-766. Spread the real module rather than listing exports. A hand-written barrel mock is
// a second implementation of `components/ui`, and it drifts the moment the page imports a
// primitive the list does not name — three suites failed with "No ErrorState export is
// defined on the mock", which reads as a mock defect and is actually a real change arriving.
import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi, beforeEach } from 'vitest'

// AssetDetail handled loading and a bare `!asset` fallback, so a FETCH failure
// showed "Asset not found" — indistinguishable from a real 404. These lock in a
// distinct error state vs. not-found.

const assetResult: { current: any } = { current: {} }
const alarmsResult: { current: any } = { current: { data: { items: [] } } }
const alarmsQueryArgs: { current: any } = { current: undefined }
vi.mock('@tanstack/react-query', () => ({
  useQuery: (args: any) => {
    const { queryKey } = args
    if (queryKey[0] === 'asset') return assetResult.current
    if (queryKey[0] === 'asset-alarms') {
      alarmsQueryArgs.current = args
      return alarmsResult.current
    }
    return { data: undefined }
  },
}))
vi.mock('react-router-dom', async (orig) => ({
  ...(await orig<any>()),
  useParams: () => ({ id: 'a1' }),
}))
vi.mock('../hooks/useAuth', () => ({ useAuth: () => ({ isAdmin: true, isOperator: true }) }))
vi.mock('../components/ui', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../components/ui')>()),
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
vi.mock('../components/oee', () => ({ OEEDetailPanel: () => null }))
const acknowledgeMock = { mutate: vi.fn(), isPending: false }
vi.mock('../hooks', () => ({
  useAcknowledgeAlarm: () => acknowledgeMock,
}))
vi.mock('../api', () => ({ assetsApi: {}, telemetryApi: {}, alarmsApi: { list: vi.fn() } }))

import AssetDetail from './AssetDetail'

const renderPage = () => render(<MemoryRouter><AssetDetail /></MemoryRouter>)

describe('AssetDetail page states', () => {
  beforeEach(() => { assetResult.current = {} })

  it('shows a distinct error state (not "not found") when the fetch fails', () => {
    assetResult.current = { data: undefined, isLoading: false, isError: true }
    renderPage()
    expect(screen.getByRole('alert')).toHaveTextContent(/could not be loaded/i)
    expect(screen.queryByText(/not found/i)).not.toBeInTheDocument()
    // Both escapes are present: retry for a transient failure, and a way out for an asset
    // that will never load. Offering only the retry traps the user on a dead page.
    expect(screen.getByRole('button', { name: /retry/i })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /back to assets/i })).toBeInTheDocument()
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

/**
 * The asset-scoped alarms panel (P7, page-enhancement review).
 *
 * The page an operator opens to ask "what is wrong with this machine" had no alarms on
 * it at all — they had to leave for /alarms and filter there, which until P1 they could
 * not do either. `alarmsApi.list({assetId, isActive})` has supported this since the
 * route existed.
 *
 * The property that matters most is the same one this repository keeps buying: a failed
 * alarm query must not render as a quiet machine. "No active alarms" and "we could not
 * ask" are different facts, and only one means walk away.
 */
describe('AssetDetail — alarms for this asset', () => {
  const alarm = {
    id: 'al-9',
    assetId: 'a1',
    severity: 'critical',
    alarmCode: 'VIB-01',
    message: 'Vibration above threshold',
    isActive: true,
    isAcknowledged: false,
    occurredAt: '2026-08-13T09:00:00Z',
  }

  beforeEach(() => {
    assetResult.current = {
      data: { id: 'a1', name: 'CNC Mill #1', currentPackmlState: 'Execute' },
      isLoading: false,
      isError: false,
    }
    alarmsResult.current = { data: { items: [] }, isLoading: false, isError: false }
  })

  it('scopes the query to this asset and to active alarms', () => {
    renderPage()
    expect(alarmsQueryArgs.current?.queryKey).toEqual(['asset-alarms', 'a1'])
  })

  it('lists an active alarm with its code and severity', () => {
    alarmsResult.current = { data: { items: [alarm] }, isLoading: false, isError: false }
    renderPage()
    expect(screen.getByText(/vibration above threshold/i)).toBeInTheDocument()
    expect(screen.getByText(/VIB-01/)).toBeInTheDocument()
  })

  it('does not render a failed alarm query as a quiet machine', () => {
    alarmsResult.current = { data: undefined, isLoading: false, isError: true }
    renderPage()
    expect(screen.getByText(/could not load alarms/i)).toBeInTheDocument()
    expect(screen.queryByText(/no active alarms/i)).not.toBeInTheDocument()
  })

  it('says plainly when the machine really has none', () => {
    renderPage()
    expect(screen.getByText(/no active alarms on this asset/i)).toBeInTheDocument()
  })

  it('offers acknowledge on an unacknowledged alarm and reports a failure', () => {
    alarmsResult.current = { data: { items: [alarm] }, isLoading: false, isError: false }
    acknowledgeMock.mutate = vi.fn((_vars: any, opts: any) => opts?.onError?.(new Error('502')))
    renderPage()
    fireEvent.click(screen.getByRole('button', { name: /acknowledge/i }))
    expect(screen.getByRole('alert').textContent).toMatch(/could not acknowledge/i)
  })
})

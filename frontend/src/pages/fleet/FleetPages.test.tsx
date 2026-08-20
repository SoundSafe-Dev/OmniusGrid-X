/**
 * The fleet pages, and a failed query that removed a whole widget instead of a row.
 *
 * `FleetOverview` runs three queries. Two were destructured with `isError` and share a
 * failure branch. The third was destructured for `data` alone:
 *
 *     const { data: orgs } = useQuery({ queryKey: ['fleet-orgs'], … })
 *     const orgId = orgs?.[0]?.id
 *     …
 *     {orgId && <GeoTabIntegration organizationId={orgId} height={480} />}
 *
 * On failure `orgs` is undefined, so `orgId` is undefined, so the live vehicle map is
 * not rendered — and nothing marks its absence. The page draws its tiles and its
 * workcell list and looks finished. This is the same defect the rest of this codebase
 * has been carrying, in a form the source-level sweep cannot see: the empty state is
 * not a sentence like "No vehicles", it is the widget not being there.
 *
 * `OrganizationTree` is covered too, as the control — it combines all three `isError`
 * flags and was already correct, so these tests describe a real difference between two
 * components in one file rather than a rule imposed on both.
 */
import { render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const listWorkcells = vi.fn()
const listAssets = vi.fn()
const listOrgs = vi.fn()

vi.mock('../../api', () => ({
  workcellsApi: { list: (...a: unknown[]) => listWorkcells(...a) },
  assetsApi: { list: (...a: unknown[]) => listAssets(...a) },
  organizationsApi: { list: (...a: unknown[]) => listOrgs(...a) },
}))

// The map is a large websocket/telematics component with queries of its own. Stubbing it
// keeps these tests about the decision this page makes — render it, or say why not.
vi.mock('../../components/fleet/GeoTabIntegration', () => ({
  GeoTabIntegration: ({ organizationId }: { organizationId: string }) => (
    <div data-testid="geotab" data-org={organizationId} />
  ),
}))

import { TooltipProvider, DialogProvider } from '../../components/ui'
import { FleetOverview, OrganizationTree } from './FleetPages'

// Shapes taken from the clients' declared return types, not invented: `workcellsApi.list`
// unwraps to a bare `Workcell[]`, `organizationsApi.list` returns `Organization[]`, and
// only `assetsApi.list` returns the paged envelope. Guessing these has cost time on three
// separate page tests in this repo.
const workcell = (over: Record<string, unknown> = {}) => ({
  id: 'wc-1',
  name: 'Line 1',
  location: 'Plant A',
  createdAt: '2026-01-01T00:00:00Z',
  updatedAt: '2026-01-01T00:00:00Z',
  ...over,
})

const org = (over: Record<string, unknown> = {}) => ({
  id: 'org-1',
  name: 'Acme Manufacturing',
  createdAt: '2026-01-01T00:00:00Z',
  updatedAt: '2026-01-01T00:00:00Z',
  ...over,
})

const assetsPage = (items: unknown[] = []) => ({
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
      {/* FS-766. The page confirms destructive actions through `DialogProvider` now
          rather than `window.confirm`, and `useDialog` throws outside its provider on
          purpose — a silent no-op would let a delete proceed unconfirmed. The test tree
          therefore has to include it, exactly as `App.tsx` does. */}
      <DialogProvider><TooltipProvider>{ui}</TooltipProvider></DialogProvider>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  listWorkcells.mockResolvedValue([workcell()])
  listAssets.mockResolvedValue(
    assetsPage([
      { id: 'a-1', name: 'CNC Mill', workcellId: 'wc-1', currentPackmlState: 'Execute' },
    ]),
  )
  listOrgs.mockResolvedValue([org()])
})

describe('FleetOverview', () => {
  it('renders the workcells and the live map when everything loads', async () => {
    // The positive control. Without it, "the map is absent" below is satisfied by a page
    // that never renders the map under any circumstances.
    wrap(<FleetOverview />)
    expect(await screen.findByText('Line 1')).toBeInTheDocument()
    const map = await screen.findByTestId('geotab')
    expect(map).toHaveAttribute('data-org', 'org-1')
  })

  it('says why the map is missing rather than omitting it in silence', async () => {
    // THE ASSERTION THIS FILE EXISTS FOR. The orgs query is the only one whose failure
    // did not reach the screen, and it is the one that gates vehicle tracking.
    listOrgs.mockRejectedValue(new Error('unreachable'))
    wrap(<FleetOverview />)
    // The rest of the page still loads — that is the point. Nothing looks wrong.
    expect(await screen.findByText('Line 1')).toBeInTheDocument()
    expect(screen.queryByTestId('geotab')).not.toBeInTheDocument()
    const notice = await screen.findByRole('alert')
    expect(notice.textContent).toMatch(/not an empty fleet/i)
  })

  it('distinguishes a failed lookup from an account with no organization', async () => {
    // Both end with no map. They are not the same thing, and an operator chasing one
    // while the other is true wastes the call.
    listOrgs.mockResolvedValue([])
    wrap(<FleetOverview />)
    const notice = await screen.findByRole('alert')
    expect(notice.textContent).toMatch(/no organization is associated/i)
    expect(notice.textContent).not.toMatch(/failed request/i)
  })

  it('does not render a failed fleet load as an empty fleet', async () => {
    listWorkcells.mockRejectedValue(new Error('unreachable'))
    wrap(<FleetOverview />)
    expect(await screen.findByText(/fleet data could not be loaded/i)).toBeInTheDocument()
    expect(screen.queryByText('No workcells configured.')).not.toBeInTheDocument()
  })

  it('says the fleet is empty when it genuinely is', async () => {
    // The other direction: the failure branch must not swallow a true empty result.
    listWorkcells.mockResolvedValue([])
    wrap(<FleetOverview />)
    expect(await screen.findByText('No workcells configured.')).toBeInTheDocument()
    expect(screen.queryByText(/fleet data could not be loaded/i)).not.toBeInTheDocument()
  })

  it('counts only assets in the Execute state as executing', async () => {
    listAssets.mockResolvedValue(
      assetsPage([
        { id: 'a-1', name: 'One', workcellId: 'wc-1', currentPackmlState: 'Execute' },
        { id: 'a-2', name: 'Two', workcellId: 'wc-1', currentPackmlState: 'Held' },
      ]),
    )
    wrap(<FleetOverview />)
    await screen.findByText('Line 1')
    expect(await screen.findByText('Executing')).toBeInTheDocument()
    // 2 total assets, 1 executing — asserted together so a tile rendering the same
    // number twice cannot satisfy this.
    expect(screen.getByText('Total Assets').previousSibling).toHaveTextContent('2')
    expect(screen.getByText('Executing').previousSibling).toHaveTextContent('1')
  })

  it('sends no tenant identifier and asks for a bounded page', async () => {
    wrap(<FleetOverview />)
    await screen.findByText('Line 1')
    expect(listAssets).toHaveBeenCalledWith(expect.objectContaining({ limit: 500 }))
    // `workcellsApi.list` takes no arguments at all: the endpoint declares only skip and
    // limit, and FastAPI drops unknown query params silently, so an organizationId here
    // would have looked like a filter while doing nothing.
    expect(JSON.stringify(listWorkcells.mock.calls)).not.toContain('rganization')
  })
})

describe('OrganizationTree — the control', () => {
  it('renders the tree when all three queries resolve', async () => {
    wrap(<OrganizationTree />)
    expect(await screen.findByText('Acme Manufacturing')).toBeInTheDocument()
    expect(screen.getByText('Line 1')).toBeInTheDocument()
  })

  it('does not render a failed org query as a tree with a default name', async () => {
    // `org?.name ?? 'Organization'` would otherwise draw a plausible root node labelled
    // "Organization" over no data at all. This component combines all three isError
    // flags, so the fallback is unreachable on failure — which is what makes it the
    // control for FleetOverview above rather than a second defect.
    listOrgs.mockRejectedValue(new Error('unreachable'))
    wrap(<OrganizationTree />)
    await waitFor(() =>
      expect(screen.getByText(/organization structure could not be loaded/i)).toBeInTheDocument(),
    )
    expect(screen.queryByText('Organization')).not.toBeInTheDocument()
  })
})

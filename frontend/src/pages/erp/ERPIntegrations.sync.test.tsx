/**
 * Triggering an ERP sync must not leave the Status tab frozen on the previous run.
 *
 * `POST /erp/integrations/{id}/sync` hands the work to FastAPI `BackgroundTasks` and
 * returns immediately, so its response is only ever "triggered" — the records are not
 * synced when the caller reads it. The page said "Sync triggered for N entity type(s)",
 * which reads as *done*, and nothing ever refetched `erp-sync-status`. A user clicked
 * Sync, was told it had happened, and watched the previous run's counts sit there for as
 * long as they cared to wait.
 *
 * WHY A PLAIN INVALIDATE IS NOT THE FIX, and the reason this needed reading the handler
 * rather than pattern-matching the page: a single refetch fired on success lands
 * milliseconds after the trigger, re-reads the row the sync has not written yet, and then
 * never fires again. It would have looked like a fix in review and changed nothing on
 * screen. The interval is what actually shows the result; the invalidate only gives an
 * immediate first read to whoever is already on the tab.
 *
 * The backend writes no "running" marker at the start of a sync, so there is no
 * in-flight state to poll until it clears — the tab polls while it is mounted, which is
 * the honest version of what is knowable here.
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const getSyncStatus = vi.fn()
const triggerSync = vi.fn()

vi.mock('../../api/erp', () => ({
  erpApi: {
    listIntegrations: vi.fn().mockResolvedValue([
      {
        id: 'erp-1',
        integration_name: 'SAP Prod',
        erp_type: 'sap',
        auth_type: 'oauth2',
        base_url: 'https://sap.example.com',
        is_active: true,
        sync_schedule: '0 * * * *',
        sync_frequency_minutes: 60,
      },
    ]),
    getSyncStatus: (...a: unknown[]) => getSyncStatus(...a),
    listFieldMappings: vi.fn().mockResolvedValue([]),
    listEntities: vi.fn().mockResolvedValue({ items: [] }),
    listEvents: vi.fn().mockResolvedValue({ items: [] }),
    listCorrelations: vi.fn().mockResolvedValue({ items: [] }),
    createIntegration: vi.fn(),
    updateIntegration: vi.fn(),
    deleteIntegration: vi.fn(),
    testConnection: vi.fn(),
    triggerSync: (...a: unknown[]) => triggerSync(...a),
    supportedTypes: () => ['sap'],
  },
}))
vi.mock('../../api/analysisSessions', () => ({ analysisSessionsApi: { createSession: vi.fn() } }))
vi.mock('../../api/platformCorrelation', () => ({ platformCorrelationApi: { attach: vi.fn() } }))

import { ERPIntegrationsPage } from './ERPIntegrations'

const before = [
  { entity_type: 'PurchaseOrder', last_sync_status: 'success', records_synced: 4, records_failed: 0 },
]
const after = [
  { entity_type: 'PurchaseOrder', last_sync_status: 'success', records_synced: 91, records_failed: 0 },
]

const wrap = () => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <ERPIntegrationsPage />
    </QueryClientProvider>,
  )
}

async function openStatusTab() {
  await waitFor(() => expect(screen.getByText('SAP Prod')).toBeInTheDocument())
  fireEvent.click(screen.getByRole('button', { name: /status/i }))
}

describe('ERP sync — the status view does not stay frozen on the previous run', () => {
  beforeEach(() => {
    getSyncStatus.mockReset()
    triggerSync.mockReset()
    triggerSync.mockResolvedValue({ status: 'triggered', message: 'Sync triggered for 1 entity type(s)' })
  })

  it('shows the counts the server currently reports', async () => {
    // The baseline the assertions below move away from. Without it, "91 appears" could
    // pass because 91 was there all along.
    getSyncStatus.mockResolvedValue(before)
    wrap()
    await openStatusTab()
    expect(await screen.findByText(/4✓/)).toBeInTheDocument()
  })

  it('re-reads sync status without the user doing anything', async () => {
    // First read is the old run; every read after it is the finished one. The user
    // takes no action between them — that is the entire point.
    getSyncStatus.mockResolvedValueOnce(before).mockResolvedValue(after)
    vi.useFakeTimers({ shouldAdvanceTime: true })
    try {
      wrap()
      await openStatusTab()
      await screen.findByText(/4✓/)
      await vi.advanceTimersByTimeAsync(11_000)
      await waitFor(() => expect(screen.getByText(/91✓/)).toBeInTheDocument())
    } finally {
      vi.useRealTimers()
    }
  })

  it('says the sync is still running rather than implying it is done', async () => {
    getSyncStatus.mockResolvedValue(before)
    wrap()
    await openStatusTab()
    fireEvent.click(screen.getAllByRole('button', { name: /^sync$/i })[0])
    const notice = await screen.findByText(/running in the background/i)
    expect(notice).toBeInTheDocument()
    // The server's own wording is kept — it names how many entity types were queued.
    expect(notice.textContent).toMatch(/Sync triggered for 1 entity type/)
  })

  it('asks the server for a fresh status as soon as a sync is triggered', async () => {
    getSyncStatus.mockResolvedValue(before)
    wrap()
    await openStatusTab()
    await screen.findByText(/4✓/)
    const readsBefore = getSyncStatus.mock.calls.length
    fireEvent.click(screen.getAllByRole('button', { name: /^sync$/i })[0])
    await waitFor(() =>
      expect(getSyncStatus.mock.calls.length).toBeGreaterThan(readsBefore),
    )
  })
})

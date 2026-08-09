/**
 * A sync that was never correlated says so on the screen (FS-562).
 *
 * THE THIRD STATE. The correlations tab renders an empty list for two situations that mean
 * opposite things: the vendor's records were analysed and nothing anomalous was found, or no
 * analyzer is registered for this vendor's field names so nothing was ever looked at. The
 * server has distinguished them since FS-557 — `routed: false` with a reason — and the answer
 * reached the client only in the sync POST response, which is read once and gone, while this
 * page polls `GET /sync-status`.
 *
 * It is the `failureIsNotEmptiness` class one layer further back. Not a failed read rendering
 * as "no results", but an analysis that never ran rendering as an analysis that found
 * nothing — and this one is worse, because the sync beside it reports **success**.
 *
 * WHAT THESE ASSERT, AND THE ONE THAT MATTERS MOST IS THE THIRD. Rendering the warning is
 * easy to get right. Not rendering it for a routed sync, and not rendering it for a sync that
 * recorded nothing, are what keep the message meaning something: a caveat that appears
 * everywhere is a caveat nobody reads.
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { describe, expect, it, vi } from 'vitest'

const getSyncStatus = vi.fn()

vi.mock('../../api/erp', () => ({
  erpApi: {
    listIntegrations: vi.fn().mockResolvedValue([
      {
        id: 'erp-1',
        integration_name: 'QuickBooks Prod',
        erp_type: 'intuit',
        auth_type: 'oauth2',
        base_url: 'https://qbo.example.com',
        is_active: true,
        sync_schedule: '0 * * * *',
        sync_frequency_minutes: 60,
      },
    ]),
    getSyncStatus: (...a: unknown[]) => getSyncStatus(...a),
    listFieldMappings: vi.fn().mockResolvedValue([]),
    listEntities: vi.fn().mockResolvedValue({ items: [], truncated: false, limit: 200 }),
    listEvents: vi.fn().mockResolvedValue({ items: [], truncated: false, limit: 200 }),
    listCorrelations: vi.fn().mockResolvedValue({ items: [], truncated: false, limit: 200 }),
    createIntegration: vi.fn(),
    updateIntegration: vi.fn(),
    deleteIntegration: vi.fn(),
    testConnection: vi.fn(),
    triggerSync: vi.fn(),
    supportedTypes: () => ['intuit'],
  },
}))
vi.mock('../../api/analysisSessions', () => ({ analysisSessionsApi: { createSession: vi.fn() } }))
vi.mock('../../api/platformCorrelation', () => ({ platformCorrelationApi: { attach: vi.fn() } }))

import { ERPIntegrationsPage } from './ERPIntegrations'

const wrap = () => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <ERPIntegrationsPage />
    </QueryClientProvider>
  )
}

async function openStatus() {
  await waitFor(() => expect(screen.getByText('QuickBooks Prod')).toBeInTheDocument())
  fireEvent.click(screen.getByRole('button', { name: /status/i }))
}

const SYNCED = {
  entity_type: 'Shipment',
  last_sync_at: '2026-08-08T10:00:00Z',
  last_sync_status: 'success',
  records_synced: 41,
  records_failed: 0,
  sync_duration_seconds: 5,
}

describe('a sync with no correlation route says so', () => {
  it('warns when the entity was never analysed', async () => {
    getSyncStatus.mockResolvedValue([
      {
        ...SYNCED,
        correlation_routed: false,
        correlation_reason: 'no correlation route for this erp_type/entity_type',
      },
    ])
    wrap()
    await openStatus()
    // 41 records in and no correlations out. Without this line the screen says "success"
    // and the correlations tab says nothing at all, and the two together read as a clean
    // result rather than an analysis that never ran.
    expect(await screen.findByText(/not analysed/i)).toBeInTheDocument()
  })

  it('still shows the sync as successful, because it was', async () => {
    // The records arrived. Turning a missing analyzer into a failed sync would trade one
    // wrong answer for another, and it is the sync status an operator retries on.
    getSyncStatus.mockResolvedValue([{ ...SYNCED, correlation_routed: false }])
    wrap()
    await openStatus()
    expect(await screen.findByText('success')).toBeInTheDocument()
    expect(screen.getByText(/41✓/)).toBeInTheDocument()
  })

  it('says nothing when the entity WAS analysed', async () => {
    // The assertion that keeps the warning worth reading. A caveat on every row is a
    // caveat that gets ignored, and then the one row that needed it is ignored too.
    getSyncStatus.mockResolvedValue([{ ...SYNCED, correlation_routed: true }])
    wrap()
    await openStatus()
    await waitFor(() => expect(screen.getByText('Shipment')).toBeInTheDocument())
    expect(screen.queryByText(/not analysed/i)).not.toBeInTheDocument()
  })

  it('says nothing when the sync recorded no correlation attempt', async () => {
    // NULL IS NOT FALSE. Every row written before the column existed reports nothing, and
    // claiming those were skipped would put a gap warning on the entire history of every
    // integration — inventing a finding out of an absence of data, which is the same
    // mistake in the opposite direction.
    getSyncStatus.mockResolvedValue([{ ...SYNCED, correlation_routed: null }])
    wrap()
    await openStatus()
    await waitFor(() => expect(screen.getByText('Shipment')).toBeInTheDocument())
    expect(screen.queryByText(/not analysed/i)).not.toBeInTheDocument()
  })

  it('names the entity type, because the answer is per entity', async () => {
    // One integration can have an analyzer for Invoice and none for Shipment. "This vendor
    // is not analysed" would be wrong, and it is the reason this lives on the status rows
    // rather than as a banner over the correlations list.
    getSyncStatus.mockResolvedValue([
      { ...SYNCED, entity_type: 'Invoice', correlation_routed: true },
      { ...SYNCED, entity_type: 'Shipment', correlation_routed: false },
    ])
    wrap()
    await openStatus()
    const warning = await screen.findByText(/not analysed/i)
    expect(warning.textContent).toMatch(/Shipment/)
    expect(warning.textContent).not.toMatch(/Invoice/)
  })
})

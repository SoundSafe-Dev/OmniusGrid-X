/**
 * The UI must survive the rows the API can genuinely return.
 *
 * The backend response model declared `erp_type`, `sync_schedule`,
 * `sync_frequency_minutes`, `records_synced` and `records_failed` as REQUIRED while
 * every one of those columns is nullable. A row holding NULL in any of them returned
 * 500 from create, list, get AND update rather than rendering — so the UI had never
 * seen a null there, and its types said it never could.
 *
 * The API now mirrors the columns. That is the correct fix, and it means these values
 * can genuinely arrive as null, so the page has to cope. Kept in its own file because
 * it mocks the API module wholesale, which would change the other tests' fixtures.
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { describe, expect, it, vi } from 'vitest'

vi.mock('../../api/erp', () => ({
  erpApi: {
    listIntegrations: vi.fn().mockResolvedValue([
      {
        id: 'erp-null-1',
        integration_name: 'Seeded outside the API',
        erp_type: null,
        erp_version: null,
        auth_type: '',
        base_url: '',
        is_active: true,
        sync_schedule: null,
        sync_frequency_minutes: null,
        last_successful_sync: null,
        created_at: null,
        updated_at: null,
      },
    ]),
    getSyncStatus: vi.fn().mockResolvedValue([
      {
        entity_type: 'systemusers',
        last_sync_at: null,
        last_sync_status: 'success',
        records_synced: null,
        records_failed: null,
        sync_duration_seconds: null,
        next_sync_at: null,
      },
    ]),
    createIntegration: vi.fn(),
    updateIntegration: vi.fn(),
    deleteIntegration: vi.fn(),
    testConnection: vi.fn(),
    triggerSync: vi.fn(),
    listFieldMappings: vi.fn().mockResolvedValue([]),
    listEntities: vi.fn().mockResolvedValue({ items: [], truncated: false, limit: 0 }),
    listEvents: vi.fn().mockResolvedValue({ items: [], truncated: false, limit: 0 }),
  },
}))
vi.mock('../../api/analysisSessions', () => ({
  analysisSessionsApi: { createSession: vi.fn() },
}))
vi.mock('../../api/platformCorrelation', () => ({
  platformCorrelationApi: { attach: vi.fn() },
}))

import { ERPIntegrationsPage } from './ERPIntegrations'

const wrap = (ui: React.ReactElement) => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>)
}

describe('ERP integrations page — nullable API fields', () => {
  it('renders an integration whose nullable fields are all null', async () => {
    wrap(<ERPIntegrationsPage />)
    await waitFor(() =>
      expect(screen.getByText('Seeded outside the API')).toBeInTheDocument()
    )
  })

  it('shows 0 for null record counts rather than nothing at all', async () => {
    // The meaningful assertion. React renders `null` as NOTHING, so a bare
    // {records_synced} does not print "null" -- it prints an empty string, and the
    // row reads "✓ ✗" with no numbers. That looks like a rendering glitch rather
    // than a count of zero, and asserting on the absence of the text "null" would
    // pass whether or not the fix is present.
    wrap(<ERPIntegrationsPage />)
    await waitFor(() =>
      expect(screen.getByText('Seeded outside the API')).toBeInTheDocument()
    )
    // The sync panel only renders for the selected integration.
    fireEvent.click(screen.getByRole('button', { name: /status/i }))

    const synced = await screen.findByText(/0✓/)
    expect(synced.textContent).toMatch(/0✓\s*0✗/)
  })
})

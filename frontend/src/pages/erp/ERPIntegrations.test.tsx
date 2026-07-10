import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from 'react-query'
import { describe, expect, it, vi } from 'vitest'

vi.mock('../../api/analysisSessions', () => ({
  analysisSessionsApi: {
    createSession: vi.fn().mockResolvedValue({ id: 'sess-1', title: 'ERP analysis — SAP S/4HANA (Prod)' }),
  },
}))
vi.mock('../../api/platformCorrelation', () => ({
  platformCorrelationApi: {
    attach: vi.fn().mockResolvedValue({
      id: 'ds-1', source_type: 'erp', row_count: 128,
      data_type: 'spreadsheet', file_name: 'erp-entities', source_id: 'erp',
    }),
  },
}))

import { ERPIntegrationsPage } from './ERPIntegrations'
import { platformCorrelationApi } from '../../api/platformCorrelation'

const wrap = (ui: React.ReactElement) => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>)
}

describe('ERP integrations page (single ERP surface)', () => {
  it('lists integrations with Test / Sync / Analyze actions', async () => {
    wrap(<ERPIntegrationsPage />)
    await waitFor(() => expect(screen.getByText('SAP S/4HANA (Prod)')).toBeInTheDocument())
    expect(screen.getAllByText('Test').length).toBeGreaterThan(0)
    expect(screen.getAllByText('Sync').length).toBeGreaterThan(0)
    expect(screen.getAllByText('Analyze').length).toBeGreaterThan(0)
  })

  it('Analyze attaches the integration data to a Correlation AI session', async () => {
    wrap(<ERPIntegrationsPage />)
    await waitFor(() => screen.getByText('SAP S/4HANA (Prod)'))
    fireEvent.click(screen.getAllByText('Analyze')[0])
    await waitFor(() =>
      expect(screen.getByText(/Attached 128 synced records/)).toBeInTheDocument()
    )
    expect(platformCorrelationApi.attach).toHaveBeenCalledWith(
      'sess-1', 'erp', { integration_id: 'erp-sap-1' }
    )
  })
})

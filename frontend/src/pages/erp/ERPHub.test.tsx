import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from 'react-query'
import { describe, expect, it, vi } from 'vitest'

vi.mock('../../api/analysisSessions', () => ({
  analysisSessionsApi: {
    createSession: vi.fn().mockResolvedValue({ id: 'sess-1', title: 'ERP analysis — all entities' }),
  },
}))
vi.mock('../../api/platformCorrelation', () => ({
  platformCorrelationApi: {
    attach: vi.fn().mockResolvedValue({ id: 'ds-1', source_type: 'erp', row_count: 4, data_type: 'spreadsheet', file_name: 'erp-entities', source_id: 'erp' }),
    listSourceTypes: vi.fn().mockResolvedValue([]),
  },
}))

import { ERPHubPage } from './ERPHub'
import { platformCorrelationApi } from '../../api/platformCorrelation'

const wrap = (ui: React.ReactElement) => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}><MemoryRouter>{ui}</MemoryRouter></QueryClientProvider>)
}

describe('ERPHubPage', () => {
  it('shows integrations on the overview tab (demo mocks)', async () => {
    wrap(<ERPHubPage />)
    await waitFor(() => expect(screen.getByText('SAP S/4HANA (Prod)')).toBeInTheDocument())
    expect(screen.getAllByText('Sync now').length).toBeGreaterThan(0)
  })

  it('entities tab lists synced business objects', async () => {
    wrap(<ERPHubPage />)
    await waitFor(() => screen.getByText('SAP S/4HANA (Prod)'))
    fireEvent.click(screen.getByText('Entities'))
    await waitFor(() => expect(screen.getByTestId('entity-PO-10021')).toBeInTheDocument())
    expect(screen.getByTestId('entity-WO-77105')).toBeInTheDocument()
  })

  it('events tab shows the event feed', async () => {
    wrap(<ERPHubPage />)
    await waitFor(() => screen.getByText('SAP S/4HANA (Prod)'))
    fireEvent.click(screen.getByText('Events'))
    await waitFor(() => expect(screen.getByTestId('event-evt-9001')).toBeInTheDocument())
  })

  it('AI tab sends ERP entities to a correlation session', async () => {
    wrap(<ERPHubPage />)
    await waitFor(() => screen.getByText('SAP S/4HANA (Prod)'))
    fireEvent.click(screen.getByText('AI & Correlation'))
    await waitFor(() => screen.getByTestId('erp-ai-panel'))

    fireEvent.click(screen.getByText('Send to Correlation AI'))
    await waitFor(() => expect(screen.getByTestId('ai-result').textContent).toContain('4 ERP records attached'))
    expect(platformCorrelationApi.attach).toHaveBeenCalledWith('sess-1', 'erp', {})
  })
})

/**
 * The ERP hub's Entities / Events / AI tabs.
 *
 * These three API client methods previously had NO production caller — the data was
 * synced, the endpoints worked, and nothing rendered it. That is why the silent
 * truncation on those endpoints was latent rather than live.
 *
 * Now that the tabs exist, the truncation signal has to reach a person. A table showing
 * 200 of 5,000 rows with nothing saying so is a confident, partial answer — the same
 * shape that silently truncated three ERP connectors, one layer up.
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { describe, expect, it, vi } from 'vitest'

const listEntities = vi.fn()
const listEvents = vi.fn()
const listCorrelations = vi.fn()

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
    getSyncStatus: vi.fn().mockResolvedValue([]),
    listFieldMappings: vi.fn().mockResolvedValue([]),
    listEntities: (...a: unknown[]) => listEntities(...a),
    listEvents: (...a: unknown[]) => listEvents(...a),
    listCorrelations: (...a: unknown[]) => listCorrelations(...a),
    createIntegration: vi.fn(),
    updateIntegration: vi.fn(),
    deleteIntegration: vi.fn(),
    testConnection: vi.fn(),
    triggerSync: vi.fn(),
    supportedTypes: () => ['sap'],
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

async function openTab(label: RegExp) {
  await waitFor(() => expect(screen.getByText('SAP Prod')).toBeInTheDocument())
  fireEvent.click(screen.getByRole('button', { name: /status/i }))
  fireEvent.click(await screen.findByRole('tab', { name: label }))
}

const ENTITY = {
  id: 'e1',
  entity_type: 'PurchaseOrder',
  entity_id: 'PO-1',
  source_system: 'sap',
  entity_data: {},
  updated_at: '2026-07-27T10:00:00Z',
}

describe('ERP hub — Entities tab', () => {
  it('renders synced entities', async () => {
    listEntities.mockResolvedValue({ items: [ENTITY], truncated: false, limit: 200 })
    wrap()
    await openTab(/entities/i)
    expect(await screen.findByText('PurchaseOrder')).toBeInTheDocument()
    expect(screen.getByText('PO-1')).toBeInTheDocument()
  })

  it('warns the operator when the list is truncated', async () => {
    // THE ASSERTION THIS FILE EXISTS FOR. Without it the table is a partial answer
    // presented as the whole set.
    listEntities.mockResolvedValue({ items: [ENTITY], truncated: true, limit: 200 })
    wrap()
    await openTab(/entities/i)
    expect(await screen.findByText(/more than 200/i)).toBeInTheDocument()
  })

  it('says nothing about truncation when the list is complete', async () => {
    listEntities.mockResolvedValue({ items: [ENTITY], truncated: false, limit: 200 })
    wrap()
    await openTab(/entities/i)
    await screen.findByText('PurchaseOrder')
    expect(screen.queryByText(/more than/i)).not.toBeInTheDocument()
  })

  it('distinguishes empty from failed', async () => {
    listEntities.mockResolvedValue({ items: [], truncated: false, limit: 200 })
    wrap()
    await openTab(/entities/i)
    expect(await screen.findByText(/no synced entities yet/i)).toBeInTheDocument()
  })

  it('reports a failure instead of rendering an empty table', async () => {
    // An error shown as "no entities" reads as a working integration with no data.
    listEntities.mockRejectedValue(new Error('boom'))
    wrap()
    await openTab(/entities/i)
    expect(await screen.findByText(/could not load synced entities/i)).toBeInTheDocument()
  })
})

describe('ERP hub — Events and AI tabs', () => {
  it('renders inbound webhook events and their truncation notice', async () => {
    listEvents.mockResolvedValue({
      items: [
        {
          id: 'ev1',
          event_type: 'po.created',
          event_id: 'evt-1',
          source_system: 'sap',
          entity_type: 'PurchaseOrder',
          processing_status: 'completed',
          created_at: '2026-07-27T10:00:00Z',
        },
      ],
      truncated: true,
      limit: 100,
    })
    wrap()
    await openTab(/events/i)
    expect(await screen.findByText('po.created')).toBeInTheDocument()
    expect(screen.getByText(/more than 100/i)).toBeInTheDocument()
  })

  it('renders correlations', async () => {
    listCorrelations.mockResolvedValue({
      items: [
        {
          id: 'c1',
          correlation_type: 'work_order_vibration',
          correlation_score: 0.87,
          created_at: '2026-07-27T10:00:00Z',
        },
      ],
      truncated: false,
      limit: 100,
    })
    wrap()
    await openTab(/^ai$/i)
    expect(await screen.findByText('work_order_vibration')).toBeInTheDocument()
    expect(screen.getByText(/0\.87/)).toBeInTheDocument()
  })
})

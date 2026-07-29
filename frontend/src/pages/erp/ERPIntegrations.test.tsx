/**
 * ERP integrations. The second half of this file is about the mutation sweep.
 *
 * `testMut` wrote its outcome into a per-integration map on SUCCESS ONLY. With no
 * `onError`, a failed connection test wrote nothing, so whatever the last test had said
 * stayed exactly where it was — "success: Connection test successful", displayed as the
 * result of a test that had just failed.
 *
 * Worse than missing feedback: the button exists to refresh that claim, so the person
 * pressing it is asking the question again and gets last time's answer, in the same
 * place, in the same colour, with nothing marking it stale. Three more mutations here had
 * the same shape (create, delete, sync) while `analyzeMut` — beside them — already had the
 * handler they were missing.
 *
 * The results line also rendered every outcome in the accent colour, so even the failures
 * `analyzeMut` DID record looked like results rather than failures.
 *
 * These use `vi.spyOn` on the real client rather than a module mock, because the suite
 * above deliberately runs against the mock API layer (`VITE_USE_MOCK` is set globally in
 * test/setup.ts) and replacing the module wholesale would rewrite what it exercises.
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, describe, expect, it, vi } from 'vitest'

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
import { erpApi } from '../../api/erp'

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

describe('ERP integrations — a failed action does not pass in silence', () => {
  afterEach(() => vi.restoreAllMocks())

  const firstIntegration = async () => {
    wrap(<ERPIntegrationsPage />)
    await waitFor(() => expect(screen.getByText('SAP S/4HANA (Prod)')).toBeInTheDocument())
  }

  it('shows a successful connection test', async () => {
    // The positive control. Without it, "the stale result is gone" below is satisfied by
    // a page that never shows a test result at all.
    await firstIntegration()
    fireEvent.click(screen.getAllByText('Test')[0])
    expect(
      await screen.findByText(/Connection test successful/i),
    ).toBeInTheDocument()
  })

  it('does not leave the previous success on screen after a failed test', async () => {
    // THE ASSERTION THIS BLOCK EXISTS FOR: test once successfully, then again with the
    // request failing, and the first answer must not survive as the displayed result.
    //
    // ONE SPY, ANSWERING DIFFERENTLY, installed before either click. Installing it
    // between the two clicks looked more natural and did not work — the second press
    // never reached the mutation at all (`spy.mock.calls.length` stayed 0 with the
    // button enabled), so the test failed while reporting the stale text and would have
    // read as the defect surviving. A test that fails for a reason other than the one it
    // names is worse than no test.
    const test = vi
      .spyOn(erpApi, 'testConnection')
      .mockResolvedValueOnce({
        status: 'healthy',
        message: 'connected',
        details: {},
        tested_at: '2026-07-29T00:00:00Z',
      } as any)
      .mockRejectedValue(new Error('unreachable'))

    await firstIntegration()
    fireEvent.click(screen.getAllByText('Test')[0])
    expect(await screen.findByText('healthy: connected')).toBeInTheDocument()

    fireEvent.click(screen.getAllByText('Test')[0])
    await waitFor(() => expect(test).toHaveBeenCalledTimes(2))
    await waitFor(() =>
      expect(screen.queryByText('healthy: connected')).not.toBeInTheDocument(),
    )
    expect(await screen.findByRole('alert')).toHaveTextContent(
      /Connection test failed to run/i,
    )
  })

  it('renders a failure in the alarm colour rather than the accent one', async () => {
    // Every outcome shared one colour, so a recorded failure still read as a result.
    vi.spyOn(erpApi, 'testConnection').mockRejectedValue(new Error('unreachable'))
    await firstIntegration()
    fireEvent.click(screen.getAllByText('Test')[0])
    const notice = await screen.findByRole('alert')
    expect(notice.className).toContain('text-status-alarm')
  })

  it('does not let a failed sync pass in silence', async () => {
    vi.spyOn(erpApi, 'triggerSync').mockRejectedValue(new Error('unreachable'))
    await firstIntegration()
    fireEvent.click(screen.getAllByText('Sync')[0])
    expect(await screen.findByRole('alert')).toHaveTextContent(/Could not trigger a sync/i)
  })

  it('does not let a failed delete look like a successful one', async () => {
    // The row is still there either way, which is what success looks like until the list
    // refetches — so "still there" carried no information at all.
    vi.spyOn(erpApi, 'deleteIntegration').mockRejectedValue(new Error('unreachable'))
    await firstIntegration()
    const buttons = screen.getAllByRole('button')
    fireEvent.click(buttons[buttons.length - 1])
    expect(await screen.findByRole('alert')).toHaveTextContent(/Could not delete/i)
    expect(screen.getByText('SAP S/4HANA (Prod)')).toBeInTheDocument()
  })
})

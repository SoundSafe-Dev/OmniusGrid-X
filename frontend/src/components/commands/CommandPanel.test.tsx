import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const get = vi.fn()

vi.mock('../../api', () => ({
  api: {
    post: vi.fn().mockResolvedValue({ data: { command_id: 'c1', status: 'pending' } }),
    get: (...a: unknown[]) => get(...a),
  },
}))

import { CommandPanel } from './CommandPanel'

const wrap = (ui: React.ReactElement) => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>)
}

beforeEach(() => {
  get.mockReset()
  get.mockResolvedValue({ data: [] })
})

describe('CommandPanel', () => {
  it('renders command options, state badge, and emergency stop', () => {
    wrap(<CommandPanel canEmergencyStop assetId="a1" assetName="Printer #1" currentState="Execute" />)
    expect(screen.getByText('Command Control')).toBeInTheDocument()
    expect(screen.getByText('Printer #1')).toBeInTheDocument()
    expect(screen.getByText('State: Execute')).toBeInTheDocument()
    expect(screen.getByText('STOP NOW')).toBeInTheDocument()
    for (const label of ['Pause Job', 'Resume Job', 'Set Speed', 'Set Temperature']) {
      expect(screen.getByText(label)).toBeInTheDocument()
    }
  })

  it('posts emergency stop to the /api/v1/commands route', async () => {
    const { api } = await import('../../api')
    wrap(<CommandPanel canEmergencyStop assetId="a1" assetName="Printer #1" />)
    fireEvent.click(screen.getByText('STOP NOW'))
    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith('/api/v1/commands/asset/a1/emergency-stop')
    )
  })
})

// Both mutations invalidated `['commands', assetId]` and NO query declared that key, so
// the refetch went nowhere. The panel meanwhile told the operator to "view command
// history in the asset details page" — the page that renders this panel and no history —
// while GET /api/v1/commands/asset/{id} worked and had zero callers.
//
// It is not just a missing list. command_executor dispatches off the request path, so
// "Command submitted successfully" only ever meant the row was written; whether the
// machine acted was not observable anywhere in the product.
describe('CommandPanel — command history', () => {
  const record = (over: Record<string, unknown> = {}) => ({
    command_id: 'c1',
    status: 'completed',
    action: 'pause_job',
    issued_at: '2026-07-28T10:00:00Z',
    executed_at: '2026-07-28T10:00:02Z',
    ...over,
  })

  it('fetches the history the invalidation always targeted', async () => {
    wrap(<CommandPanel assetId="a1" assetName="Printer #1" />)
    await waitFor(() =>
      expect(get).toHaveBeenCalledWith('/api/v1/commands/asset/a1', expect.anything()),
    )
  })

  it('shows each command with the status the server reports', async () => {
    get.mockResolvedValue({ data: [record({ status: 'failed', action: 'set_speed' })] })
    wrap(<CommandPanel assetId="a1" assetName="Printer #1" />)
    expect(await screen.findByText('set_speed')).toBeInTheDocument()
    expect(screen.getByText('failed')).toBeInTheDocument()
  })

  it('says so when nothing has been sent, rather than showing an empty box', async () => {
    wrap(<CommandPanel assetId="a1" assetName="Printer #1" />)
    expect(await screen.findByText(/No commands have been sent/)).toBeInTheDocument()
  })

  it('does not claim a history page that does not exist', async () => {
    wrap(<CommandPanel assetId="a1" assetName="Printer #1" />)
    await screen.findByText(/No commands have been sent/)
    expect(screen.queryByText(/asset details page/i)).not.toBeInTheDocument()
  })

  it('warns while a command is still in flight', async () => {
    get.mockResolvedValue({ data: [record({ status: 'pending' })] })
    wrap(<CommandPanel assetId="a1" assetName="Printer #1" />)
    expect(await screen.findByText(/still in flight/)).toBeInTheDocument()
  })

  it('says nothing about flight once every command has settled', async () => {
    // The negative control: a warning shown unconditionally would satisfy the test
    // above while telling the operator nothing.
    get.mockResolvedValue({ data: [record({ status: 'completed' })] })
    wrap(<CommandPanel assetId="a1" assetName="Printer #1" />)
    await screen.findByText('pause_job')
    expect(screen.queryByText(/still in flight/)).not.toBeInTheDocument()
  })

  it('refreshes the history after an emergency stop', async () => {
    // Submit refreshed it and emergency stop did not, so the one command an operator
    // most needs to see land was the one missing from the list.
    wrap(<CommandPanel canEmergencyStop assetId="a1" assetName="Printer #1" />)
    await screen.findByText(/No commands have been sent/)
    const before = get.mock.calls.length
    fireEvent.click(screen.getByText('STOP NOW'))
    await waitFor(() => expect(get.mock.calls.length).toBeGreaterThan(before))
  })
})

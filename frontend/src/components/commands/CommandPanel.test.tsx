import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from 'react-query'
import { describe, expect, it, vi } from 'vitest'

vi.mock('../../api', () => ({
  api: {
    post: vi.fn().mockResolvedValue({ data: { command_id: 'c1', status: 'pending' } }),
  },
}))

import { CommandPanel } from './CommandPanel'

const wrap = (ui: React.ReactElement) => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>)
}

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

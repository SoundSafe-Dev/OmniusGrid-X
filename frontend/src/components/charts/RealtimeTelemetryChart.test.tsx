import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

vi.mock('../../api', () => ({
  websocketManager: {
    subscribe: vi.fn().mockReturnValue(() => {}),
  },
}))

import { RealtimeTelemetryChart } from './RealtimeTelemetryChart'
import { TooltipProvider } from '../ui'

const wrap = (ui: React.ReactElement) => render(<TooltipProvider>{ui}</TooltipProvider>)

describe('RealtimeTelemetryChart', () => {
  it('renders title, connection indicator, and time window without crashing', () => {
    wrap(
      <RealtimeTelemetryChart assetId="a1" assetName="Printer #1" metrics={['temperature']} />
    )
    expect(screen.getByText('Real-time Telemetry - Printer #1')).toBeInTheDocument()
    // No websocket connection in the test environment.
    expect(screen.getByText('Disconnected')).toBeInTheDocument()
    // Default 5-minute window.
    expect(screen.getByText('Window: 5min')).toBeInTheDocument()
  })

  it('subscribes to telemetry and connection status on mount', async () => {
    const { websocketManager } = await import('../../api')
    wrap(<RealtimeTelemetryChart assetId="a1" metrics={['temperature']} />)
    const topics = (websocketManager.subscribe as ReturnType<typeof vi.fn>).mock.calls.map(
      (c) => c[0]
    )
    expect(topics).toContain('telemetry')
    expect(topics).toContain('connection_status')
  })
})

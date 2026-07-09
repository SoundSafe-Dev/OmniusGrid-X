import { render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from 'react-query'
import { describe, expect, it, vi } from 'vitest'

vi.mock('../../api', () => ({
  telemetryApi: {
    getAvailableMetrics: vi.fn().mockResolvedValue({ assetId: 'a1', metrics: ['temp', 'rpm'] }),
    getHistory: vi.fn().mockResolvedValue([
      { timestamp: '2026-07-09T10:00:00Z', metricName: 'temp', value: 21.5 },
      { timestamp: '2026-07-09T10:02:00Z', metricName: 'temp', value: 22.1 },
    ]),
  },
}))

import { TelemetryHistoryChart } from './TelemetryHistoryChart'

const wrap = (ui: React.ReactElement) => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>)
}

describe('TelemetryHistoryChart', () => {
  it('loads metrics and offers aggregation buttons', async () => {
    wrap(<TelemetryHistoryChart assetId="a1" />)
    await waitFor(() => expect(screen.getByLabelText('Metric')).toBeInTheDocument())
    // metric options populated from getAvailableMetrics
    await waitFor(() => expect(screen.getByRole('option', { name: 'temp' })).toBeInTheDocument())
    // aggregation choices rendered
    for (const label of ['Raw', '1m', '5m', '1h']) {
      expect(screen.getByText(label)).toBeInTheDocument()
    }
  })

  it('requests history for the first available metric', async () => {
    const { telemetryApi } = await import('../../api')
    wrap(<TelemetryHistoryChart assetId="a1" />)
    await waitFor(() =>
      expect(telemetryApi.getHistory).toHaveBeenCalledWith('a1', { metricName: 'temp', aggregation: undefined })
    )
  })
})

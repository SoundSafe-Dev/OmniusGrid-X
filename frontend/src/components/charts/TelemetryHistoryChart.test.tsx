import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { describe, expect, it, vi } from 'vitest'

vi.mock('../../api', () => ({
  telemetryApi: {
    getAvailableMetrics: vi.fn().mockResolvedValue({ assetId: 'a1', metrics: ['temp', 'rpm'] }),
    getHistoryPage: vi.fn().mockResolvedValue({
      items: [
        { timestamp: '2026-07-09T10:00:00Z', metricName: 'temp', value: 21.5 },
        { timestamp: '2026-07-09T10:02:00Z', metricName: 'temp', value: 22.1 },
      ],
      meta: {
        count: 2,
        skip: 0,
        limit: 1000,
        hasMore: true,
        newest: '2026-07-09T10:02:00Z',
        oldest: '2026-07-09T10:00:00Z',
      },
    }),
  },
}))

import { TelemetryHistoryChart } from './TelemetryHistoryChart'

const wrap = (ui: React.ReactElement) => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>)
}

describe('TelemetryHistoryChart', () => {
  it('loads metrics and offers aggregation + time-range buttons', async () => {
    wrap(<TelemetryHistoryChart assetId="a1" />)
    await waitFor(() => expect(screen.getByLabelText('Metric')).toBeInTheDocument())
    // metric options populated from getAvailableMetrics
    await waitFor(() => expect(screen.getByRole('option', { name: 'temp' })).toBeInTheDocument())
    // aggregation choices rendered
    for (const label of ['Raw', '1m', '5m']) {
      expect(screen.getByText(label)).toBeInTheDocument()
    }
    // time-range presets rendered (FS-126); '1h' appears in both groups
    for (const label of ['6h', '24h', '7d']) {
      expect(screen.getByText(label)).toBeInTheDocument()
    }
    expect(screen.getAllByText('1h').length).toBeGreaterThanOrEqual(2)
  })

  it('requests the first page for the default 24h range', async () => {
    const { telemetryApi } = await import('../../api')
    wrap(<TelemetryHistoryChart assetId="a1" />)
    await waitFor(() => expect(telemetryApi.getHistoryPage).toHaveBeenCalled())
    const [assetId, filters] = (telemetryApi.getHistoryPage as any).mock.calls[0]
    expect(assetId).toBe('a1')
    expect(filters.metricName).toBe('temp')
    expect(filters.aggregation).toBeUndefined()
    // first page has no cursor; startTime is ~24h back
    expect(filters.endTime).toBeUndefined()
    const ageMs = Date.now() - new Date(filters.startTime).getTime()
    expect(ageMs).toBeGreaterThan(23 * 60 * 60 * 1000)
    expect(ageMs).toBeLessThan(25 * 60 * 60 * 1000)
  })

  it('loads older points using meta.oldest as the endTime cursor', async () => {
    const { telemetryApi } = await import('../../api')
    ;(telemetryApi.getHistoryPage as any).mockClear()
    wrap(<TelemetryHistoryChart assetId="a1" />)
    const loadOlder = await screen.findByRole('button', { name: 'Load older' })
    // hasMore: true -> affordance enabled
    await waitFor(() => expect(loadOlder).toBeEnabled())
    await userEvent.click(loadOlder)
    await waitFor(() => expect(telemetryApi.getHistoryPage).toHaveBeenCalledTimes(2))
    const [, filters] = (telemetryApi.getHistoryPage as any).mock.calls[1]
    expect(filters.endTime).toBe('2026-07-09T10:00:00Z')
  })
})

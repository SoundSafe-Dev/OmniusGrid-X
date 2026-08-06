import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { loadInRealMode, restoreMockMode } from '../test/realMode'

/**
 * REAL-MODE tests for the telemetry client (FS-486).
 *
 * Four consumers — more than any other client here — and its mock branch does not fetch at
 * all: `getHistory` SYNTHESISES a sixty-point series over the last two hours from the latest
 * values. Sixty points, always, whatever range was asked for. So the server's 1000-point cap
 * cannot be reached in mock mode, and no test taken through the fixture could ever have
 * noticed a capped chart.
 *
 * **That cap is what this file exists for.** `GET /telemetry/{id}/history` returns a
 * `{items, meta}` envelope where `meta.hasMore` says a full page came back. `getHistory`
 * returns `response.data.items` and throws the envelope away — a documented choice, so that
 * existing chart consumers keep a plain array — and `getHistoryPage` is the one that keeps
 * it. `AnalyticsPages` was on `getHistory` while offering a 30-day range: at minute
 * resolution that is ten times the cap, so a chart headed "Last 30 Days" plotted one end of
 * the window with nothing saying which end, or that there was another. It reads
 * `getHistoryPage` now.
 *
 * A trend taken off the wrong end of a window is not a partial answer. It is a wrong one,
 * and it looks exactly like a right one.
 *
 * THE FILTER NAMES ARE THE OTHER HALF. Every filter is renamed on the way out —
 * `metricName` becomes `metric_name`, `startTime` becomes `start_time`. A misspelling here
 * is not an error: FastAPI ignores an undeclared query parameter, so the server returns the
 * DEFAULT window and the chart draws a period nobody asked for. The mock branch reads the
 * camelCase names off the same object, so it agrees with itself either way.
 */

const get = vi.fn()

vi.mock('./client', () => ({
  api: {
    get: (...args: unknown[]) => get(...args),
    post: vi.fn(),
    patch: vi.fn(),
    put: vi.fn(),
    delete: vi.fn(),
  },
}))
vi.mock('./transformRegistry', () => ({ registerTransform: vi.fn() }))

type AnyApi = Record<string, (...args: any[]) => Promise<any>>

async function telemetry(): Promise<AnyApi> {
  const mod = await loadInRealMode(() => import('./telemetry'))
  return (mod as unknown as { telemetryApi: AnyApi }).telemetryApi
}

const POINT = {
  timestamp: '2026-08-06T09:00:00Z',
  metricName: 'temperature',
  value: 41.2,
  unit: 'C',
}

const page = (items: unknown[], hasMore: boolean) => ({
  data: {
    items,
    meta: {
      count: items.length,
      skip: 0,
      limit: 1000,
      hasMore,
      newest: '2026-08-06T09:00:00Z',
      oldest: '2026-08-06T08:00:00Z',
    },
  },
})

beforeEach(() => {
  get.mockReset()
})

afterEach(() => {
  restoreMockMode()
})

describe('the history envelope', () => {
  it('keeps meta.hasMore on the paged call', async () => {
    // The flag a chart needs to know it is drawing part of its own range.
    get.mockResolvedValue(page([POINT], true))
    const api = await telemetry()

    const result = await api.getHistoryPage('asset-1', {})

    expect(result.meta.hasMore).toBe(true)
    expect(result.items).toHaveLength(1)
  })

  it('does not claim more exists when the server said otherwise', async () => {
    get.mockResolvedValue(page([POINT], false))
    const api = await telemetry()

    expect((await api.getHistoryPage('asset-1', {})).meta.hasMore).toBe(false)
  })

  it('unwraps to a bare array on the plain call', async () => {
    // Deliberate: `getHistory` stays a point array for consumers that chart a short window
    // and cannot be truncated. The behaviour is asserted so the choice stays a choice
    // rather than becoming an accident — a caller who needs the cap uses getHistoryPage.
    get.mockResolvedValue(page([POINT, { ...POINT, value: 42 }], true))
    const api = await telemetry()

    const points = await api.getHistory('asset-1', {})

    expect(Array.isArray(points)).toBe(true)
    expect(points).toHaveLength(2)
  })
})

describe('filters are renamed on the way out', () => {
  it('sends metric_name, start_time, end_time and aggregation', async () => {
    // FastAPI ignores an undeclared query parameter, so a misspelling returns 200 and the
    // DEFAULT window — the chart draws a period nobody asked for and nothing errors.
    get.mockResolvedValue(page([], false))
    const api = await telemetry()

    await api.getHistoryPage('asset-1', {
      metricName: 'temperature',
      startTime: '2026-08-01T00:00:00Z',
      endTime: '2026-08-06T00:00:00Z',
      aggregation: 'avg',
    })

    expect(get).toHaveBeenCalledWith('/api/v1/telemetry/asset-1/history', {
      params: {
        metric_name: 'temperature',
        start_time: '2026-08-01T00:00:00Z',
        end_time: '2026-08-06T00:00:00Z',
        aggregation: 'avg',
      },
    })
  })

  it('omits the ones that were not given rather than sending empties', async () => {
    // An empty `metric_name` is not the same request as no `metric_name`, and the second is
    // what "all metrics" means.
    get.mockResolvedValue(page([], false))
    const api = await telemetry()

    await api.getHistoryPage('asset-1', { startTime: '2026-08-01T00:00:00Z' })

    expect(get.mock.calls[0][1].params).toEqual({ start_time: '2026-08-01T00:00:00Z' })
  })

  it('renames the metric filter on the latest reading too', async () => {
    get.mockResolvedValue({ data: POINT })
    const api = await telemetry()

    await api.getLatest('asset-1', 'temperature')

    expect(get).toHaveBeenCalledWith('/api/v1/telemetry/asset-1/latest', {
      params: { metric_name: 'temperature' },
    })
  })

  it('asks for every metric when none was named', async () => {
    get.mockResolvedValue({ data: {} })
    const api = await telemetry()

    await api.getLatest('asset-1')

    expect(get).toHaveBeenCalledWith('/api/v1/telemetry/asset-1/latest', { params: undefined })
  })
})

describe('the reading is returned as the server sent it', () => {
  it('invents no packml state', async () => {
    // The mock branch hard-codes `packmlState: 'Execute'` on every reading — the PackML
    // state for "running normally" — so in demo mode nothing is ever stopped. The real
    // path must carry whatever the asset reported, including nothing.
    get.mockResolvedValue({ data: { ...POINT } })
    const api = await telemetry()

    expect(await api.getLatest('asset-1', 'temperature')).not.toHaveProperty('packmlState')
  })

  it('passes a state through when the asset reported one', async () => {
    get.mockResolvedValue({ data: { ...POINT, packmlState: 'Held' } })
    const api = await telemetry()

    expect((await api.getLatest('asset-1', 'temperature')).packmlState).toBe('Held')
  })

  it('reads the available metrics from the metrics endpoint', async () => {
    // The mock derives this from the keys of its latest-values fixture, which is a
    // different question: what the asset has EVER reported versus what it reported last.
    get.mockResolvedValue({ data: { assetId: 'asset-1', metrics: ['temperature', 'vibration'] } })
    const api = await telemetry()

    const metrics = await api.getAvailableMetrics('asset-1')

    expect(get).toHaveBeenCalledWith('/api/v1/telemetry/asset-1/metrics')
    expect(metrics.metrics).toEqual(['temperature', 'vibration'])
  })
})

describe('the harness is not testing the mock branch by accident', () => {
  it('reaches the http client at all', async () => {
    // In mock mode `getHistory` synthesises sixty points and never calls `api.get`. If
    // `loadInRealMode` stopped working, this test is the one that would notice.
    get.mockResolvedValue(page([], false))
    const api = await telemetry()

    await api.getHistory('asset-1', {})

    expect(get).toHaveBeenCalled()
  })
})

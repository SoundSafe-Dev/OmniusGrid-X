import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { loadInRealMode, restoreMockMode } from '../test/realMode'

/**
 * REAL-MODE tests for the fleet KPI client (FS-487).
 *
 * Eight `USE_MOCK` forks behind `PerformancePanel`, and every one of the five range-taking
 * calls builds its query string by hand: `?range=${timeRange}`.
 *
 * **A dropped or misspelled `range` is not an error.** FastAPI declares it as
 * `range: str = Query("month")`, so an absent parameter returns 200 and a thirty-day window
 * — and `_range_start` falls back to thirty days for an unrecognised value too:
 *
 *     _RANGE_DAYS = {"today": 1, "week": 7, "month": 30, "quarter": 90, "year": 365, ...}
 *     since = now - timedelta(days=_RANGE_DAYS.get(time_range, 30))
 *
 * So every way of getting this wrong produces the same answer: a month's figures, under
 * whatever label the operator selected. The mock branch takes no range at all, which is why
 * no test through it could see the difference.
 *
 * That fallback is also why the selector's labels were the other half of FS-486: the endpoint
 * computes a ROLLING window, and the panel called it "This Month". The label now names the
 * days, and `backend/tests/test_kpi_range_labels_are_honest.py` holds the two together.
 *
 * `getVehicleHealthScore` and `getDTCCount` take no range. They are asserted here as the
 * control: a client that appended `?range=` to everything would look correct in every test
 * above and start narrowing two endpoints that have no such parameter.
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

type AnyApi = Record<string, (...args: any[]) => Promise<any>>

async function kpi(): Promise<AnyApi> {
  const mod = await loadInRealMode(() => import('./kpi'))
  return (mod as unknown as { kpiApi: AnyApi }).kpiApi
}

/** The five range-taking calls, and the path each is supposed to reach. */
const RANGED: Array<[string, string]> = [
  ['getFuelEfficiency', '/api/v1/kpi/fuel-efficiency'],
  ['getIdleTime', '/api/v1/kpi/idle-time'],
  ['getOnTimePerformance', '/api/v1/kpi/on-time-performance'],
  ['getCostPerMile', '/api/v1/kpi/cost-per-mile'],
]

beforeEach(() => {
  get.mockReset()
  get.mockResolvedValue({ data: {} })
})

afterEach(() => {
  restoreMockMode()
})

describe('every range-taking call sends its range', () => {
  it.each(RANGED)('%s reaches %s with the range attached', async (method, path) => {
    const api = await kpi()

    await api[method]('quarter')

    expect(get).toHaveBeenCalledWith(`${path}?range=quarter`)
  })

  it.each(RANGED)('%s sends the default rather than nothing', async (method, path) => {
    // The client defaults to 'month'. Omitting the parameter would ALSO give thirty days,
    // so this cannot be caught by comparing figures — only by looking at the request.
    const api = await kpi()

    await api[method]()

    expect(get).toHaveBeenCalledWith(`${path}?range=month`)
  })

  it('sends every value the selector can produce', async () => {
    // `_RANGE_DAYS` accepts these five and silently falls back to thirty days for anything
    // else, so a typo in either list is a window nobody asked for and no error anywhere.
    const api = await kpi()

    for (const range of ['today', 'week', 'month', 'quarter', 'year']) {
      get.mockClear()
      await api.getFuelEfficiency(range)
      expect(get.mock.calls[0][0]).toBe(`/api/v1/kpi/fuel-efficiency?range=${range}`)
    }
  })
})

describe('the calls that take no range do not invent one', () => {
  it('asks for the vehicle health score plainly', async () => {
    // The control. A client that appended `?range=` everywhere would pass every test above
    // and start narrowing two endpoints that have no such parameter — which, because the
    // parameter is simply undeclared there, would also not error.
    const api = await kpi()

    await api.getVehicleHealthScore()

    expect(get).toHaveBeenCalledWith('/api/v1/kpi/vehicle-health')
  })

  it('asks for the DTC count plainly', async () => {
    const api = await kpi()

    await api.getDTCCount()

    expect(get).toHaveBeenCalledWith('/api/v1/kpi/dtc-count')
  })
})

describe('the payload is returned as the server sent it', () => {
  it('does not reshape the fuel-efficiency response', async () => {
    const wire = { averageMpg: 6.4, totalMiles: 12500, byVehicle: [] }
    get.mockResolvedValue({ data: wire })
    const api = await kpi()

    expect(await api.getFuelEfficiency('month')).toEqual(wire)
  })
})

describe('the harness is not testing the mock branch by accident', () => {
  it('reaches the http client at all', async () => {
    const api = await kpi()

    await api.getIdleTime('week')

    expect(get).toHaveBeenCalled()
  })
})

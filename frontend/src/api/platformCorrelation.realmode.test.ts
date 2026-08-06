import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { loadInRealMode, restoreMockMode } from '../test/realMode'

/**
 * REAL-MODE tests for the platform-correlation client (FS-488).
 *
 * Two calls, and the second is the one worth pinning. `attach` adds a platform data source
 * to an analysis session — telemetry, alarms, kanban — and everything the assistant says
 * afterwards is computed over whatever is attached. The mock branch invents an
 * `AttachedSource` on the spot, complete with `row_count: 42`, so in demo mode every attach
 * succeeds and reports a plausible number of rows.
 *
 * The real path must return the SERVER's record. A client echoing its own request would tell
 * an operator a source was attached, with a row count, when the session has nothing in it —
 * and the next answer would be computed over a data set they believe includes it. That is the
 * same failure `CorrelationAIPane.handleAddIntakeData` had at the other end of the wire
 * (FS-481), where a failed attach said nothing at all.
 *
 * `/api/v1/nlp` is NOT in the transform registry, so nothing renames these keys — which is
 * correct here and worth asserting: the body is already snake_case (`source_type`), and a
 * rename would break it rather than fix it.
 */

const get = vi.fn()
const post = vi.fn()

vi.mock('./client', () => ({
  api: {
    get: (...args: unknown[]) => get(...args),
    post: (...args: unknown[]) => post(...args),
    patch: vi.fn(),
    put: vi.fn(),
    delete: vi.fn(),
  },
}))

type AnyApi = Record<string, (...args: any[]) => Promise<any>>

async function platform(): Promise<AnyApi> {
  const mod = await loadInRealMode(() => import('./platformCorrelation'))
  return (mod as unknown as { platformCorrelationApi: AnyApi }).platformCorrelationApi
}

const SOURCE_TYPE = {
  source_type: 'telemetry',
  label: 'Telemetry',
  description: 'Metric history for an asset',
}

const ATTACHED = {
  id: 'plat-server-1',
  source_type: 'telemetry',
  source_id: 'asset-9',
  file_name: 'telemetry-asset-9',
  data_type: 'spreadsheet',
  row_count: 1440,
}

beforeEach(() => {
  get.mockReset()
  post.mockReset()
})

afterEach(() => {
  restoreMockMode()
})

describe('the source types come from the server', () => {
  it('reads the platform-sources endpoint', async () => {
    get.mockResolvedValue({ data: [SOURCE_TYPE] })
    const api = await platform()

    const types = await api.listSourceTypes()

    expect(get).toHaveBeenCalledWith('/api/v1/nlp/platform-sources')
    expect(types).toEqual([SOURCE_TYPE])
  })

  it('does not fall back to a built-in list when the server returns none', async () => {
    // An empty list means this deployment offers no platform sources. Substituting the
    // demo's three would offer an operator sources that cannot be attached.
    get.mockResolvedValue({ data: [] })
    const api = await platform()

    expect(await api.listSourceTypes()).toEqual([])
  })
})

describe('attaching a source', () => {
  it('posts the type and params to the session', async () => {
    post.mockResolvedValue({ data: ATTACHED })
    const api = await platform()

    await api.attach('sess-1', 'telemetry', { asset_id: 'asset-9' })

    expect(post).toHaveBeenCalledWith('/api/v1/nlp/sessions/sess-1/platform-data', {
      source_type: 'telemetry',
      params: { asset_id: 'asset-9' },
    })
  })

  it('sends an empty params object when none was given', async () => {
    // Not `undefined`: the endpoint reads `params` off the body, and an absent key is a
    // different request from an empty one.
    post.mockResolvedValue({ data: ATTACHED })
    const api = await platform()

    await api.attach('sess-1', 'alarms')

    expect(post.mock.calls[0][1]).toEqual({ source_type: 'alarms', params: {} })
  })

  it('returns the server record rather than an invented one', async () => {
    // The mock synthesises an id and `row_count: 42`. A real path doing the same would tell
    // an operator a source was attached, with a row count, when the session has nothing in
    // it — and the next answer would be computed over a data set they believe includes it.
    post.mockResolvedValue({ data: ATTACHED })
    const api = await platform()

    const attached = await api.attach('sess-1', 'telemetry', { asset_id: 'asset-9' })

    expect(attached.id).toBe('plat-server-1')
    expect(attached.row_count).toBe(1440)
  })

  it('lets a failed attach reach the caller', async () => {
    // `CorrelationAIPane` turns this rejection into "Could not attach that document —
    // answers will not take it into account" (FS-481). Swallowing it here would restore the
    // original defect from the other side of the wire.
    post.mockRejectedValue(new Error('409'))
    const api = await platform()

    await expect(api.attach('sess-1', 'telemetry')).rejects.toThrow()
  })
})

describe('the harness is not testing the mock branch by accident', () => {
  it('reaches the http client at all', async () => {
    get.mockResolvedValue({ data: [] })
    const api = await platform()

    await api.listSourceTypes()

    expect(get).toHaveBeenCalled()
  })
})

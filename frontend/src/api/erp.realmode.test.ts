import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { loadInRealMode, restoreMockMode } from '../test/realMode'

/**
 * REAL-MODE tests for the ERP integrations client (FS-486).
 *
 * Fifteen `USE_MOCK` forks — the most of any client after `analysisSessions` — and the mock
 * branch does substantially more work than the others: it keeps a mutable
 * `mockIntegrations` array, splices on delete, and `Object.assign`s on update. That makes it
 * a small in-memory ERP hub rather than a fixture, and the more a double behaves like the
 * real thing, the less any test through it says about the real thing.
 *
 * WHAT THE MOCK CANNOT CHECK, and what is asserted here:
 *
 * **The two optional query parameters.** `triggerSync(id, entityType)` and
 * `listEntities(id, entityType)` build a query string by hand, and the mock branch filters
 * the fixture in JavaScript. A dropped or misspelled parameter returns **200 and everything**
 * — a sync of every entity type when the operator asked for one, and an entity list that
 * ignores the filter it is labelled with. Both directions are asserted: present when given,
 * absent when not.
 *
 * **Truncation survives.** `listEntities`, `listEvents` and `listCorrelations` all return
 * `ListResult`. The mock says `truncated: false`, which is a fact about a fixture; the real
 * path has to read `X-Result-Truncated` off the response. The client's own comment records
 * why the shape was fixed before the consuming tabs were built — so that whoever builds them
 * does not rediscover the problem — and that is only true if the real branch honours it.
 *
 * **`supportedTypes()` is a promise about the backend.** It is the entire surface through
 * which an integration can be created. `intuit` (QuickBooks Online) is a 384-line connector
 * with its own sandbox suite, registered in the factory, and this list omitted it — a shipped
 * capability nobody could reach. The list-versus-factory comparison lives in
 * `backend/tests/test_supported_erp_types_match.py`, because only the backend can see the
 * registry; what is asserted here is the part this file is responsible for.
 */

const get = vi.fn()
const post = vi.fn()
const put = vi.fn()
const del = vi.fn()

vi.mock('./client', () => ({
  api: {
    get: (...args: unknown[]) => get(...args),
    post: (...args: unknown[]) => post(...args),
    put: (...args: unknown[]) => put(...args),
    delete: (...args: unknown[]) => del(...args),
    patch: vi.fn(),
  },
}))

type AnyApi = Record<string, (...args: any[]) => Promise<any>>

async function erp(): Promise<AnyApi> {
  const mod = await loadInRealMode(() => import('./erp'))
  return (mod as unknown as { erpApi: AnyApi }).erpApi
}

const INTEGRATION = {
  id: 'erp-1',
  integration_name: 'SAP production',
  erp_type: 'sap',
  erp_version: 'S/4HANA',
  auth_type: 'oauth2',
  base_url: 'https://sap.example.com',
  is_active: true,
  sync_schedule: '0 * * * *',
  sync_frequency_minutes: 60,
  last_successful_sync: null,
  created_at: '2026-08-01T00:00:00Z',
  updated_at: '2026-08-01T00:00:00Z',
}

const capped = (items: unknown[], limit: number) => ({
  data: items,
  headers: { 'x-result-truncated': 'true', 'x-result-limit': String(limit) },
})

const complete = (items: unknown[]) => ({ data: items, headers: {} })

beforeEach(() => {
  get.mockReset()
  post.mockReset()
  put.mockReset()
  del.mockReset()
})

afterEach(() => {
  restoreMockMode()
})

describe('the optional filters are sent, and only when asked for', () => {
  it('sends entity_type on a targeted sync', async () => {
    // Without it the backend syncs every entity type. The operator asked for one, the
    // response says "triggered", and the difference is invisible from the screen.
    post.mockResolvedValue({ data: { status: 'triggered', message: 'ok' } })
    const api = await erp()

    await api.triggerSync('erp-1', 'purchase_order')

    expect(post.mock.calls[0][0]).toContain('entity_type=purchase_order')
  })

  it('omits it entirely when no type was given', async () => {
    // The other direction. A client that always appended the parameter — empty — would
    // pass the test above while narrowing every full sync to nothing.
    post.mockResolvedValue({ data: { status: 'triggered', message: 'ok' } })
    const api = await erp()

    await api.triggerSync('erp-1')

    expect(post).toHaveBeenCalledWith('/api/v1/erp/integrations/erp-1/sync')
  })

  it('encodes a type that needs it', async () => {
    post.mockResolvedValue({ data: { status: 'triggered', message: 'ok' } })
    const api = await erp()

    await api.triggerSync('erp-1', 'goods receipt')

    expect(post.mock.calls[0][0]).toContain('entity_type=goods%20receipt')
  })

  it('sends entity_type when listing entities, and omits it otherwise', async () => {
    get.mockResolvedValue(complete([]))
    const api = await erp()

    await api.listEntities('erp-1', 'invoice')
    expect(get.mock.calls[0][0]).toContain('entity_type=invoice')

    await api.listEntities('erp-1')
    expect(get.mock.calls[1][0]).toBe('/api/v1/erp/integrations/erp-1/entities')
  })
})

describe('a capped list says so on the real path', () => {
  it('reads the flag off the entities response', async () => {
    get.mockResolvedValue(capped([{ id: 'e1' }], 200))
    const api = await erp()

    const result = await api.listEntities('erp-1')

    expect(result.truncated).toBe(true)
    expect(result.limit).toBe(200)
  })

  it('reads it off events', async () => {
    get.mockResolvedValue(capped([{ id: 'ev1' }], 100))
    const api = await erp()

    expect((await api.listEvents('erp-1')).truncated).toBe(true)
  })

  it('reads it off correlations', async () => {
    get.mockResolvedValue(capped([{ id: 'c1' }], 50))
    const api = await erp()

    expect((await api.listCorrelations()).truncated).toBe(true)
  })

  it('does not claim truncation when the server sent none', async () => {
    // A client that hard-coded `truncated: true` would pass all three tests above and put a
    // permanent "there is more" on every complete list.
    get.mockResolvedValue(complete([{ id: 'e1' }, { id: 'e2' }]))
    const api = await erp()

    const result = await api.listEntities('erp-1')

    expect(result.truncated).toBe(false)
    expect(result.limit).toBe(2)
  })
})

describe('the write paths use the verbs and bodies they claim', () => {
  it('creates with POST and returns the server row, not the request', async () => {
    // The mock branch SYNTHESISES the created integration — id, timestamps, defaults for
    // `sync_schedule` and `sync_frequency_minutes`. The real path must return what the
    // server made, or a defaulted value invented here is displayed as a stored one.
    post.mockResolvedValue({ data: { ...INTEGRATION, id: 'erp-server-assigned' } })
    const api = await erp()

    const created = await api.createIntegration({
      integration_name: 'SAP production',
      erp_type: 'sap',
      auth_type: 'oauth2',
      base_url: 'https://sap.example.com',
    })

    expect(post).toHaveBeenCalledWith('/api/v1/erp/integrations', expect.objectContaining({ erp_type: 'sap' }))
    expect(created.id).toBe('erp-server-assigned')
  })

  it('updates with PUT rather than PATCH', async () => {
    put.mockResolvedValue({ data: INTEGRATION })
    const api = await erp()

    await api.updateIntegration('erp-1', { is_active: false })

    expect(put).toHaveBeenCalledWith('/api/v1/erp/integrations/erp-1', { is_active: false })
  })

  it('deletes the integration it was given', async () => {
    del.mockResolvedValue({ data: {} })
    const api = await erp()

    await api.deleteIntegration('erp-1')

    expect(del).toHaveBeenCalledWith('/api/v1/erp/integrations/erp-1')
  })

  it('posts a connection test and returns the server verdict', async () => {
    // The mock always reports success. This is the one call an operator makes precisely to
    // find out whether something is broken, so a real failure has to reach them intact.
    post.mockResolvedValue({
      data: { status: 'failed', message: 'auth rejected', details: { healthy: false }, tested_at: 'x' },
    })
    const api = await erp()

    const result = await api.testConnection('erp-1')

    expect(post).toHaveBeenCalledWith('/api/v1/erp/integrations/erp-1/test')
    expect(result.status).toBe('failed')
    expect(result.details.healthy).toBe(false)
  })
})

describe('supportedTypes is a promise about what can be created', () => {
  it('offers QuickBooks Online', async () => {
    // FS-486. A 384-line connector with its own sandbox suite, registered in the factory,
    // and absent from the only dropdown through which an integration can be made.
    const api = await erp()
    expect(api.supportedTypes()).toContain('intuit')
  })

  it('does not offer generic', async () => {
    // In the `ERPType` enum, not in the factory registry. Offering it would fail at
    // creation, after the operator had filled in credentials.
    const api = await erp()
    expect(api.supportedTypes()).not.toContain('generic')
  })
})

describe('the harness is not testing the mock branch by accident', () => {
  it('reaches the http client at all', async () => {
    get.mockResolvedValue(complete([]))
    const api = await erp()

    await api.listIntegrations()

    expect(get).toHaveBeenCalledWith('/api/v1/erp/integrations')
  })
})

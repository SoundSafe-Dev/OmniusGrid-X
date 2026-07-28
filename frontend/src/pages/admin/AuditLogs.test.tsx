/**
 * The audit-trail viewer — the operator-facing end of the chain repaired this week.
 *
 * The writers had been rejected by row-level security and the failure swallowed, so
 * exports, bulk jobs and flag changes recorded nothing while reporting success. Fixing
 * that made the entries land and made them readable; this page is where a person finally
 * sees them, and it had no test.
 *
 * It also called `fetch()` directly with a hand-built `Authorization` header instead of
 * going through the shared axios client. That mattered twice over: the client's response
 * interceptor refreshes an expired token on 401 and redirects to `/login` when the
 * refresh fails, so this was the ONE screen that could not recover from expiry — and the
 * audit trail is exactly where someone sits reading long enough to expire. It also put
 * the page outside every frontend/backend contract guard, which scan for calls through
 * the client. Both are fixed; these tests assert the page against the client it now uses.
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const get = vi.fn()
vi.mock('../../api', () => ({ api: { get: (...a: unknown[]) => get(...a) } }))

import { TooltipProvider } from '../../components/ui'
import AuditLogs from './AuditLogs'

const entry = (over: Record<string, unknown> = {}) => ({
  id: 'log-1',
  timestamp: '2026-07-28T10:00:00Z',
  user_id: 'user-1',
  organization_id: 'org-1',
  action: 'export_kanban_tasks',
  resource_type: 'export',
  resource_id: null,
  ip_address: '10.0.0.1',
  user_agent: 'test',
  details: { job_id: 'j1' },
  hash_chain: 'abc123',
  ...over,
})

const page = (items: unknown[] = [entry()], total = items.length) => {
  get.mockImplementation((url: string) =>
    url.startsWith('/api/v1/audit/verify')
      ? Promise.resolve({ data: { verified: true, message: 'Hash chain intact' } })
      : Promise.resolve({ data: { items, total } }),
  )
  return render(
    <TooltipProvider>
      <AuditLogs />
    </TooltipProvider>,
  )
}

beforeEach(() => {
  get.mockReset()
})

describe('AuditLogs', () => {
  it('lists an entry the trail returned', async () => {
    page()
    expect(await screen.findByText('export_kanban_tasks')).toBeInTheDocument()
  })

  it('reads through the shared client, not raw fetch', async () => {
    // The whole point of the rework. A raw fetch skips token refresh and every contract
    // guard; asserting the client is used is what keeps it from drifting back.
    page()
    await screen.findByText('export_kanban_tasks')
    expect(get).toHaveBeenCalledWith(expect.stringContaining('/api/v1/audit/logs'))
  })

  it('asks for a bounded page rather than the whole trail', async () => {
    page()
    await screen.findByText('export_kanban_tasks')
    const url = get.mock.calls[0][0] as string
    expect(url).toMatch(/skip=0/)
    expect(url).toMatch(/limit=\d+/)
  })

  it('surfaces a failure instead of rendering an empty trail', async () => {
    // An audit view that shows nothing on error is indistinguishable from one showing a
    // genuinely empty trail — and "no audit entries" is a compliance claim. The page
    // renders the error text where the table would be, so the table must be gone too.
    // Rendered directly: `page()` installs its own mockImplementation and would
    // overwrite the rejection, which is how the first version of this test silently
    // asserted the happy path.
    get.mockRejectedValue(new Error('the trail could not be read'))
    render(
      <TooltipProvider>
        <AuditLogs />
      </TooltipProvider>,
    )
    expect(await screen.findByText('the trail could not be read')).toBeInTheDocument()
    expect(screen.queryByText('export_kanban_tasks')).not.toBeInTheDocument()
  })
})

describe('AuditLogs — hash-chain verification', () => {
  it('does not verify until asked', async () => {
    page()
    await screen.findByText('export_kanban_tasks')
    expect(
      get.mock.calls.filter(([u]) => String(u).includes('/audit/verify')),
    ).toHaveLength(0)
  })

  it('reports an intact chain', async () => {
    page()
    await screen.findByText('export_kanban_tasks')
    fireEvent.click(screen.getByRole('button', { name: /verify hash chain/i }))
    expect(await screen.findByText('Hash chain intact')).toBeInTheDocument()
  })

  it('reports a broken chain as broken', async () => {
    // The negative control. A verifier that always says "intact" is worse than none:
    // tamper-evidence that cannot report tampering is a false assurance.
    get.mockImplementation((url: string) =>
      url.startsWith('/api/v1/audit/verify')
        ? Promise.resolve({ data: { verified: false, message: 'Chain broken at entry 42' } })
        : Promise.resolve({ data: { items: [entry()], total: 1 } }),
    )
    render(
      <TooltipProvider>
        <AuditLogs />
      </TooltipProvider>,
    )
    await screen.findByText('export_kanban_tasks')
    fireEvent.click(screen.getByRole('button', { name: /verify hash chain/i }))
    expect(await screen.findByText('Chain broken at entry 42')).toBeInTheDocument()
  })

  it('says so when verification itself fails', async () => {
    get.mockImplementation((url: string) =>
      url.startsWith('/api/v1/audit/verify')
        ? Promise.reject(new Error('unreachable'))
        : Promise.resolve({ data: { items: [entry()], total: 1 } }),
    )
    render(
      <TooltipProvider>
        <AuditLogs />
      </TooltipProvider>,
    )
    await screen.findByText('export_kanban_tasks')
    fireEvent.click(screen.getByRole('button', { name: /verify hash chain/i }))
    // Must not fall through to a green "verified" state on an error.
    await waitFor(() => expect(screen.queryByText('Hash chain intact')).not.toBeInTheDocument())
  })
})

describe('AuditLogs — filters reach the server', () => {
  it('sends the action filter as a query parameter', async () => {
    // Filtering client-side over one page would silently exclude matches on every other
    // page — on an audit search, a filter that looks applied and is not is the defect.
    page()
    await screen.findByText('export_kanban_tasks')
    const before = get.mock.calls.length
    // A value the page actually offers. A native <select> ignores a change to an
    // option it does not have, so `login` left the state untouched and nothing
    // refetched — the first version of this test was wrong, not the page.
    const select = screen.getAllByRole('combobox')[0]
    fireEvent.change(select, { target: { value: 'command_executed' } })
    await waitFor(() => expect(get.mock.calls.length).toBeGreaterThan(before))
    const last = get.mock.calls[get.mock.calls.length - 1]
    expect(String(last[0])).toContain('action=command_executed')
  })
})

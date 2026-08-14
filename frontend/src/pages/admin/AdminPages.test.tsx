/**
 * The three admin pages left in `AdminPages.tsx` after `UsersPage` moved out (2026-08-08).
 *
 * WHY THIS FILE EXISTS AGAIN. Deleting it — once its UsersPage describes had moved to
 * `Users.test.tsx` — made `everyRoutedPageHasATest` report Collectors, SystemHealth and
 * Settings as untested. They always were: the file's NAME satisfied the walk while every
 * describe in it was about a different page. A test file that covers none of the
 * components its filename implies is the same shape as a mock more generous than the wire.
 *
 * These are deliberately thin. What they pin is the property this repository keeps paying
 * for: **a failed read must not render as an empty one**, because "no collectors" and "we
 * could not ask" send an operator to different places.
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { TooltipProvider } from '../../components/ui'
import { describe, expect, it, vi, beforeEach } from 'vitest'

const get = vi.fn()
vi.mock('../../api', () => ({ api: { get: (...a: unknown[]) => get(...a) }, authApi: {} }))

import { CollectorsPage, SystemHealthPage, SettingsPage } from './AdminPages'

function show(ui: React.ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <TooltipProvider>
        <MemoryRouter>{ui}</MemoryRouter>
      </TooltipProvider>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  get.mockResolvedValue({ data: [] })
})

describe('CollectorsPage', () => {
  it('renders the agents the fleet endpoint returns', async () => {
    get.mockResolvedValue({
      data: [{
        agent_id: 'agent-7', liveness: 'online',
        active_collectors: 2, total_collectors: 2, buffer_pending: 0, dead_lettered: 0,
      }],
    })
    show(<CollectorsPage />)
    expect(await screen.findByText(/agent-7/)).toBeInTheDocument()
  })

  /**
   * P12 (page-enhancement review). Three things this list did not do: it hid an
   * expiring certificate in a tooltip (an expired cert stops an agent dead), it never
   * showed `dropped` at all — the one unrecoverable figure of the three, which FS-591
   * traced onto the wire specifically so a fleet view could show it and which this
   * page's own interface then omitted — and it rendered agents in arbitrary order, so
   * the offline one was the reader's job to find.
   */
  it('shows dropped readings as loss, not as another grey clause', async () => {
    get.mockResolvedValue({
      data: [{
        agent_id: 'agent-loss', liveness: 'online',
        active_collectors: 2, total_collectors: 2,
        buffer_pending: 0, dead_lettered: 0, dropped: 1234,
      }],
    })
    show(<CollectorsPage />)
    expect(await screen.findByText(/1,234 readings dropped/i)).toBeInTheDocument()
    expect(screen.getByText(/not recoverable/i)).toBeInTheDocument()
  })

  it('says nothing about drops when there are none', async () => {
    // NEGATIVE CONTROL: a permanent "0 readings dropped" line would train the eye to
    // skip the row that matters.
    get.mockResolvedValue({
      data: [{
        agent_id: 'agent-clean', liveness: 'online',
        active_collectors: 2, total_collectors: 2,
        buffer_pending: 0, dead_lettered: 0, dropped: 0,
      }],
    })
    show(<CollectorsPage />)
    await screen.findByText(/agent-clean/)
    expect(screen.queryByText(/dropped/i)).not.toBeInTheDocument()
  })

  it('badges a certificate that is about to expire', async () => {
    get.mockResolvedValue({
      data: [{
        agent_id: 'agent-cert', liveness: 'online',
        active_collectors: 1, total_collectors: 1,
        buffer_pending: 0, dead_lettered: 0, dropped: 0,
        cert_expires_in_seconds: 86400, // one day
      }],
    })
    show(<CollectorsPage />)
    expect(await screen.findByText(/cert 1d/i)).toBeInTheDocument()
  })

  it('does not badge a certificate with months left', async () => {
    get.mockResolvedValue({
      data: [{
        agent_id: 'agent-fine', liveness: 'online',
        active_collectors: 1, total_collectors: 1,
        buffer_pending: 0, dead_lettered: 0, dropped: 0,
        cert_expires_in_seconds: 86400 * 90,
      }],
    })
    show(<CollectorsPage />)
    await screen.findByText(/agent-fine/)
    expect(screen.queryByText(/^cert /i)).not.toBeInTheDocument()
  })

  it('puts the offline agent first, not wherever the server listed it', async () => {
    get.mockResolvedValue({
      data: [
        { agent_id: 'agent-ok', liveness: 'online', active_collectors: 1, total_collectors: 1, buffer_pending: 0, dead_lettered: 0, dropped: 0 },
        { agent_id: 'agent-down', liveness: 'offline', active_collectors: 0, total_collectors: 1, buffer_pending: 0, dead_lettered: 0, dropped: 0 },
        { agent_id: 'agent-stale', liveness: 'stale', active_collectors: 1, total_collectors: 1, buffer_pending: 0, dead_lettered: 0, dropped: 0 },
      ],
    })
    show(<CollectorsPage />)
    await screen.findByText(/agent-down/)
    const order = screen.getAllByText(/^agent-/).map((el) => el.textContent)
    expect(order).toEqual(['agent-down', 'agent-stale', 'agent-ok'])
  })

  it('does not render a failed read as an empty fleet', async () => {
    // The distinction this repository keeps buying: "no collectors are enrolled" is a fact
    // about the estate; "we could not ask" is a fact about the request, and only one of
    // them means an operator should stop looking.
    get.mockRejectedValue(new Error('unreachable'))
    show(<CollectorsPage />)
    await waitFor(() => expect(get).toHaveBeenCalled())
    expect(screen.queryByText(/^no collectors$/i)).not.toBeInTheDocument()
  })
})

describe('SystemHealthPage', () => {
  it('asks the detailed health endpoint', async () => {
    show(<SystemHealthPage />)
    await waitFor(() =>
      expect(get).toHaveBeenCalledWith(expect.stringContaining('/health/detailed')),
    )
  })

  /** P2 (page-enhancement review): `details` and `checked_at` were fetched and
   * DISCARDED — the endpoint has carried per-component payloads since the FS-693 arc
   * gave every background service a check, and the page typed them away. */
  it('expands a tile into the details the endpoint sends', async () => {
    const healthPayload = {
      status: 'ready',
      checked_at: '2026-08-13T12:00:00Z',
      checks: { command_dispatch: 'ok' },
      details: { command_dispatch: { running: true, consecutive_failures: 0 } },
    }
    get.mockImplementation(async (url: string) =>
      url.includes('/health/detailed') ? { data: healthPayload } : { data: {} },
    )
    show(<SystemHealthPage />)

    fireEvent.click(await screen.findByRole('button', { name: /command dispatch health/i }))

    expect(await screen.findByText(/consecutive failures/i)).toBeInTheDocument()
    expect(screen.getByText(/overall: ready/i)).toBeInTheDocument()
  })

  it('does not paint a disabled subsystem as an error', async () => {
    // "disabled" is a deployment posture, not a fault. The old two-state badge rendered
    // an instance with exports switched off as red — and red that is always wrong is red
    // an admin learns to ignore, which un-alarms the genuinely broken tile beside it.
    const healthPayload = {
      status: 'ready',
      checked_at: '2026-08-13T12:00:00Z',
      checks: { export_scheduler: 'disabled', database: 'error: down' },
      details: {},
    }
    get.mockImplementation(async (url: string) =>
      url.includes('/health/detailed') ? { data: healthPayload } : { data: {} },
    )
    show(<SystemHealthPage />)

    const disabledBadge = await screen.findByText('disabled')
    const errorBadge = screen.getByText('error: down')
    expect(disabledBadge.className).not.toMatch(/alarm|error|red/i)
    expect(errorBadge.className).toMatch(/alarm|error|red/i)
  })
})

describe('SettingsPage', () => {
  it('mounts', () => {
    show(<SettingsPage />)
    expect(document.body.textContent).not.toBe('')
  })
})

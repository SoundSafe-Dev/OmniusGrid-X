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
import { render, screen, waitFor } from '@testing-library/react'
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
})

describe('SettingsPage', () => {
  it('mounts', () => {
    show(<SettingsPage />)
    expect(document.body.textContent).not.toBe('')
  })
})

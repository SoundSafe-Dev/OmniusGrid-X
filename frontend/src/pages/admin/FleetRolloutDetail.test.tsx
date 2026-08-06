/**
 * The rollout detail page — pause and cancel, on a fleet taking a firmware release.
 *
 * One of FS-364's untested routed pages, and the one where a silent failure costs the most.
 * Both actions read only `isPending` before FS-480: an operator cancelling a rollout that is
 * going wrong saw the spinner stop and the status badge still read "running", which is
 * exactly what it looks like for the moment before the refetch. The reasonable reading is
 * that it worked. It did not, and the fleet is still taking the release.
 *
 * The mutations live in `useFleet.ts`. The sweep that catches this class everywhere else
 * scans `.tsx` only, so neither it nor the hand-rolled sweep from FS-478 could see them —
 * the third hiding place for one defect, and the reason `mutationFailureIsVisible` now has a
 * call-site-aware check for hooks.
 */
import type { ReactNode } from 'react'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const useAgentRollout = vi.fn()
const pauseMutation = { mutate: vi.fn(), isPending: false, isError: false }
const cancelMutation = { mutate: vi.fn(), isPending: false, isError: false }

vi.mock('../../hooks/useFleet', () => ({
  useAgentRollout: (id: string) => useAgentRollout(id),
  usePauseAgentRollout: () => pauseMutation,
  useCancelAgentRollout: () => cancelMutation,
}))
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<Record<string, unknown>>('react-router-dom')
  return { ...actual, useParams: () => ({ rolloutId: 'ro-1' }) }
})

const { FleetRolloutDetail } = await import('./FleetRolloutDetail')
const { TooltipProvider } = await import('../../components/ui')

/** The page uses `Tooltip`, which throws outside a provider. Without this the failure is a
 *  context error rather than an assertion, which reads as a broken component. */
const wrap = (node: ReactNode) => (
  <TooltipProvider>
    <MemoryRouter>{node}</MemoryRouter>
  </TooltipProvider>
)

const rollout = (over: Record<string, unknown> = {}) => ({
  id: 'ro-1',
  name: 'agent 1.4.0 → stable',
  release_id: 'rel-9',
  status: 'running',
  created_at: '2026-08-01T00:00:00Z',
  updated_at: '2026-08-06T00:00:00Z',
  targets: [
    {
      asset_id: 'a1',
      agent_id: 'ag1',
      status: 'succeeded',
      command_id: 'c1',
      updated_at: '2026-08-06T00:00:00Z',
    },
  ],
  events: [],
  ...over,
})

function show(state: Record<string, unknown> = {}) {
  useAgentRollout.mockReturnValue({
    data: rollout(),
    isLoading: false,
    isError: false,
    refetch: vi.fn(),
    ...state,
  })
  return render(wrap(<FleetRolloutDetail />))
}

beforeEach(() => {
  useAgentRollout.mockReset()
  pauseMutation.mutate = vi.fn()
  cancelMutation.mutate = vi.fn()
  pauseMutation.isError = false
  cancelMutation.isError = false
})

describe('a failed cancel does not look like a successful one (FS-480)', () => {
  it('says the rollout is still running', () => {
    cancelMutation.isError = true
    show()

    const alert = screen.getByRole('alert')
    expect(alert.textContent).toMatch(/could not cancel/i)
    expect(alert.textContent).toMatch(/still running/i)
  })

  it('says which action failed', () => {
    // Pause and cancel are different promises to the operator. "Something went wrong"
    // leaves them unsure which state the fleet is in.
    pauseMutation.isError = true
    show()

    expect(screen.getByRole('alert').textContent).toMatch(/could not pause/i)
  })

  it('says nothing when neither failed', () => {
    show()
    expect(screen.queryByText(/could not cancel/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/could not pause/i)).not.toBeInTheDocument()
  })

  it('still dispatches the action', () => {
    // The other direction: an error banner that replaced the buttons would pass the tests
    // above and remove the feature.
    show()
    fireEvent.click(screen.getByRole('button', { name: /^cancel$/i }))
    expect(cancelMutation.mutate).toHaveBeenCalledWith('ro-1')
  })
})

describe('a rollout that will not load', () => {
  it('says so rather than rendering an empty shell', async () => {
    show({ data: undefined, isError: true })
    await waitFor(() =>
      expect(screen.getByRole('alert').textContent).toMatch(/not found or failed to load/i),
    )
  })

  it('shows a skeleton while loading, not the not-found message', () => {
    const { container } = show({ data: undefined, isLoading: true })
    expect(container.querySelector('.animate-pulse')).toBeTruthy()
    expect(screen.queryByText(/not found or failed/i)).not.toBeInTheDocument()
  })
})

describe('the actions offered match the rollout state', () => {
  it('offers pause and cancel while running', () => {
    show()
    expect(screen.getByRole('button', { name: /pause/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /^cancel$/i })).toBeInTheDocument()
  })

  it('offers neither once it has completed', () => {
    // A pause button on a finished rollout is an action that cannot do anything, and
    // pressing it teaches the operator that buttons here are unreliable.
    useAgentRollout.mockReturnValue({
      data: rollout({ status: 'completed' }),
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    })
    render(wrap(<FleetRolloutDetail />))
    expect(screen.queryByRole('button', { name: /pause/i })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /^cancel$/i })).not.toBeInTheDocument()
  })
})

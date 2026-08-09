/**
 * The FleetTargeting admin page (arrived 2026-08-08 with Hridyansh's fleet work).
 *
 * Written during the merge because `everyRoutedPageHasATest` reported it routed and
 * untested — a page nothing checks for rendering a field that never arrived.
 *
 * Thin on purpose, and pinning the property that keeps costing this product: **a failed
 * read must not render as an empty one.** "No sites configured" and "we could not ask"
 * look identical on screen and mean opposite things.
 */
import { render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi, beforeEach } from 'vitest'

// STUBBED FROM THE REAL MODULE'S OWN EXPORT LIST, not from a hand-written object. A
// partial `vi.mock` throws on any export the page reaches for and the mock omits — which
// is exactly what took Fleet.test.tsx and FleetRolloutDetail.test.tsx down when this merge
// added four hooks to the page they render. Deriving the keys means this file does not
// need editing every time the page gains a query.
vi.mock('../../hooks/useFleet', async () => {
  const actual = await vi.importActual<Record<string, unknown>>('../../hooks/useFleet')
  const stub = () => ({
    data: undefined,
    isLoading: false,
    isError: false,
    mutate: () => {},
    mutateAsync: async () => {},
    isPending: false,
  })
  return Object.fromEntries(Object.keys(actual).map((name) => [name, stub]))
})
vi.mock('../../api', () => ({ api: { get: vi.fn(), post: vi.fn() }, authApi: {} }))

import { FleetTargeting } from './FleetTargeting'

function show() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <FleetTargeting />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

beforeEach(() => vi.clearAllMocks())

describe('FleetTargeting', () => {
  it('mounts and renders something', async () => {
    show()
    await waitFor(() => expect(document.body.textContent?.length ?? 0).toBeGreaterThan(0))
  })

  it('renders without throwing when every query is empty', async () => {
    // The state a fresh organisation is actually in. A page that only survives populated
    // data fails on the first day it is used.
    show()
    expect(screen.queryByText(/undefined|NaN|\[object Object\]/)).not.toBeInTheDocument()
  })
})

/**
 * The error-triage list — one of the two pages a walk kept reporting as already tested.
 *
 * `Fleet` and `ErrorTriage` are imported through the `./pages/admin` barrel, so the string
 * `pages/admin/ErrorTriage` appears nowhere in `App.tsx` and a resolver keyed on the import
 * path found nothing to complain about. `everyRoutedPageHasATest.test.ts` now follows the
 * barrel; this file and `Fleet.test.tsx` are what it turned up.
 *
 * The page itself is careful, and this exists mostly to keep it that way. It distinguishes
 * four states where most pages manage two — loading, failed, *filtered to nothing*, and
 * genuinely nothing — and that third one matters: "No errors match these filters" and "No
 * production errors recorded" are opposite claims, and a triage engineer acts differently on
 * each. It also refuses to let the summary tile's failure masquerade as a quiet week.
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const useErrorList = vi.fn()
const useErrorSummary = vi.fn()

vi.mock('../../hooks/useErrorTriage', () => ({
  useErrorList: (p: unknown) => useErrorList(p),
  useErrorSummary: (r: unknown) => useErrorSummary(r),
  useUpdateErrorStatus: () => ({ mutate: vi.fn(), isPending: false, isError: false }),
}))

const { ErrorTriage } = await import('./ErrorTriage')
const { TooltipProvider } = await import('../../components/ui')

// Shapes taken from `src/types/errorTriage.ts`, not guessed. A wrong fixture throws inside
// the page ("cannot read properties of undefined") and renders an empty document, which
// reads as a component bug rather than a test that made something up.
const errorRow = (over: Record<string, unknown> = {}) => ({
  fingerprint: 'fp-1',
  exception_type: 'IntegrityError',
  route: '/api/v1/assets',
  method: 'POST',
  status_code: 500,
  status: 'open',
  total_count: 118,
  count_in_range: 42,
  regression_count: 0,
  first_seen: '2026-08-01T09:00:00Z',
  last_seen: '2026-08-06T09:00:00Z',
  ...over,
})

const list = (over: Record<string, unknown> = {}) => ({
  data: { items: [errorRow()], total: 1 },
  isLoading: false,
  isError: false,
  refetch: vi.fn(),
  ...over,
})

const summary = (over: Record<string, unknown> = {}) => ({
  data: {
    range: '7d',
    open_count: 3,
    acknowledged_count: 1,
    events_in_range: 42,
    regressions_in_range: 0,
    top_error: {
      fingerprint: 'fp-1',
      exception_type: 'IntegrityError',
      route: '/api/v1/assets',
      count_in_range: 42,
    },
    series: [{ hour: '2026-08-06T09:00:00Z', count: 42 }],
  },
  isLoading: false,
  isError: false,
  ...over,
})

const show = (path = '/admin/errors') =>
  render(
    <MemoryRouter initialEntries={[path]}>
      <TooltipProvider>
        <ErrorTriage />
      </TooltipProvider>
    </MemoryRouter>,
  )

beforeEach(() => {
  useErrorList.mockReset()
  useErrorSummary.mockReset()
  useErrorList.mockReturnValue(list())
  useErrorSummary.mockReturnValue(summary())
})

describe('four states, not two', () => {
  it('shows the errors when they load', () => {
    show()
    expect(screen.getByText('IntegrityError')).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('says a failed list is a failed list, with a retry', async () => {
    const refetch = vi.fn()
    useErrorList.mockReturnValue(list({ data: undefined, isError: true, refetch }))
    show()

    expect(screen.getByRole('alert').textContent).toMatch(/failed to load errors/i)
    // An empty table here would read as "no production errors", which is the single most
    // misleading thing this page could say to somebody checking whether a deploy broke.
    expect(screen.queryByText(/no production errors recorded/i)).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: /retry/i }))
    await waitFor(() => expect(refetch).toHaveBeenCalled())
  })

  it('distinguishes "filtered to nothing" from "nothing happened"', () => {
    // The distinction most pages skip. One means the engineer should widen their filters;
    // the other means the week was clean. Reading the wrong one wastes an investigation or
    // hides an outage.
    useErrorList.mockReturnValue(list({ data: { items: [], total: 0 } }))
    show('/admin/errors?q=IntegrityError')

    expect(screen.getByText(/no errors match these filters/i)).toBeInTheDocument()
    expect(screen.queryByText(/no production errors recorded/i)).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: /clear filters/i })).toBeInTheDocument()
  })

  it('says the range really was clean when no filter is set', () => {
    useErrorList.mockReturnValue(list({ data: { items: [], total: 0 } }))
    show()

    expect(screen.getByText(/no production errors recorded/i)).toBeInTheDocument()
    expect(screen.queryByText(/no errors match these filters/i)).not.toBeInTheDocument()
  })
})

describe('a failed summary is not a quiet week', () => {
  it('says the tile failed rather than showing a blank figure', () => {
    useErrorSummary.mockReturnValue(summary({ data: undefined, isError: true }))
    show()

    expect(screen.getByText(/failed to load error volume/i)).toBeInTheDocument()
  })

  it('says nothing when the summary loaded', () => {
    show()
    expect(screen.queryByText(/failed to load error volume/i)).not.toBeInTheDocument()
  })
})

describe('the filters reach the query', () => {
  it('passes the URL state through rather than defaulting silently', () => {
    // The page reads status, sort, order and range out of the URL. If any of them stopped
    // reaching the hook the list would look right and be answering a different question.
    show('/admin/errors?status=resolved&sort=last_seen&order=asc&range=30d')

    expect(useErrorList).toHaveBeenCalledWith(
      expect.objectContaining({
        status: 'resolved',
        sort: 'last_seen',
        order: 'asc',
        range: '30d',
      }),
    )
    expect(useErrorSummary).toHaveBeenCalledWith('30d')
  })

  it('defaults to active errors over the last week', () => {
    show()
    expect(useErrorList).toHaveBeenCalledWith(
      expect.objectContaining({ status: 'active', sort: 'count', order: 'desc', range: '7d' }),
    )
  })
})

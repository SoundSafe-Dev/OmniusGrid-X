import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi, beforeEach } from 'vitest'

// Assets renders only a loading state and the grid: on a fetch error it showed
// the header over an empty grid (a blank screen), and on zero assets it showed
// an empty grid with no message. These lock in an explicit error state and
// empty state.

const useAssets = vi.fn()
vi.mock('../hooks', () => ({ useAssets: (args: any) => useAssets(args) }))
vi.mock('../api', () => ({
  assetsApi: { getTypes: vi.fn().mockResolvedValue([{ id: 'ty1', name: 'Mill' }]) },
  workcellsApi: { list: vi.fn().mockResolvedValue([{ id: 'wc1', name: 'Cell A' }]) },
}))
vi.mock('../components/ui', () => ({
  Tooltip: ({ children }: any) => <>{children}</>,
  TooltipTrigger: ({ children }: any) => children,
  TooltipContent: () => null,
}))

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import Assets from './Assets'

function renderAssets() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter><Assets /></MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('Assets page states', () => {
  beforeEach(() => useAssets.mockReset())

  it('shows an error state (not a blank screen) when the fetch fails', () => {
    useAssets.mockReturnValue({ data: undefined, isLoading: false, isError: true })
    renderAssets()
    expect(screen.getByText(/failed to load/i)).toBeInTheDocument()
  })

  it('shows an empty state when there are no assets', () => {
    useAssets.mockReturnValue({
      data: { items: [], total: 0, skip: 0, limit: 20 },
      isLoading: false,
      isError: false,
    })
    renderAssets()
    expect(screen.getByText(/no assets/i)).toBeInTheDocument()
  })

  it('renders assets when present', () => {
    useAssets.mockReturnValue({
      data: {
        items: [{ id: 'a1', name: 'CNC Mill #1', current_packml_state: 'Execute' }],
        total: 1, skip: 0, limit: 20,
      },
      isLoading: false,
      isError: false,
    })
    renderAssets()
    expect(screen.getByText('CNC Mill #1')).toBeInTheDocument()
    expect(screen.queryByText(/no assets/i)).not.toBeInTheDocument()
  })
})

/**
 * The filter bar (P6, page-enhancement review). workcell/type/active existed as backend
 * query params for as long as the route has and the page sent none — finding one machine
 * meant paging the whole estate. `search` is the one param added with the bar.
 */
describe('the filter bar', () => {
  beforeEach(() => {
    useAssets.mockReset()
    useAssets.mockReturnValue({
      data: { items: [{ id: 'a1', name: 'CNC Mill #1', current_packml_state: 'Execute' }], total: 40, skip: 20, limit: 20, hasMore: true },
      isLoading: false,
      isError: false,
    })
  })

  it('sends the debounced search and returns to page one', async () => {
    vi.useFakeTimers()
    try {
      renderAssets()
      fireEvent.change(screen.getByLabelText(/search assets/i), {
        target: { value: 'press' },
      })
      await vi.advanceTimersByTimeAsync(350)
      const params = useAssets.mock.calls[useAssets.mock.calls.length - 1][0]
      expect(params.search).toBe('press')
      expect(params.skip).toBe(0)
    } finally {
      vi.useRealTimers()
    }
  })

  it('does not fire a request per keystroke', async () => {
    vi.useFakeTimers()
    try {
      renderAssets()
      const callsBefore = useAssets.mock.calls.length
      for (const value of ['p', 'pr', 'pre', 'pres', 'press']) {
        fireEvent.change(screen.getByLabelText(/search assets/i), { target: { value } })
        await vi.advanceTimersByTimeAsync(50)
      }
      await vi.advanceTimersByTimeAsync(350)
      const searches = useAssets.mock.calls
        .slice(callsBefore)
        .map((call) => call[0]?.search)
        .filter(Boolean)
      expect(searches).toEqual(['press'])
    } finally {
      vi.useRealTimers()
    }
  })

  it('maps the workcell select onto workcellId', async () => {
    renderAssets()
    await screen.findByRole('option', { name: 'Cell A' })
    fireEvent.change(screen.getByLabelText(/workcell/i), { target: { value: 'wc1' } })
    const params = useAssets.mock.calls[useAssets.mock.calls.length - 1][0]
    expect(params.workcellId).toBe('wc1')
    expect(params.skip).toBe(0)
  })

  it('an empty filtered result says the filters are why', async () => {
    useAssets.mockReturnValue({
      data: { items: [], total: 0, skip: 0, limit: 20 },
      isLoading: false,
      isError: false,
    })
    renderAssets()
    await screen.findByRole('option', { name: 'Cell A' })
    fireEvent.change(screen.getByLabelText(/workcell/i), { target: { value: 'wc1' } })
    expect(await screen.findByText(/no assets match the current filters/i)).toBeInTheDocument()
  })
})

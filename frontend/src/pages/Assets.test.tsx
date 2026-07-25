import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi, beforeEach } from 'vitest'

// Assets renders only a loading state and the grid: on a fetch error it showed
// the header over an empty grid (a blank screen), and on zero assets it showed
// an empty grid with no message. These lock in an explicit error state and
// empty state.

const useAssets = vi.fn()
vi.mock('../hooks', () => ({ useAssets: (args: any) => useAssets(args) }))
vi.mock('../components/ui', () => ({
  Tooltip: ({ children }: any) => <>{children}</>,
  TooltipTrigger: ({ children }: any) => children,
  TooltipContent: () => null,
}))

import Assets from './Assets'

function renderAssets() {
  return render(<MemoryRouter><Assets /></MemoryRouter>)
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

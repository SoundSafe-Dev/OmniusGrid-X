import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi, beforeEach } from 'vitest'

// Alarms handled loading and an empty state but not fetch errors — a failed
// load rendered the header over an empty list (blank). This locks in an error
// state.

const useAlarms = vi.fn()
vi.mock('../hooks', () => ({
  useAlarms: (args: any) => useAlarms(args),
  useActiveAlarms: () => ({ data: [] }),
  useAcknowledgeAlarm: () => ({ mutate: vi.fn(), isPending: false }),
}))
vi.mock('../components/ui', () => ({
  Tooltip: ({ children }: any) => <>{children}</>,
  TooltipTrigger: ({ children }: any) => children,
  TooltipContent: () => null,
}))

import Alarms from './Alarms'

const renderAlarms = () => render(<MemoryRouter><Alarms /></MemoryRouter>)

describe('Alarms page states', () => {
  beforeEach(() => useAlarms.mockReset())

  it('shows an error state (not a blank screen) when the fetch fails', () => {
    useAlarms.mockReturnValue({ data: undefined, isLoading: false, isError: true })
    renderAlarms()
    expect(screen.getByText(/failed to load/i)).toBeInTheDocument()
  })

  it('shows the empty state when there are no alarms', () => {
    useAlarms.mockReturnValue({
      data: { items: [], total: 0, skip: 0, limit: 20 },
      isLoading: false, isError: false,
    })
    renderAlarms()
    expect(screen.getByText(/no alarms/i)).toBeInTheDocument()
  })
})

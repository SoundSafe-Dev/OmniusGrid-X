import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi, beforeEach } from 'vitest'

// Alarms handled loading and an empty state but not fetch errors — a failed
// load rendered the header over an empty list (blank). This locks in an error
// state.

const useAlarms = vi.fn()
const acknowledge = { mutate: vi.fn(), isPending: false }
vi.mock('../hooks', () => ({
  useAlarms: (args: any) => useAlarms(args),
  useActiveAlarms: () => ({ data: [] }),
  useAcknowledgeAlarm: () => acknowledge,
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

/**
 * A failed acknowledgement (FS-480).
 *
 * `useAcknowledgeAlarm` lives in `useAlarms.ts`, and both mutation sweeps scanned `.tsx`
 * only — so this was outside them entirely. The page read `isPending` and nothing else: the
 * spinner stopped and the row stayed unacknowledged, which is exactly what it looks like for
 * the moment before the list refetches. The operator's reasonable reading is that it worked,
 * and the alarm nobody owns is the one nobody chases.
 */
describe('an acknowledgement that did not happen', () => {
  // The page reads the camelCase shape the api client already maps to, and the button
  // only renders for an alarm that is active AND not yet acknowledged — which is the only
  // state in which this failure can happen.
  const alarm = {
    id: 'al-1',
    assetId: 'a1',
    assetName: 'Press 1',
    severity: 'critical',
    message: 'Vibration above threshold',
    isActive: true,
    isAcknowledged: false,
    triggeredAt: '2026-08-05T00:00:00Z',
  }

  beforeEach(() => {
    useAlarms.mockReset()
    acknowledge.mutate = vi.fn()
    useAlarms.mockReturnValue({
      data: { items: [alarm], total: 1, skip: 0, limit: 20 },
      isLoading: false,
      isError: false,
    })
  })

  it('says the alarm is still unacknowledged', () => {
    // The page passes a per-call `onError`, so the failure is driven by invoking it.
    acknowledge.mutate = vi.fn((_vars, opts) => opts?.onError?.(new Error('502')))
    renderAlarms()

    fireEvent.click(screen.getByRole('button', { name: /acknowledge/i }))

    const alert = screen.getByRole('alert')
    expect(alert.textContent).toMatch(/could not/i)
    expect(alert.textContent).toMatch(/still unacknowledged|not acknowledged/i)
  })

  it('says nothing when it succeeded', () => {
    // The other direction: a banner on every acknowledgement would make the failure above
    // indistinguishable from the normal case.
    acknowledge.mutate = vi.fn((_vars, opts) => opts?.onSuccess?.())
    renderAlarms()

    fireEvent.click(screen.getByRole('button', { name: /acknowledge/i }))

    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })
})

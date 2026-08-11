/**
 * The alarm badge, and the state it could not express.
 *
 * `useActiveAlarms` polls every TEN SECONDS. The header destructured only `data`, computed
 * `activeAlarms?.count || 0`, and hid the badge behind `> 0`. Two failures followed from that
 * one line, and the second is the serious one:
 *
 *   * a poll that starts failing leaves react-query's last successful `data` in place, so the
 *     badge went on showing a count from an unknown time ago;
 *   * a poll that has NEVER succeeded leaves `data` undefined, `|| 0` turns that into zero,
 *     and the badge disappears — **an alarm feed that has never answered rendered as a plant
 *     with no active alarms.**
 *
 * On an industrial monitoring product this is the one indicator that must never quietly read
 * "all clear". Absence of evidence was being drawn as evidence of absence, in the corner of
 * every page.
 */
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const alarms = vi.fn()
vi.mock('../../hooks/useAlarms', () => ({ useActiveAlarms: () => alarms() }))
vi.mock('../../hooks/useWebSocket', () => ({
  useWebSocket: () => ({ connected: true, connectionState: 'open', pollingFallback: false }),
}))
vi.mock('../../stores/uiStore', () => ({
  useUIStore: () => ({ mobileSidebarOpen: false, setMobileSidebarOpen: vi.fn() }),
}))

import { TooltipProvider } from '../ui/Tooltip'
import { Header } from './Header'

// The header's indicators are all Radix tooltips, which throw outside a provider — the app
// supplies one at the root. Wrapping here rather than mocking `Tooltip` away, because a mocked
// tooltip would not render its trigger and the badge under test lives inside one.
const show = () =>
  render(
    <MemoryRouter>
      <TooltipProvider><Header /></TooltipProvider>
    </MemoryRouter>,
  )

beforeEach(() => vi.clearAllMocks())

describe('when the alarm feed is answering', () => {
  it('shows the count', () => {
    alarms.mockReturnValue({ data: { count: 3 }, isError: false })
    show()
    expect(screen.getByText('3')).toBeInTheDocument()
  })

  it('caps the badge at 9+', () => {
    alarms.mockReturnValue({ data: { count: 42 }, isError: false })
    show()
    expect(screen.getByText('9+')).toBeInTheDocument()
  })

  it('shows no badge when there genuinely are no alarms', () => {
    // The one case where an absent badge is the truth, and the reason the fix could not
    // simply be "always show something".
    alarms.mockReturnValue({ data: { count: 0 }, isError: false })
    show()
    expect(screen.queryByRole('status', { name: /alarm status unavailable/i })).toBeNull()
    expect(screen.queryByText('0')).toBeNull()
  })
})

describe('when the alarm feed is not answering', () => {
  it('says the status is unavailable rather than showing nothing', () => {
    // THE FINDING, cold-start form: no data has ever arrived, so the old code computed 0 and
    // hid the badge. A plant with a dead alarm feed looked identical to a plant with nothing
    // wrong.
    alarms.mockReturnValue({ data: undefined, isError: true })
    show()
    expect(screen.getByRole('status', { name: /alarm status unavailable/i })).toBeInTheDocument()
  })

  it('does not present a surviving count as current', () => {
    // THE FINDING, stale form: react-query keeps the last successful data across a failure,
    // so the badge would have gone on reporting 3 alarms for as long as the feed stayed down.
    alarms.mockReturnValue({ data: { count: 3 }, isError: true })
    show()
    expect(screen.getByRole('status', { name: /alarm status unavailable/i })).toBeInTheDocument()
    expect(screen.queryByText('3')).toBeNull()
  })

  it('recovers once the feed answers again', () => {
    // A warning that never clears is a warning that gets ignored, which would put the badge
    // back in the state this test exists to prevent.
    alarms.mockReturnValue({ data: { count: 2 }, isError: false })
    show()
    expect(screen.queryByRole('status', { name: /alarm status unavailable/i })).toBeNull()
    expect(screen.getByText('2')).toBeInTheDocument()
  })
})

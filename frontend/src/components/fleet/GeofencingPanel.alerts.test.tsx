/**
 * The geofencing alert list — where silence is both the normal state and the broken one.
 *
 * `/ws/geofencing` does not exist on the backend, so `subscribeToAlerts` polls every fifteen
 * seconds. Its catch used to end at `console.error` (FS-487).
 *
 * That is a worse failure than the fleet map's stalled position poll, and for a reason worth
 * naming: **the display of "no alerts" is an empty list.** A poll that has stopped produces
 * exactly the same empty list as a fleet where nothing has happened. There is no stale value
 * to notice and no pin sitting in the wrong place — the absence *is* the display. A truck
 * leaves its zone, the alert exists on the server, and this panel goes on saying nothing.
 *
 * So the panel now says which silence it is showing. The message is deliberately about the
 * meaning of the list rather than about the request: "an empty list right now means nobody
 * knows, not that nothing has happened" is what an operator needs; "poll failed" is not.
 */
import { act, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const getZones = vi.fn()
const getAlerts = vi.fn()
const getUnacknowledgedAlerts = vi.fn()
const subscribeToAlerts = vi.fn()

vi.mock('../../api/geofencing', () => ({
  geofencingApi: {
    getZones: (...a: unknown[]) => getZones(...a),
    getAlerts: (...a: unknown[]) => getAlerts(...a),
    getUnacknowledgedAlerts: (...a: unknown[]) => getUnacknowledgedAlerts(...a),
    subscribeToAlerts: (...a: unknown[]) => subscribeToAlerts(...a),
    acknowledgeAlert: vi.fn(),
    createZone: vi.fn(),
    updateZone: vi.fn(),
    deleteZone: vi.fn(),
  },
}))

const { GeofencingPanel } = await import('./GeofencingPanel')
const { DialogProvider } = await import('../ui')

/** The panel uses `useDialog` for its zone-delete confirmation, which throws outside a
 *  provider — a context error rather than an assertion, which reads as a broken component. */
const show = () => render(<DialogProvider><GeofencingPanel /></DialogProvider>)

/** Keep the panel's error callback so a failed poll can be triggered the way the client
 *  triggers it — fifteen seconds after anyone was watching. */
let reportPollError: ((error: unknown) => void) | undefined

beforeEach(() => {
  getZones.mockReset()
  getAlerts.mockReset()
  getUnacknowledgedAlerts.mockReset()
  subscribeToAlerts.mockReset()
  reportPollError = undefined

  // Read from the client, not guessed: `getZones` returns a bare array and `getAlerts`
  // returns a ListResult. An envelope where an array belongs throws `zones.filter is not a
  // function` inside the render, and the component then produces an EMPTY DOCUMENT — which
  // looks exactly like an assertion failing on a working component.
  getZones.mockResolvedValue([])
  getAlerts.mockResolvedValue({ items: [], truncated: false, limit: 50 })
  getUnacknowledgedAlerts.mockResolvedValue([])
  subscribeToAlerts.mockImplementation((_onAlert, onError) => {
    reportPollError = onError
    return () => {}
  })
})

describe('an empty alert list that means nobody knows (FS-487)', () => {
  it('says checks are failing when the poll errors', async () => {
    show()
    await waitFor(() => expect(reportPollError).toBeTypeOf('function'))

    act(() => reportPollError!(new Error('network')))

    const alert = await screen.findByRole('alert')
    expect(alert.textContent).toMatch(/alert checks are failing/i)
    // The sentence that does the work: it tells the operator what the empty list below it
    // means, which is the only thing they can act on.
    expect(alert.textContent).toMatch(/means nobody knows/i)
  })

  it('says nothing while the poll is working', async () => {
    // An empty list with a healthy poll is a real answer — nothing has happened — and a
    // permanent warning would make the two indistinguishable again, in the other direction.
    show()
    await waitFor(() => expect(subscribeToAlerts).toHaveBeenCalled())

    expect(screen.queryByText(/alert checks are failing/i)).not.toBeInTheDocument()
  })

  it('clears the warning when polling recovers', async () => {
    // A warning that survives recovery is one people learn to ignore, and this panel needs
    // to be believed the one time it fires.
    show()
    await waitFor(() => expect(reportPollError).toBeTypeOf('function'))

    act(() => reportPollError!(new Error('network')))
    await screen.findByRole('alert')

    act(() => reportPollError!(null))
    await waitFor(() =>
      expect(screen.queryByText(/alert checks are failing/i)).not.toBeInTheDocument(),
    )
  })
})

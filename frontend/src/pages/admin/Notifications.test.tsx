/**
 * Notification subscriptions and the delivery log.
 *
 * NO DEFECT WAS FOUND HERE, and that is worth stating rather than leaving implied. Both
 * queries already distinguish a failed load from an empty one, in both panels. These
 * tests exist because that correctness was UNPINNED — the same situation as the tactical
 * engine's thresholds panel, which had been fixed for exactly this and then had a
 * hardcoded badge regress beside it. A page nothing asserts against is a page that can
 * quietly lose a property nobody remembers it had.
 *
 * The distinction matters here for a specific reason. "No deliveries yet" under a
 * Delivery Log is what an operator checks after wiring up a webhook: it means *the
 * platform sent nothing*, so the integration is at fault. If a failed request rendered
 * the same way, they would go and debug a webhook that works.
 *
 * The "Send Test" button is disabled when `subs.length === 0`, which is also true when
 * the subscriptions query fails. That is covered below — it is acceptable only because
 * the failure message sits immediately above the button, so the disabled control is
 * explained rather than mysterious.
 */
import { within, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const listSubscriptions = vi.fn()
const deliveryLog = vi.fn()
const createSubscription = vi.fn()
const deleteSubscription = vi.fn()
const sendTest = vi.fn()
const updateSubscription = vi.fn()

vi.mock('../../api/notifications', async () => {
  const actual = await vi.importActual<any>('../../api/notifications')
  return {
    ...actual,
    notificationsApi: {
      listSubscriptions: (...a: unknown[]) => listSubscriptions(...a),
      deliveryLog: (...a: unknown[]) => deliveryLog(...a),
      createSubscription: (...a: unknown[]) => createSubscription(...a),
      deleteSubscription: (...a: unknown[]) => deleteSubscription(...a),
      sendTest: (...a: unknown[]) => sendTest(...a),
      updateSubscription: (...a: unknown[]) => updateSubscription(...a),
    },
  }
})

import { Notifications } from './Notifications'

// Shapes from `NotificationSubscription` / `NotificationDeliveryEntry`, not invented.
// `listSubscriptions` returns a bare array; only the paged endpoints use an envelope.
const subscription = (over: Record<string, unknown> = {}) => ({
  id: 'sub-1',
  name: 'Ops webhook',
  channel: 'webhook' as const,
  target: 'https://hooks.example/ops',
  minSeverity: 'warning' as const,
  domain: null,
  assetId: null,
  enabled: true,
  ...over,
})

const delivery = (over: Record<string, unknown> = {}) => ({
  id: 'del-1',
  channel: 'webhook',
  severity: 'critical',
  title: 'Nozzle temperature exceeded',
  delivered: true,
  detail: null,
  createdAt: '2026-07-28T09:15:00Z',
  ...over,
})

const wrap = () => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <Notifications />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  listSubscriptions.mockResolvedValue([subscription()])
  // ListResult since FS-485; the page reads `.items` and renders a note off `.truncated`.
  deliveryLog.mockResolvedValue({ items: [delivery()], truncated: false, limit: 100 })
  createSubscription.mockResolvedValue({ id: 'sub-2', name: 'New', channel: 'webhook' })
  deleteSubscription.mockResolvedValue(undefined)
  sendTest.mockResolvedValue({ matched: 1, results: [] })
})

describe('Notifications — subscriptions', () => {
  it('lists what the API returned', async () => {
    wrap()
    expect(await screen.findByText('Ops webhook')).toBeInTheDocument()
    expect(screen.getByText('https://hooks.example/ops')).toBeInTheDocument()
  })

  it('says there are none when there genuinely are none', async () => {
    listSubscriptions.mockResolvedValue([])
    wrap()
    expect(
      await screen.findByText(/No subscriptions yet\. Create one below/i),
    ).toBeInTheDocument()
  })

  it('does not render a failed load as an empty list', async () => {
    // The two states send an admin to different places: one means "set one up", the
    // other means "the subscriptions service is down".
    listSubscriptions.mockRejectedValue(new Error('unreachable'))
    wrap()
    expect(await screen.findByText('Subscriptions could not be loaded.')).toBeInTheDocument()
    expect(
      screen.queryByText(/No subscriptions yet\. Create one below/i),
    ).not.toBeInTheDocument()
  })

  it('explains the disabled test button rather than leaving it inert', async () => {
    // `subs.length === 0` is true on failure as well as on an empty list, so the button
    // is disabled either way. That is acceptable only because the failure message is
    // rendered immediately above it — this asserts they appear together.
    listSubscriptions.mockRejectedValue(new Error('unreachable'))
    wrap()
    await screen.findByText('Subscriptions could not be loaded.')
    expect(screen.getByRole('button', { name: /send test/i })).toBeDisabled()
  })
})

describe('Notifications — deleting a subscription', () => {
  it('removes it when the request succeeds', async () => {
    // The positive control: without it, "an error appears on failure" is satisfied by a
    // delete button that never works at all.
    wrap()
    await screen.findByText('Ops webhook')
    fireEvent.click(screen.getByRole('button', { name: /delete/i }))
    await waitFor(() => expect(deleteSubscription).toHaveBeenCalledWith('sub-1'))
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('does not leave a failed delete looking like a successful one', async () => {
    // FOUND BY THE MUTATION SWEEP, after this page had been read for its query defects
    // and declared clean. The mutation handled only success, so a rejected delete left
    // the row exactly where it was — which is what a successful delete looks like until
    // the list refetches. An admin who believes they stopped a webhook has not.
    deleteSubscription.mockRejectedValue(new Error('unreachable'))
    wrap()
    await screen.findByText('Ops webhook')
    fireEvent.click(screen.getByRole('button', { name: /delete/i }))
    const notice = await screen.findByRole('alert')
    expect(notice.textContent).toMatch(/still active and will keep sending/i)
    expect(screen.getByText('Ops webhook')).toBeInTheDocument()
  })
})

describe('Notifications — the delivery log', () => {
  it('lists dispatch attempts', async () => {
    wrap()
    expect(await screen.findByText('Nozzle temperature exceeded')).toBeInTheDocument()
  })

  it('says nothing has been delivered when nothing has', async () => {
    // What an operator checks after wiring a webhook: the platform sent nothing, so the
    // integration is at fault.
    deliveryLog.mockResolvedValue([])
    wrap()
    expect(await screen.findByText('No deliveries yet.')).toBeInTheDocument()
  })

  it('does not render a failed log query as an empty log', async () => {
    // If this looked the same, they would debug a webhook that works.
    deliveryLog.mockRejectedValue(new Error('unreachable'))
    wrap()
    expect(await screen.findByText('The delivery log could not be loaded.')).toBeInTheDocument()
    expect(screen.queryByText('No deliveries yet.')).not.toBeInTheDocument()
  })

  it('keeps the two panels independent', async () => {
    // A dead log must not blank the subscriptions above it, and vice versa.
    deliveryLog.mockRejectedValue(new Error('unreachable'))
    wrap()
    await screen.findByText('The delivery log could not be loaded.')
    expect(screen.getByText('Ops webhook')).toBeInTheDocument()
  })
})

describe('Notifications — creating a subscription', () => {
  it('refuses a submission with no name and does not call the API', async () => {
    wrap()
    await screen.findByText('Ops webhook')
    fireEvent.click(screen.getByRole('button', { name: /create subscription/i }))
    expect(await screen.findByText('Name is required.')).toBeInTheDocument()
    expect(createSubscription).not.toHaveBeenCalled()
  })

  it('refuses a submission with no target', async () => {
    wrap()
    await screen.findByText('Ops webhook')
    fireEvent.change(screen.getByLabelText(/name/i), { target: { value: 'Pager' } })
    fireEvent.click(screen.getByRole('button', { name: /create subscription/i }))
    expect(await screen.findByText(/Target is required/i)).toBeInTheDocument()
    expect(createSubscription).not.toHaveBeenCalled()
  })

  it('sends a trimmed payload and clears the form on success', async () => {
    wrap()
    await screen.findByText('Ops webhook')
    fireEvent.change(screen.getByLabelText(/name/i), { target: { value: '  Pager  ' } })
    // Exact label: the create form below also has a Target field.
    fireEvent.change(screen.getByLabelText('Target'), {
      target: { value: '  https://hooks.example/pager  ' },
    })
    fireEvent.click(screen.getByRole('button', { name: /create subscription/i }))
    await waitFor(() => expect(createSubscription).toHaveBeenCalled())
    // Asserted on the argument rather than on the rendered form: whitespace in a webhook
    // URL is the kind of thing that fails silently at dispatch time.
    expect(createSubscription).toHaveBeenCalledWith(
      expect.objectContaining({
        name: 'Pager',
        target: 'https://hooks.example/pager',
      }),
    )
  })
})

describe('Notifications — the test dispatch', () => {
  it('reports how many subscriptions a test matched', async () => {
    wrap()
    await screen.findByText('Ops webhook')
    fireEvent.click(screen.getByRole('button', { name: /send test/i }))
    expect(
      await screen.findByText(/Test dispatched — matched 1 subscription\./),
    ).toBeInTheDocument()
  })

  it('says a matched count of zero rather than implying success', async () => {
    // "Test dispatched" alone would read as delivered. Zero matches means the event
    // reached nobody, which is the thing the tester is trying to find out.
    //
    // This asserted the COUNT — "matched 0 subscriptions" — which was already better than
    // silence, and still read as an outcome report in the same grey as a success. FS-487
    // says which it is in the first three words and points at the filters that caused it;
    // the assertion moved with it, and the tone is asserted separately below.
    sendTest.mockResolvedValue({ matched: 0, results: [] })
    wrap()
    await screen.findByText('Ops webhook')
    fireEvent.click(screen.getByRole('button', { name: /send test/i }))
    expect(await screen.findByText(/nothing was sent/i)).toBeInTheDocument()
  })

  it('does not report a failed dispatch as a dispatch', async () => {
    sendTest.mockRejectedValue(new Error('unreachable'))
    wrap()
    await screen.findByText('Ops webhook')
    fireEvent.click(screen.getByRole('button', { name: /send test/i }))
    expect(await screen.findByText('Test dispatch failed.')).toBeInTheDocument()
    expect(screen.queryByText(/Test dispatched/)).not.toBeInTheDocument()
  })
})

describe('a page of the log is not the log (FS-485)', () => {
  it('says so when the server capped it', async () => {
    // Ordered newest first, so what is missing is the OLDEST attempts — and this card is
    // where somebody checks whether an alert was delivered. A capped list presented as
    // complete turns "not listed here" into "never sent".
    deliveryLog.mockResolvedValue({ items: [delivery()], truncated: true, limit: 100 })
    wrap()

    const note = await screen.findByRole('status')
    expect(note.textContent).toMatch(/100 most recent/i)
    expect(note.textContent).toMatch(/may still have been sent/i)
  })

  it('says nothing when the whole log came back', async () => {
    // The other direction. A permanent caveat would make the capped case indistinguishable
    // from the complete one, which is the whole point of the flag.
    deliveryLog.mockResolvedValue({ items: [delivery()], truncated: false, limit: 100 })
    wrap()

    await waitFor(() => expect(deliveryLog).toHaveBeenCalled())
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
  })
})

describe('a test that reached nobody (FS-487)', () => {
  const pressTest = async () => {
    wrap()
    fireEvent.click(await screen.findByRole('button', { name: /send test/i }))
  }

  it('says nothing was sent when no subscription matched', async () => {
    // The request succeeded and nothing was delivered — which is the one thing pressing
    // Test is meant to find out. "Test dispatched — matched 0 subscriptions" in the same
    // grey as every other outcome reads as "done" to anyone skimming.
    sendTest.mockResolvedValue({ matched: 0, results: [] })
    await pressTest()

    const note = await screen.findByRole('alert')
    expect(note.textContent).toMatch(/nothing was sent/i)
    expect(note.textContent).toMatch(/minimum severity/i)
  })

  it('reports a match as ordinary status, not an alert', async () => {
    // The other direction. Alerting on every test would make the zero case
    // indistinguishable from the working one, which is the defect pointing the other way.
    sendTest.mockResolvedValue({ matched: 2, results: [] })
    await pressTest()

    const note = await screen.findByRole('status')
    expect(note.textContent).toMatch(/matched 2 subscriptions/i)
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('gets the singular right for one match', async () => {
    sendTest.mockResolvedValue({ matched: 1, results: [] })
    await pressTest()

    expect((await screen.findByRole('status')).textContent).toMatch(/matched 1 subscription\./)
  })
})

/**
 * Editing, toggling and testing at the right severity (P11, page-enhancement review).
 *
 * Three gaps the survey found, all downstream of one absent route: there was no PATCH, so
 * a wrong URL or severity meant delete-and-recreate; the `enabled` column the list has
 * always returned could be written once at creation and never again; and Send Test
 * hardcoded `warning`, so a critical-only subscription could never match one and every
 * check of it reported "matched 0" — the FS-487 failure arriving from the test button
 * itself.
 */
describe('editing and toggling a subscription', () => {
  const sub = {
    id: 'sub-1',
    name: 'Ops webhook',
    channel: 'webhook',
    target: 'https://hooks.example.com/a',
    minSeverity: 'critical',
    domain: null,
    assetId: null,
    enabled: true,
  }

  beforeEach(() => {
    listSubscriptions.mockResolvedValue([sub])
    updateSubscription.mockResolvedValue({ ...sub, enabled: false })
  })

  it('disables a subscription without deleting it', async () => {
    // The action an operator most wants mid-incident is "stop paging this channel", and
    // it used to mean destroying the subscription — losing the id every delivery log
    // entry refers to.
    wrap()
    fireEvent.click(await screen.findByRole('button', { name: /disable subscription ops webhook/i }))
    await waitFor(() =>
      expect(updateSubscription).toHaveBeenCalledWith('sub-1', { enabled: false }),
    )
    expect(deleteSubscription).not.toHaveBeenCalled()
  })

  it('edits the target in place and sends only what changed', async () => {
    wrap()
    fireEvent.click(await screen.findByRole('button', { name: /edit subscription ops webhook/i }))
    // Scoped to the row: the CREATE form below has a Target field too, so a bare
    // label lookup is ambiguous — and picking one by index would silently depend on
    // DOM order.
    const row = screen.getByRole('button', { name: /^save$/i }).closest('tr')!
    const targetInput = within(row).getByLabelText('Target')
    fireEvent.change(targetInput, { target: { value: 'https://hooks.example.com/b' } })
    fireEvent.click(within(row).getByRole('button', { name: /^save$/i }))
    await waitFor(() => expect(updateSubscription).toHaveBeenCalled())
    expect(updateSubscription.mock.lastCall?.[1].target).toBe('https://hooks.example.com/b')
  })

  it('says an update that did not happen', async () => {
    updateSubscription.mockRejectedValue(new Error('500'))
    wrap()
    fireEvent.click(await screen.findByRole('button', { name: /disable subscription ops webhook/i }))
    const alerts = await screen.findAllByRole('alert')
    expect(alerts.some((el) => /could not update/i.test(el.textContent ?? ''))).toBe(true)
  })

  it('sends the test at the chosen severity, not always warning', async () => {
    sendTest.mockResolvedValue({ matched: 1, results: [] })
    wrap()
    fireEvent.change(await screen.findByLabelText(/test severity/i), {
      target: { value: 'critical' },
    })
    fireEvent.click(screen.getByRole('button', { name: /send test/i }))
    await waitFor(() => expect(sendTest).toHaveBeenCalledWith({ severity: 'critical' }))
  })

  it('names the severity in the matched-nothing warning', async () => {
    // "no subscription matches a warning-severity test event" was wrong the moment the
    // severity became selectable.
    sendTest.mockResolvedValue({ matched: 0, results: [] })
    wrap()
    fireEvent.change(await screen.findByLabelText(/test severity/i), {
      target: { value: 'critical' },
    })
    fireEvent.click(screen.getByRole('button', { name: /send test/i }))
    expect(await screen.findByText(/critical-severity test event/i)).toBeInTheDocument()
  })
})

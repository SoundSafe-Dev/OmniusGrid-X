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
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const listSubscriptions = vi.fn()
const deliveryLog = vi.fn()
const createSubscription = vi.fn()
const deleteSubscription = vi.fn()
const sendTest = vi.fn()

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
  deliveryLog.mockResolvedValue([delivery()])
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
    expect(await screen.findByText('Failed to load subscriptions.')).toBeInTheDocument()
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
    await screen.findByText('Failed to load subscriptions.')
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
    expect(await screen.findByText('Failed to load the delivery log.')).toBeInTheDocument()
    expect(screen.queryByText('No deliveries yet.')).not.toBeInTheDocument()
  })

  it('keeps the two panels independent', async () => {
    // A dead log must not blank the subscriptions above it, and vice versa.
    deliveryLog.mockRejectedValue(new Error('unreachable'))
    wrap()
    await screen.findByText('Failed to load the delivery log.')
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
    fireEvent.change(screen.getByLabelText(/target/i), {
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
    sendTest.mockResolvedValue({ matched: 0, results: [] })
    wrap()
    await screen.findByText('Ops webhook')
    fireEvent.click(screen.getByRole('button', { name: /send test/i }))
    expect(
      await screen.findByText(/Test dispatched — matched 0 subscriptions\./),
    ).toBeInTheDocument()
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

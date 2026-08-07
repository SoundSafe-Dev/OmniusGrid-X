/**
 * Scheduled export deliveries — the page that exists because nothing did (FS-285).
 *
 * `GET /api/v1/exports/deliveries` has returned a status and an error per send for some
 * time, and no frontend file called it. A scheduled report that failed to go out set
 * `status='failed'` with the reason in `error`, and the person waiting for it had nowhere
 * in the product to learn either fact — or that a send had been attempted at all.
 *
 * The properties here are the ones that make the page worth having rather than decorative:
 * a failure is counted and surfaced rather than buried among successes, the server's own
 * error text survives to the screen, and an empty history is told apart from a history
 * nobody could load.
 */
import { render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const list = vi.fn()
vi.mock('../../api/exportDeliveries', () => ({
  exportDeliveriesApi: { list: (...a: unknown[]) => list(...a) },
}))

const { ExportDeliveries } = await import('./ExportDeliveries')

// Shape read from `ExportDeliveryItem` in `app/api/exports.py` — snake_case, because
// `/api/v1/exports` is not in the transform registry and nothing renames these keys.
const delivery = (over: Record<string, unknown> = {}) => ({
  id: 'del-1',
  schedule_id: 'sch-1',
  status: 'sent',
  filename: 'oee-summary.xlsx',
  error: null,
  scheduled_for: '2026-08-06T06:00:00Z',
  completed_at: '2026-08-06T06:00:12Z',
  ...over,
})

const show = () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <ExportDeliveries />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  list.mockReset()
  list.mockResolvedValue({ items: [delivery()] })
})

describe('a failed send is the point of the page', () => {
  it('counts the failures and says nobody received them', async () => {
    list.mockResolvedValue({
      items: [delivery(), delivery({ id: 'del-2', status: 'failed', error: 'SMTP 550 mailbox unavailable' })],
    })
    show()

    const alert = await screen.findByRole('alert')
    expect(alert.textContent).toMatch(/1 scheduled report failed to send/i)
    expect(alert.textContent).toMatch(/nobody received it/i)
  })

  it('shows the server’s own reason rather than a generic message', async () => {
    // An SMTP rejection and an expired credential need different people. Collapsing them
    // into "delivery failed" throws away the only actionable thing on the page.
    list.mockResolvedValue({
      items: [delivery({ status: 'failed', error: 'SMTP 550 mailbox unavailable' })],
    })
    show()

    expect(await screen.findByText(/SMTP 550 mailbox unavailable/)).toBeInTheDocument()
  })

  it('says so when a failure carries no reason', async () => {
    // `error` is nullable. A blank cell beside a red badge reads as "no problem here".
    list.mockResolvedValue({ items: [delivery({ status: 'failed', error: null })] })
    show()

    expect(await screen.findByText(/no reason recorded/i)).toBeInTheDocument()
  })

  it('lists failures before successes', async () => {
    // A page that showed fifty successful sends and buried one failure below the fold
    // would be the same silence in a longer form.
    list.mockResolvedValue({
      items: [
        delivery({ id: 'ok-1', filename: 'first.xlsx' }),
        delivery({ id: 'bad-1', status: 'failed', filename: 'broken.xlsx', error: 'boom' }),
      ],
    })
    show()

    await screen.findByText('broken.xlsx')
    const rendered = screen.getByRole('table').textContent ?? ''
    expect(rendered.indexOf('broken.xlsx')).toBeLessThan(rendered.indexOf('first.xlsx'))
  })

  it('raises no alarm when everything sent', async () => {
    // The other direction: a banner on every visit would make the real one unreadable.
    show()

    await waitFor(() => expect(screen.getByText('oee-summary.xlsx')).toBeInTheDocument())
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })
})

describe('an empty history is not an unreadable one', () => {
  it('says the load failed, and that a report may still have failed to send', async () => {
    list.mockRejectedValue(new Error('502'))
    show()

    const alert = await screen.findByRole('alert')
    expect(alert.textContent).toMatch(/not an empty one/i)
    expect(screen.queryByText(/no scheduled deliveries have been attempted/i)).not.toBeInTheDocument()
  })

  it('says nothing has been attempted when that is the truth', async () => {
    list.mockResolvedValue({ items: [] })
    show()

    await waitFor(() =>
      expect(screen.getByText(/no scheduled deliveries have been attempted/i)).toBeInTheDocument(),
    )
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })
})

describe('a delivery still in flight is not a completed one', () => {
  it('renders an em dash rather than inventing a completion time', async () => {
    list.mockResolvedValue({
      items: [delivery({ status: 'queued', completed_at: null, filename: null })],
    })
    show()

    await waitFor(() => expect(screen.getByText('queued')).toBeInTheDocument())
    expect(screen.getAllByText('—').length).toBeGreaterThanOrEqual(2)
  })
})

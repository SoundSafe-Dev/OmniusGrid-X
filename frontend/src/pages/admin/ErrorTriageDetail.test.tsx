/**
 * The error-detail page — where a redacted sample either reads as a redaction or as a
 * fact about the error.
 *
 * `error_events` is keyed on `fingerprint` alone, one row per distinct error for the
 * whole platform, so this view is cross-tenant by construction and `require_admin` means
 * a TENANT admin. It therefore handed any tenant's admin any other tenant's
 * `message_sample` and `traceback_sample` — the two fields most likely to carry customer
 * data, precisely because nobody chooses what goes into them. The server now substitutes
 * `[redacted: belongs to another organization]` for a viewer outside the owning org.
 *
 * THE PROPERTY THIS FILE EXISTS FOR. The page must render that placeholder as what it
 * is. It has a separate empty state — "No traceback captured." — and if a redacted
 * sample ever fell into that branch, an operator would read "this error had no traceback"
 * when the truth is "you are not allowed to see it". Those are different statements, and
 * only one of them is true.
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const useErrorDetail = vi.fn()
const mutate = vi.fn()

vi.mock('../../hooks/useErrorTriage', () => ({
  useErrorDetail: (fp: string) => useErrorDetail(fp),
  useUpdateErrorStatus: () => ({ mutate, isPending: false }),
}))
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<Record<string, unknown>>('react-router-dom')
  return { ...actual, useParams: () => ({ fingerprint: 'fp-abc' }) }
})

import { TooltipProvider } from '../../components/ui'
import { ErrorTriageDetail } from './ErrorTriageDetail'

const REDACTED = '[redacted: belongs to another organization]'

const detail = (over: Record<string, unknown> = {}) => ({
  fingerprint: 'fp-abc',
  exception_type: 'ValueError',
  route: '/api/v1/x',
  method: 'GET',
  status_code: 500,
  total_count: 12,
  regression_count: 0,
  status: 'open',
  first_seen: '2026-07-01T00:00:00Z',
  last_seen: '2026-07-28T00:00:00Z',
  message_sample: 'customer_ref=AAA-BB-CCCC failed validation',
  traceback_sample: 'File "handler.py", line 9',
  organization_id: 'org-1',
  status_changed_by: null,
  // Every field the page reads. `count_in_range` and `series` are the ones an
  // incomplete fixture takes down: the page formats them unguarded, so omitting them
  // throws during render and the whole document comes back empty — which reads as a
  // component bug rather than a bad fixture.
  count_in_range: 12,
  series: [{ hour: '2026-07-28T09:00:00Z', count: 3 }],
  ...over,
})

const show = (data: unknown, state: Record<string, unknown> = {}) => {
  useErrorDetail.mockReturnValue({ data, isLoading: false, isError: false, ...state })
  return render(
    <TooltipProvider>
      <MemoryRouter>
        <ErrorTriageDetail />
      </MemoryRouter>
    </TooltipProvider>,
  )
}

beforeEach(() => {
  useErrorDetail.mockReset()
  mutate.mockReset()
})

describe('ErrorTriageDetail', () => {
  it('shows the error the fingerprint identifies', () => {
    show(detail())
    expect(screen.getByText('ValueError')).toBeInTheDocument()
  })

  it('shows the traceback when the viewer owns the error', () => {
    show(detail())
    expect(screen.getByText(/File "handler.py"/)).toBeInTheDocument()
  })

  it('shows a loading state', () => {
    show(undefined, { isLoading: true })
    expect(screen.queryByText('ValueError')).not.toBeInTheDocument()
  })

  it('shows an error state rather than a blank page', () => {
    show(undefined, { isError: true })
    expect(screen.queryByText('ValueError')).not.toBeInTheDocument()
  })
})

describe("ErrorTriageDetail — another tenant's sample", () => {
  it('renders the redaction rather than the empty state', () => {
    // THE ASSERTION THIS FILE EXISTS FOR. "No traceback captured." is a claim about the
    // error; the redaction is a claim about the viewer's permissions. Showing the first
    // where the second is true tells an operator the wrong thing about their system.
    show(detail({ traceback_sample: REDACTED, message_sample: REDACTED }))
    expect(screen.getByText(REDACTED, { exact: false })).toBeInTheDocument()
    expect(screen.queryByText('No traceback captured.')).not.toBeInTheDocument()
  })

  it('still shows the triage data that carries no payload', () => {
    // Redaction must not blind the view it exists to serve: counts, route and status are
    // the reason a cross-tenant triage screen exists at all.
    show(detail({ traceback_sample: REDACTED, message_sample: REDACTED }))
    expect(screen.getByText('ValueError')).toBeInTheDocument()
    expect(screen.getByText(/GET\s+\/api\/v1\/x/)).toBeInTheDocument()
  })

  it('keeps the empty state for an error that genuinely has no traceback', () => {
    // The negative control. Both branches must exist and mean different things.
    show(detail({ traceback_sample: null }))
    expect(screen.getByText('No traceback captured.')).toBeInTheDocument()
  })
})

describe('ErrorTriageDetail — status changes', () => {
  it('sends the new status for this fingerprint', async () => {
    show(detail())
    // An open error offers "acknowledge"; the label is the action, not the status name.
    const button = screen
      .getAllByRole('button')
      .find((b) => /acknowledg/i.test(b.textContent || ''))
    expect(button).toBeTruthy()
    fireEvent.click(button!)
    await waitFor(() =>
      expect(mutate).toHaveBeenCalledWith(
        { fingerprint: 'fp-abc', status: 'acknowledged' },
        expect.anything(),
      ),
    )
  })
})


describe('ErrorTriageDetail — the redaction assertion is not vacuous', () => {
  it('fails to find the redaction when the server did not redact', () => {
    // Pre-fix behaviour: the other tenant's real traceback arrives in full. If the
    // assertion above passed here too, it would be matching something incidental
    // rather than the redacted branch.
    show(detail({ traceback_sample: 'File "handler.py", line 9\n  card="XXXX"' }))
    expect(screen.queryByText(REDACTED, { exact: false })).not.toBeInTheDocument()
    expect(screen.getByText(/card="XXXX"/)).toBeInTheDocument()
  })
})

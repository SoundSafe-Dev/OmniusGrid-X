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

  it('shows a loading skeleton', () => {
    // Asserts the skeleton is PRESENT, not merely that the data is absent. The first
    // version checked only the absence, which is equally true when the component
    // crashes, when the selector is wrong, and when nothing renders at all (rule 21).
    const { container } = show(undefined, { isLoading: true })
    expect(container.querySelector('.animate-pulse')).toBeTruthy()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('names the problem instead of showing a blank page', () => {
    show(undefined, { isError: true })
    const alert = screen.getByRole('alert')
    expect(alert).toBeInTheDocument()
    expect(alert.textContent).toMatch(/unknown or expired fingerprint/i)
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

describe('ErrorTriageDetail — the frame around the redaction (FS-477)', () => {
  // The placeholder inside the block was already right and is asserted above. What sat
  // AROUND it was not: the card promised "Latest occurrence · scrubbed of PII" over a
  // sentence that is neither, and Copy was enabled — the marker is a truthy string, so the
  // clipboard would carry "[redacted: …]" into somebody's bug report as a stack trace.
  //
  // Both read `samples_redacted`, a flag the server derives from the same condition that
  // does the withholding. Matching the marker TEXT would work today and break the day
  // somebody rewords it: prose is not an API.

  it('does not promise a scrubbed sample over a withheld one', () => {
    show(detail({ traceback_sample: REDACTED, samples_redacted: true }))
    expect(screen.queryByText(/scrubbed of PII/i)).not.toBeInTheDocument()
    expect(screen.getByText(/another organisation/i)).toBeInTheDocument()
  })

  it('does not offer to copy a refusal', () => {
    show(detail({ traceback_sample: REDACTED, samples_redacted: true }))
    const copy = screen
      .getAllByRole('button')
      .find((b) => /copy/i.test(b.textContent || ''))
    expect(copy).toBeTruthy()
    expect(copy).toBeDisabled()
  })

  it('still offers to copy a real traceback', () => {
    // The other direction: disabling it unconditionally passes the test above and takes
    // away the button's only purpose.
    show(detail())
    const copy = screen
      .getAllByRole('button')
      .find((b) => /copy/i.test(b.textContent || ''))
    expect(copy).not.toBeDisabled()
    expect(screen.getByText(/scrubbed of PII/i)).toBeInTheDocument()
  })

  it('trusts the flag rather than the wording', () => {
    // If the server improves the marker text, the frame must still say withheld.
    show(detail({ traceback_sample: 'withheld — reworded', samples_redacted: true }))
    expect(screen.getByText(/another organisation/i)).toBeInTheDocument()
  })

  it('treats an older server that sends no flag as not redacted', () => {
    // `samples_redacted` is optional: a deployment running an older API omits it, and the
    // page must not mark every error as withheld.
    const { samples_redacted: _omitted, ...older } = detail({ samples_redacted: false })
    show(older)
    expect(screen.getByText(/scrubbed of PII/i)).toBeInTheDocument()
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

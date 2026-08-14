/**
 * The intake inbox — where a partial reading of a document carries a confident risk score.
 *
 * This page had no test at all, which is what FS-364 records. Writing one found a defect
 * before it asserted anything (FS-478, below), and the properties worth holding are the two
 * this page can get wrong in ways nobody would notice:
 *
 * **A partial analysis must say so** (FS-456). `parse_pdf_structure` caps pages, and caps
 * text within each page. Both caps reach this component. Before FS-456 neither was rendered:
 * a risk score derived from the first 20,000 characters of a 90,000-character page appeared
 * beside one derived from the whole thing, and nothing distinguished them. A confident number
 * over a partial reading is worse than no number, because nothing about it looks partial.
 *
 * **A failed action must reach the operator** (FS-478). `handleUpload` and `handleAnalyze`
 * caught their errors into `console.error` and stopped. The analyse case is the sharper one:
 * the spinner stops and the row stays exactly as it was, which is indistinguishable from an
 * item that had nothing to analyse. The page does not use `useMutation`, so the sweep that
 * covers this class everywhere else could not see it.
 *
 * The load path was already right — a failed list renders "This is a loading failure, not an
 * empty inbox" rather than the empty state — and that is asserted here so it stays right.
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const listIntakeItems = vi.fn()
const analyzeIntake = vi.fn()
const uploadToIntake = vi.fn()
const getIntakeItem = vi.fn()

vi.mock('../../api/nlpCorrelation', () => ({
  nlpCorrelationApi: {
    listIntakeItems: (...a: unknown[]) => listIntakeItems(...a),
    analyzeIntake: (...a: unknown[]) => analyzeIntake(...a),
    uploadToIntake: (...a: unknown[]) => uploadToIntake(...a),
    getIntakeItem: (...a: unknown[]) => getIntakeItem(...a),
  },
}))

const { IntakeInbox } = await import('./IntakeInbox')
const { TooltipProvider } = await import('../../components/ui')

/** The page uses `Tooltip`, which throws outside a provider — the same wrapper
 *  `ErrorTriageDetail.test.tsx` uses. Rendering bare fails with a context error rather
 *  than an assertion, which reads as a component bug rather than a missing wrapper. */
const show = () => render(
  <TooltipProvider>
    <IntakeInbox />
  </TooltipProvider>,
)

const item = (over: Record<string, unknown> = {}) => ({
  id: 'item-1',
  title: 'Q3 maintenance report',
  description: 'quarterly',
  data_type: 'document',
  category: 'maintenance',
  file_name: 'q3.pdf',
  status: 'pending',
  created_at: '2026-08-01T00:00:00Z',
  ...over,
})

/** An analysis result as `POST /nlp/correlation/intake/analyze` returns it. */
const analysis = (over: Record<string, unknown> = {}) => ({
  intake_id: 'item-1',
  analysis: 'Peak risk score 87/100 across 12 sections.',
  risk_score: 87,
  domains_analyzed: ['MAINTENANCE'],
  truncated: false,
  pages_text_truncated: 0,
  text_chars_dropped: 0,
  ...over,
})

beforeEach(() => {
  listIntakeItems.mockReset()
  analyzeIntake.mockReset()
  uploadToIntake.mockReset()
  getIntakeItem.mockReset()
  listIntakeItems.mockResolvedValue({ items: [item()], total: 1 })
})

describe('a partial analysis says so', () => {
  it('warns when text was cut on a page', async () => {
    // The FS-456 case. The document-level `truncated` flag covers only DROPPED PAGES, so a
    // dense page cut in half reports `truncated: false` — and the score beside it is
    // computed from the half that survived.
    analyzeIntake.mockResolvedValue(
      analysis({ pages_text_truncated: 2, text_chars_dropped: 41_000 }),
    )
    show()

    fireEvent.click(await screen.findByRole('button', { name: /analyz/i }))

    await waitFor(() =>
      expect(screen.getByText(/part of the document/i)).toBeInTheDocument(),
    )
    expect(screen.getByText(/text was cut on 2 page/i)).toBeInTheDocument()
    expect(screen.getByText(/41,000 characters dropped/i)).toBeInTheDocument()
  })

  it('warns when whole pages were dropped', async () => {
    analyzeIntake.mockResolvedValue(analysis({ truncated: true }))
    show()

    fireEvent.click(await screen.findByRole('button', { name: /analyz/i }))

    await waitFor(() =>
      expect(screen.getByText(/some pages were not read/i)).toBeInTheDocument(),
    )
  })

  it('says nothing when the whole document was read', async () => {
    // The other direction. A notice on every analysis is a notice nobody reads, and it
    // would make the two cases above indistinguishable from the normal one.
    analyzeIntake.mockResolvedValue(analysis())
    show()

    fireEvent.click(await screen.findByRole('button', { name: /analyz/i }))

    await waitFor(() => expect(screen.getByText(/87.0\/100/)).toBeInTheDocument())
    expect(screen.queryByText(/part of the document/i)).not.toBeInTheDocument()
  })
})

describe('a failed action reaches the operator (FS-478)', () => {
  it('says the analysis did not happen, and names the item', async () => {
    // Before this, the catch reached only the console: the spinner stopped and the row
    // stayed pending, which is exactly what an item with nothing to analyse looks like.
    analyzeIntake.mockRejectedValue(new Error('502'))
    show()

    fireEvent.click(await screen.findByRole('button', { name: /analyz/i }))

    const alert = await screen.findByRole('alert')
    expect(alert.textContent).toMatch(/could not analyse/i)
    expect(alert.textContent).toMatch(/Q3 maintenance report/)
  })

  it('does not claim failure when the analysis succeeded', async () => {
    analyzeIntake.mockResolvedValue(analysis())
    show()

    fireEvent.click(await screen.findByRole('button', { name: /analyz/i }))

    await waitFor(() => expect(screen.getByText(/87.0\/100/)).toBeInTheDocument())
    expect(screen.queryByText(/could not analyse/i)).not.toBeInTheDocument()
  })
})

describe('an empty inbox is not a failed one', () => {
  it('distinguishes them', async () => {
    // Already correct before this file existed — asserted so it stays that way. A failed
    // load rendering "No items in the inbox" tells an operator their queue is clear when
    // the truth is that nobody knows.
    listIntakeItems.mockRejectedValue(new Error('down'))
    show()

    const alert = await screen.findByRole('alert')
    expect(alert.textContent).toMatch(/could not load the inbox/i)
    expect(alert.textContent).toMatch(/not an empty inbox/i)
    expect(screen.queryByText(/No items in the inbox/i)).not.toBeInTheDocument()
  })

  it('shows the empty state when the inbox really is empty', async () => {
    listIntakeItems.mockResolvedValue({ items: [], total: 0 })
    show()

    await waitFor(() =>
      expect(screen.getByText(/No items in the inbox/i)).toBeInTheDocument(),
    )
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })
})


/**
 * The two dead controls (P3, page-enhancement review). The status dropdown wrote state
 * an already-fired request had captured — it APPEARED to filter and did nothing. And
 * "View Results" had no onClick, while the list endpoint never sends `analysis_result`,
 * so for anything analysed before the last reload the dead button was the only path to
 * results only `GET /intake/{id}` carries.
 */
describe('the status filter actually filters', () => {
  it('re-requests with the selected status', async () => {
    show()
    await screen.findByText('Q3 maintenance report')

    fireEvent.change(screen.getByDisplayValue('All Status'), { target: { value: 'analyzed' } })

    await waitFor(() => {
      const lastCall = listIntakeItems.mock.calls[listIntakeItems.mock.calls.length - 1]
      expect(lastCall[2]).toBe('analyzed')
    })
  })

  it('maps All Status back to no filter', async () => {
    show()
    await screen.findByText('Q3 maintenance report')
    fireEvent.change(screen.getByDisplayValue('All Status'), { target: { value: 'analyzed' } })
    await waitFor(() => expect(listIntakeItems).toHaveBeenCalledTimes(2))
    fireEvent.change(screen.getByDisplayValue('Analyzed'), { target: { value: 'all' } })
    await waitFor(() => {
      const lastCall = listIntakeItems.mock.calls[listIntakeItems.mock.calls.length - 1]
      expect(lastCall[2]).toBeUndefined()
    })
  })
})

describe('View Results fetches what the list cannot carry', () => {
  it('loads the detail and renders the analysis inline', async () => {
    listIntakeItems.mockResolvedValue({ items: [item({ status: 'analyzed' })], total: 1 })
    getIntakeItem.mockResolvedValue({
      ...item({ status: 'analyzed' }),
      analysis_result: analysis(),
    })
    show()

    fireEvent.click(await screen.findByRole('button', { name: /view results/i }))

    expect(await screen.findByText(/peak risk score 87/i)).toBeInTheDocument()
    expect(getIntakeItem).toHaveBeenCalledWith('item-1')
  })

  it('reports a failed detail fetch instead of doing nothing', async () => {
    // Doing nothing is exactly what the dead button did; the failure mode must not
    // round-trip back to it.
    listIntakeItems.mockResolvedValue({ items: [item({ status: 'analyzed' })], total: 1 })
    getIntakeItem.mockRejectedValue(new Error('500'))
    show()

    fireEvent.click(await screen.findByRole('button', { name: /view results/i }))

    expect(await screen.findByText(/could not load results/i)).toBeInTheDocument()
  })

  it('does not offer the button for an item whose results are already shown', async () => {
    listIntakeItems.mockResolvedValue({
      items: [item({ status: 'analyzed', analysis_result: analysis() })],
      total: 1,
    })
    show()
    await screen.findByText(/peak risk score 87/i)
    expect(screen.queryByRole('button', { name: /view results/i })).not.toBeInTheDocument()
  })
})

/**
 * Compliance Assistant. The failure modes worth pinning are all "the page renders
 * something reassuring when it should not":
 *
 *   - `answer: null` with citations is a NORMAL response (retrieval up, generator
 *     down or not asked). Rendering it as an error hides passages the reader can
 *     use; rendering it as an empty state is worse — it says the library has
 *     nothing when it has exactly what they asked for.
 *   - A failed query must not read as "no policy covers this". In a compliance
 *     tool that difference is the difference between "you're allowed" and "we
 *     couldn't check", and only one of those is safe to act on.
 *   - An uncited source carries an RRF fusion score, not a cross-encoder one. The
 *     server sends `null` rather than a number on a different scale, and the page
 *     must not coerce it into a percentage — a rendered "0% match" would be a
 *     ranking that does not exist.
 *
 * `vi.spyOn` on the real client, not a module mock: the suite runs with
 * `VITE_USE_MOCK` set globally in test/setup.ts, and replacing the module wholesale
 * would change what is being exercised.
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ComplianceAssistant } from './ComplianceAssistant'
import { ragApi } from '../../api/rag'
import type { RagAnswer } from '../../api/rag'

const wrap = (ui: React.ReactElement) => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>)
}

const answer = (overrides: Partial<RagAnswer> = {}): RagAnswer => ({
  answer: 'Apply a personal lock to each energy isolating device [1].',
  citations: [
    {
      n: 1,
      docId: 'doc-loto',
      filename: 'lockout-tagout-sop.pdf',
      s3Key: 'org-a/doc-loto/lockout-tagout-sop.pdf',
      source: { page: 4, heading: 'Energy Isolation' },
      score: 0.94,
      snippet: 'Each authorized employee shall affix a personal lockout device.',
    },
  ],
  usedContext: true,
  generated: true,
  sources: [
    {
      docId: 'doc-loto',
      filename: 'lockout-tagout-sop.pdf',
      s3Key: 'org-a/doc-loto/lockout-tagout-sop.pdf',
      cited: true,
      score: 0.94,
      isForm: false,
    },
  ],
  ...overrides,
})

const ask = async (question = 'lockout procedure') => {
  fireEvent.change(screen.getByLabelText('Compliance question'), {
    target: { value: question },
  })
  fireEvent.click(screen.getByText('Ask'))
}

afterEach(() => vi.restoreAllMocks())

describe('Compliance Assistant', () => {
  it('renders a grounded answer with its cited passage', async () => {
    vi.spyOn(ragApi, 'query').mockResolvedValue(answer())
    wrap(<ComplianceAssistant />)
    await ask()

    await waitFor(() => expect(screen.getByText('Answer')).toBeInTheDocument())
    expect(screen.getByText(/personal lockout device/)).toBeInTheDocument()
    expect(screen.getAllByText('lockout-tagout-sop.pdf').length).toBeGreaterThan(0)
    expect(screen.getByText(/page 4 · Energy Isolation/)).toBeInTheDocument()
  })

  it('does not ask until there is a question', () => {
    const query = vi.spyOn(ragApi, 'query').mockResolvedValue(answer())
    wrap(<ComplianceAssistant />)
    expect(screen.getByText('Ask')).toBeDisabled()
    expect(query).not.toHaveBeenCalled()
  })

  it('a suggested question asks it', async () => {
    const query = vi.spyOn(ragApi, 'query').mockResolvedValue(answer())
    wrap(<ComplianceAssistant />)
    fireEvent.click(screen.getByText('What do I file to request FMLA leave?'))
    await waitFor(() =>
      expect(query).toHaveBeenCalledWith({ query: 'What do I file to request FMLA leave?' })
    )
  })

  describe('generation unavailable', () => {
    it('shows the passages rather than an error', async () => {
      vi.spyOn(ragApi, 'query').mockResolvedValue(
        answer({ answer: null, generated: false })
      )
      wrap(<ComplianceAssistant />)
      await ask()

      await waitFor(() =>
        expect(screen.getByText(/Answer generation is unavailable/)).toBeInTheDocument()
      )
      // The passage is still there and still openable — that is the point.
      expect(screen.getByText(/personal lockout device/)).toBeInTheDocument()
      expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    })
  })

  describe('failure is not emptiness', () => {
    it('a failed query reads as a failure, not as "no policy covers this"', async () => {
      vi.spyOn(ragApi, 'query').mockRejectedValue(new Error('boom'))
      wrap(<ComplianceAssistant />)
      await ask()

      await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument())
      expect(screen.queryByText('Answer')).not.toBeInTheDocument()
      expect(
        screen.queryByText(/Nothing in your document library matches/)
      ).not.toBeInTheDocument()
    })

    it('names a service outage as an outage', async () => {
      vi.spyOn(ragApi, 'query').mockRejectedValue({
        response: { status: 503, data: { detail: 'Retrieval unavailable' } },
        isAxiosError: true,
      })
      wrap(<ComplianceAssistant />)
      await ask()

      await waitFor(() =>
        expect(screen.getByText(/retrieval services are unavailable/i)).toBeInTheDocument()
      )
      expect(screen.getByText(/not an empty library/i)).toBeInTheDocument()
    })

    it('an empty corpus says so plainly', async () => {
      vi.spyOn(ragApi, 'query').mockResolvedValue({
        answer: "I couldn't find any relevant documents to answer that question.",
        citations: [],
        usedContext: false,
        generated: false,
        sources: [],
      })
      wrap(<ComplianceAssistant />)
      await ask()

      await waitFor(() =>
        expect(
          screen.getByText(/Nothing in your document library matches/)
        ).toBeInTheDocument()
      )
      expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    })
  })

  describe('sources and forms', () => {
    it('groups a form separately and badges it', async () => {
      vi.spyOn(ragApi, 'query').mockResolvedValue(
        answer({
          sources: [
            ...answer().sources,
            {
              docId: 'doc-permit',
              filename: 'energy-isolation-permit.pdf',
              s3Key: 'org-a/doc-permit/energy-isolation-permit.pdf',
              cited: false,
              score: null,
              isForm: true,
            },
          ],
        })
      )
      wrap(<ComplianceAssistant />)
      await ask()

      await waitFor(() =>
        expect(screen.getByText('Forms you may need')).toBeInTheDocument()
      )
      expect(screen.getByText('energy-isolation-permit.pdf')).toBeInTheDocument()
      expect(screen.getByText('Form')).toBeInTheDocument()
    })

    it('lists a document that matched but was not cited, with no score', async () => {
      vi.spyOn(ragApi, 'query').mockResolvedValue(
        answer({
          sources: [
            ...answer().sources,
            {
              docId: 'doc-osha',
              filename: 'osha-1910-147.pdf',
              s3Key: 'org-a/doc-osha/osha-1910-147.pdf',
              cited: false,
              score: null,
              isForm: false,
            },
          ],
        })
      )
      wrap(<ComplianceAssistant />)
      await ask()

      await waitFor(() => expect(screen.getByText('Also relevant')).toBeInTheDocument())
      expect(screen.getByText('osha-1910-147.pdf')).toBeInTheDocument()
      // A null score must not become "0% match".
      expect(screen.queryByText('0% match')).not.toBeInTheDocument()
      expect(screen.getByText('94% match')).toBeInTheDocument()
    })
  })

  describe('opening a document', () => {
    beforeEach(() => {
      vi.stubGlobal('open', vi.fn())
    })

    it('presigns the key and opens the result in a new tab', async () => {
      vi.spyOn(ragApi, 'query').mockResolvedValue(answer())
      const link = vi
        .spyOn(ragApi, 'documentLink')
        .mockResolvedValue({ url: 'https://s3/signed', expiresIn: 3600 })
      wrap(<ComplianceAssistant />)
      await ask()

      await waitFor(() => expect(screen.getAllByText('Open').length).toBeGreaterThan(0))
      fireEvent.click(screen.getAllByText('Open')[0])

      await waitFor(() =>
        expect(link).toHaveBeenCalledWith('org-a/doc-loto/lockout-tagout-sop.pdf')
      )
      await waitFor(() =>
        expect(window.open).toHaveBeenCalledWith(
          'https://s3/signed',
          '_blank',
          'noopener,noreferrer'
        )
      )
    })

    it('offers no Open button for a passage with no stored blob', async () => {
      vi.spyOn(ragApi, 'query').mockResolvedValue(
        answer({
          citations: [{ ...answer().citations[0], s3Key: null }],
          sources: [{ ...answer().sources[0], s3Key: null }],
        })
      )
      wrap(<ComplianceAssistant />)
      await ask()

      await waitFor(() => expect(screen.getByText('Answer')).toBeInTheDocument())
      expect(screen.queryByText('Open')).not.toBeInTheDocument()
    })

    it('a failed link is visible, not swallowed', async () => {
      vi.spyOn(ragApi, 'query').mockResolvedValue(answer())
      vi.spyOn(ragApi, 'documentLink').mockRejectedValue({
        response: { status: 403, data: { detail: 'Document is not in your organization.' } },
        isAxiosError: true,
      })
      wrap(<ComplianceAssistant />)
      await ask()

      await waitFor(() => expect(screen.getAllByText('Open').length).toBeGreaterThan(0))
      fireEvent.click(screen.getAllByText('Open')[0])

      await waitFor(() =>
        expect(screen.getByText(/Couldn’t open that document/)).toBeInTheDocument()
      )
      expect(window.open).not.toHaveBeenCalled()
    })
  })

  describe('the response contract', () => {
    it('never surfaces operational records, because the API never sends them', async () => {
      /**
       * The ERP leg is prompt-side only: it shapes the answer and appears in no
       * field of the response. This asserts the PAGE has no path that would show
       * it — the backend half is pinned in tests/test_rag_erp_context.py.
       */
      vi.spyOn(ragApi, 'query').mockResolvedValue(answer())
      wrap(<ComplianceAssistant />)
      await ask()

      await waitFor(() => expect(screen.getByText('Answer')).toBeInTheDocument())
      expect(screen.queryByText(/Operational records/i)).not.toBeInTheDocument()
      expect(screen.queryByText(/WorkOrder \|/)).not.toBeInTheDocument()
    })
  })
})

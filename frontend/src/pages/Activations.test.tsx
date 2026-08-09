import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { beforeEach, describe, expect, it, vi } from 'vitest'

// The worklist for everything activated from a correlation session (FS-425). Before this
// page, `GET /insights/activations` was served by no screen: an operator could see an
// activation only inline, in the message that created it, in that session. "What did we
// commit to and what is still outstanding" had no answer in the product.
//
// These assert the properties that make it a worklist rather than a log — it opens on the
// outstanding ones, it shows what each still needs, and a failed load does not read as an
// empty list.

const list = vi.fn()
const confirm = vi.fn()
const reject = vi.fn()
const acknowledgePosting = vi.fn()

vi.mock('../api/insightActivation', async () => {
  const actual = await vi.importActual<typeof import('../api/insightActivation')>(
    '../api/insightActivation',
  )
  return {
    ...actual,
    insightActivationApi: {
      list: (...a: unknown[]) => list(...a),
      confirm: (...a: unknown[]) => confirm(...a),
      reject: (...a: unknown[]) => reject(...a),
      acknowledgePosting: (...a: unknown[]) => acknowledgePosting(...a),
    },
  }
})

import Activations from './Activations'

const manualPosting = {
  id: 'p1',
  targetSystem: 'purchasing',
  status: 'manual_required',
  externalRef: null,
  instruction: 'Tell the stores clerk to raise a requisition for BRG-6204.',
  acknowledgedAt: null,
  postedAt: null,
  lastError: null,
}

const activation = (over: Record<string, unknown> = {}) => ({
  id: 'act-1',
  title: 'Schedule preventive maintenance on the spindle bearing',
  description: null,
  domain: 'MAINTENANCE',
  priority: 'high',
  source: 'analysis_session',
  sessionId: 's1',
  messageId: 'm1',
  actionIndex: 0,
  status: 'issued',
  issuedAt: '2026-08-04T09:00:00Z',
  confirmedAt: null,
  rejectedAt: null,
  rejectionReason: null,
  task: { id: 't1', title: 'x', taskType: 'maintenance_pm', status: 'ready', priority: 'high', boardId: 'b', columnId: 'c' },
  taskBlockedReason: null,
  postings: [manualPosting],
  readyToConfirm: false,
  blockers: [{ kind: 'task', reason: 'the Kanban task is ready, not completed' }],
  awaitingAPerson: [{ target: 'purchasing', instruction: manualPosting.instruction, postingId: 'p1' }],
  validation: null,
  alreadyExisted: false,
  ...over,
})

const page = (rows = [activation()]) => {
  list.mockResolvedValue({ items: rows, total: rows.length, limit: 100, truncated: false })
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <Activations />
    </QueryClientProvider>,
  )
}

beforeEach(() => vi.clearAllMocks())

describe('the worklist', () => {
  it('opens on the outstanding ones, not on everything', async () => {
    page()
    await screen.findByText(/spindle bearing/)
    // A list where the finished outnumber the outstanding stops being read.
    expect(list).toHaveBeenCalledWith(expect.objectContaining({ status: 'issued' }))
  })

  it('shows what each activation still needs', async () => {
    page()
    expect(await screen.findByText('purchasing')).toBeInTheDocument()
    expect(screen.getByText('needs a person')).toBeInTheDocument()
    expect(screen.getByText(manualPosting.instruction)).toBeInTheDocument()
    expect(screen.getByText(/1 thing outstanding/)).toBeInTheDocument()
  })

  it('does not read as empty when the load fails', async () => {
    list.mockRejectedValue(new Error('boom'))
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(
      <QueryClientProvider client={qc}>
        <Activations />
      </QueryClientProvider>,
    )
    // The FS-62 shape: an empty list after a failed request reads as "nothing outstanding",
    // which is the opposite of what happened.
    expect(await screen.findByRole('alert')).toHaveTextContent(/loading failure, not an empty worklist/i)
  })

  it('says so when there is genuinely nothing', async () => {
    page([])
    expect(await screen.findByText(/Nothing outstanding/)).toBeInTheDocument()
  })
})

describe('acting on one', () => {
  it('shows the blockers the server refused a confirm with', async () => {
    confirm.mockRejectedValue({
      response: {
        data: {
          error: {
            details: {
              detail: {
                message: 'cannot be confirmed yet',
                blockers: [{ kind: 'task', reason: 'the Kanban task is ready, not completed' }],
              },
            },
          },
        },
      },
    })
    page()
    fireEvent.click(await screen.findByRole('button', { name: /confirm done/i }))

    // Not "could not confirm" — the reason, which is the only actionable part.
    expect(await screen.findByText(/Not confirmed yet/)).toBeInTheDocument()
    expect(screen.getAllByText(/the Kanban task is ready, not completed/).length).toBeGreaterThan(0)
  })

  it('passes the reference through when a person clears a manual posting', async () => {
    acknowledgePosting.mockResolvedValue(activation())
    page()
    const input = await screen.findByLabelText(/Reference for purchasing/i)
    fireEvent.change(input, { target: { value: 'REQ-4471' } })
    fireEvent.click(screen.getByRole('button', { name: /i told them/i }))

    await waitFor(() => expect(acknowledgePosting).toHaveBeenCalledWith('act-1', 'p1', 'REQ-4471'))
  })

  it('requires a reason before declining', async () => {
    page()
    fireEvent.click(await screen.findByRole('button', { name: /^decline$/i }))
    expect(screen.getByRole('button', { name: /^decline$/i })).toBeDisabled()
    expect(reject).not.toHaveBeenCalled()
  })

  it('reports a failed acknowledgement instead of leaving the row looking cleared', async () => {
    acknowledgePosting.mockRejectedValue(new Error('nope'))
    page()
    fireEvent.click(await screen.findByRole('button', { name: /i told them/i }))
    expect(await screen.findByText(/still needs passing on/i)).toBeInTheDocument()
  })
})

describe('a confirmed activation', () => {
  it('claims evidence only once the server says so', async () => {
    page([activation({ status: 'confirmed', readyToConfirm: false, blockers: [], postings: [
      { ...manualPosting, status: 'posted', externalRef: 'REQ-4471', postedAt: '2026-08-04T10:00:00Z' },
    ] })])
    expect(await screen.findByText(/every system of record above carries evidence/i)).toBeInTheDocument()
    expect(screen.getByText('REQ-4471')).toBeInTheDocument()
  })
})

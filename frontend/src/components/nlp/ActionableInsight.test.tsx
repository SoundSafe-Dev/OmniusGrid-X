import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi, beforeEach } from 'vitest'

// A recommended action used to render as a bullet with a GREEN TICK and no control (FS-406).
// The tick was the defect: it read as "done" for work that had not been started and could
// not be started from the pane at all. These lock in the replacement — that the row offers a
// real verb, that nothing is drawn as complete without evidence, and that when the server
// refuses to confirm, the operator is shown which system is still outstanding rather than a
// bare failure.

const activate = vi.fn()
const confirm = vi.fn()
const acknowledgePosting = vi.fn()
const reject = vi.fn()
const get = vi.fn()

vi.mock('../../api/insightActivation', async () => {
  const actual = await vi.importActual<typeof import('../../api/insightActivation')>(
    '../../api/insightActivation',
  )
  return {
    ...actual,
    insightActivationApi: {
      activate: (...args: unknown[]) => activate(...args),
      confirm: (...args: unknown[]) => confirm(...args),
      acknowledgePosting: (...args: unknown[]) => acknowledgePosting(...args),
      reject: (...args: unknown[]) => reject(...args),
      get: (...args: unknown[]) => get(...args),
    },
  }
})

import { ActionableInsight } from './ActionableInsight'

const ACTION = { description: 'Schedule preventive maintenance on the spindle bearing' }

const manualPosting = {
  id: 'p1',
  targetSystem: 'maintenance',
  status: 'manual_required',
  externalRef: null,
  instruction: 'Tell the maintenance planner to book a 2h window on Mill #1 before Friday.',
  acknowledgedAt: null,
  postedAt: null,
  lastError: null,
}

const issued = {
  id: 'act-1',
  title: ACTION.description,
  description: null,
  domain: 'MAINTENANCE',
  priority: 'high',
  source: 'analysis_session',
  sessionId: 's1',
  messageId: 'm1',
  actionIndex: 0,
  status: 'issued',
  issuedAt: '2026-08-03T10:00:00Z',
  confirmedAt: null,
  rejectedAt: null,
  rejectionReason: null,
  task: {
    id: 't1',
    title: ACTION.description,
    taskType: 'maintenance_pm',
    status: 'ready',
    priority: 'high',
    boardId: 'b1',
    columnId: 'c1',
  },
  taskBlockedReason: null,
  postings: [manualPosting],
  readyToConfirm: false,
  blockers: [{ kind: 'task', reason: 'the Kanban task is ready, not completed' }],
  awaitingAPerson: [
    { target: 'maintenance', instruction: manualPosting.instruction, postingId: 'p1' },
  ],
  validation: null,
  alreadyExisted: false,
}

const renderInsight = (props = {}) =>
  render(
    <ul>
      <ActionableInsight action={ACTION} index={0} sessionId="s1" messageId="m1" {...props} />
    </ul>,
  )

beforeEach(() => {
  vi.clearAllMocks()
  activate.mockResolvedValue(issued)
})

describe('before activation', () => {
  it('offers a control instead of drawing the action as already done', () => {
    const { container } = renderInsight()

    expect(screen.getByRole('button', { name: /activate/i })).toBeInTheDocument()
    // The old bullet used lucide's CheckCircle. Nothing may claim completion here.
    expect(container.querySelector('.text-green-600')).toBeNull()
    expect(container.querySelector('.text-green-500')).toBeNull()
  })

  it('sends the session, message and index so the server can make it idempotent', async () => {
    renderInsight()
    fireEvent.click(screen.getByRole('button', { name: /activate/i }))

    await waitFor(() => expect(activate).toHaveBeenCalled())
    expect(activate).toHaveBeenCalledWith(
      expect.objectContaining({ sessionId: 's1', messageId: 'm1', actionIndex: 0 }),
    )
  })

  it('reports a failure instead of leaving the row looking activated', async () => {
    activate.mockRejectedValue({
      response: { data: { error: { details: { detail: { message: 'the ERP rejected it' } } } } },
    })
    renderInsight()
    fireEvent.click(screen.getByRole('button', { name: /activate/i }))

    expect(await screen.findByText('the ERP rejected it')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /activate/i })).toBeInTheDocument()
  })
})

describe('after activation', () => {
  it('shows each system of record separately rather than one success', async () => {
    renderInsight()
    fireEvent.click(screen.getByRole('button', { name: /activate/i }))

    expect(await screen.findByText('maintenance')).toBeInTheDocument()
    expect(screen.getByText('needs a person')).toBeInTheDocument()
    expect(screen.getByText(/maintenance_pm/)).toBeInTheDocument()
  })

  it('puts the analog instruction on screen where a supervisor can read it out', async () => {
    renderInsight()
    fireEvent.click(screen.getByRole('button', { name: /activate/i }))

    expect(await screen.findByText(manualPosting.instruction)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /i told them/i })).toBeInTheDocument()
  })

  it('says why no board task exists rather than silently showing none', async () => {
    activate.mockResolvedValue({
      ...issued,
      task: null,
      taskBlockedReason: 'this organisation has no active task board',
    })
    renderInsight()
    fireEvent.click(screen.getByRole('button', { name: /activate/i }))

    expect(
      await screen.findByText(/no active task board/i),
    ).toBeInTheDocument()
  })

  it('does not narrate a second dispatch when the server matched an existing activation', async () => {
    activate.mockResolvedValue({ ...issued, alreadyExisted: true })
    renderInsight()
    fireEvent.click(screen.getByRole('button', { name: /activate/i }))

    expect(await screen.findByText(/did not dispatch it a second time/i)).toBeInTheDocument()
  })
})

describe('confirmation', () => {
  it('shows the blockers the server refused with, not just a failure', async () => {
    confirm.mockRejectedValue({
      response: {
        data: {
          error: {
            details: {
              detail: {
                message: 'this activation cannot be confirmed yet',
                blockers: [
                  {
                    kind: 'posting',
                    target: 'maintenance',
                    reason: 'maintenance has no integration and nobody has confirmed the manual step yet',
                  },
                ],
              },
            },
          },
        },
      },
    })
    get.mockResolvedValue(issued)

    renderInsight()
    fireEvent.click(screen.getByRole('button', { name: /activate/i }))
    fireEvent.click(await screen.findByRole('button', { name: /confirm done/i }))

    expect(
      await screen.findByText(/nobody has confirmed the manual step yet/i),
    ).toBeInTheDocument()
  })

  it('only claims the systems carry evidence once the server confirms', async () => {
    confirm.mockResolvedValue({
      ...issued,
      status: 'confirmed',
      confirmedAt: '2026-08-03T11:00:00Z',
      readyToConfirm: false,
      blockers: [],
      awaitingAPerson: [],
      postings: [
        { ...manualPosting, status: 'posted', externalRef: 'WO-9912', postedAt: '2026-08-03T11:00:00Z' },
      ],
      validation: { postings: [{ target: 'maintenance', evidence: 'external_reference' }] },
    })

    renderInsight()
    fireEvent.click(screen.getByRole('button', { name: /activate/i }))
    fireEvent.click(await screen.findByRole('button', { name: /confirm done/i }))

    expect(await screen.findByText(/every system of record above carries evidence/i)).toBeInTheDocument()
    // And the reference is shown, because it is the evidence a reader can check.
    expect(screen.getByText('WO-9912')).toBeInTheDocument()
  })
})

describe('the analog handover', () => {
  it('passes the reference through so the posting can become posted', async () => {
    acknowledgePosting.mockResolvedValue({
      ...issued,
      postings: [
        { ...manualPosting, status: 'posted', externalRef: 'REQ-4471', postedAt: '2026-08-03T11:00:00Z' },
      ],
      awaitingAPerson: [],
    })

    renderInsight()
    fireEvent.click(screen.getByRole('button', { name: /activate/i }))
    const input = await screen.findByPlaceholderText(/reference they gave you/i)
    fireEvent.change(input, { target: { value: 'REQ-4471' } })
    fireEvent.click(screen.getByRole('button', { name: /i told them/i }))

    await waitFor(() => expect(acknowledgePosting).toHaveBeenCalledWith('act-1', 'p1', 'REQ-4471'))
    expect(await screen.findByText('REQ-4471')).toBeInTheDocument()
  })

  it('keeps "I told them" distinct from "the system has a record"', async () => {
    acknowledgePosting.mockResolvedValue({
      ...issued,
      postings: [
        { ...manualPosting, acknowledgedAt: '2026-08-03T11:00:00Z' },
      ],
    })

    renderInsight()
    fireEvent.click(screen.getByRole('button', { name: /activate/i }))
    fireEvent.click(await screen.findByRole('button', { name: /i told them/i }))

    // No external reference was given, so the posting is NOT presented as posted.
    await waitFor(() => expect(acknowledgePosting).toHaveBeenCalledWith('act-1', 'p1', undefined))
    expect(await screen.findByText(/confirmed by a person/i)).toBeInTheDocument()
  })
})

describe('declining', () => {
  it('requires a reason before it will send one', async () => {
    renderInsight()
    fireEvent.click(screen.getByRole('button', { name: /activate/i }))
    fireEvent.click(await screen.findByRole('button', { name: /^decline$/i }))

    const declineButton = screen.getByRole('button', { name: /^decline$/i })
    expect(declineButton).toBeDisabled()
    expect(reject).not.toHaveBeenCalled()
  })

  it('sends the reason and shows the action as declined', async () => {
    reject.mockResolvedValue({
      ...issued,
      status: 'rejected',
      rejectionReason: 'the bearing was replaced last week',
    })

    renderInsight()
    fireEvent.click(screen.getByRole('button', { name: /activate/i }))
    fireEvent.click(await screen.findByRole('button', { name: /^decline$/i }))
    fireEvent.change(screen.getByPlaceholderText(/why not/i), {
      target: { value: 'the bearing was replaced last week' },
    })
    fireEvent.click(screen.getByRole('button', { name: /^decline$/i }))

    await waitFor(() =>
      expect(reject).toHaveBeenCalledWith('act-1', 'the bearing was replaced last week'),
    )
    expect(await screen.findByText(/Declined: the bearing was replaced last week/)).toBeInTheDocument()
  })
})

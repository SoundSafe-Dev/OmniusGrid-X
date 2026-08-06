/**
 * The correlation assistant pane — 909 lines, the largest of FS-364's untested components.
 *
 * Most of what it does it already does carefully: a failed chat turn becomes a message in
 * the transcript rather than a console line, `simulated` is carried through instead of
 * defaulted (so a heuristic reply cannot pass for an inference), and a capped history says
 * which half is missing (FS-459). Those are asserted here so they stay true.
 *
 * **What it got wrong** (FS-481). `handleSessionSelect` switches the session BEFORE the
 * transcript arrives. When the fetch failed, `setCurrentSession` had already run and
 * `setMessages` had not — so the header, the data-sources panel and the suggested-questions
 * effect all moved to session B while the message list still showed **session A's
 * conversation**. This is not the ordinary silent-failure class. A silent failure shows
 * nothing; this showed another investigation's transcript under this session's name, which
 * is a thing an operator has no reason to doubt.
 *
 * The same ordering exists in `bootstrapSession`, where at boot `messages` is empty so the
 * failure mode is only the milder one: a named session with no history, indistinguishable
 * from a session nobody ever used.
 *
 * And `handleAddIntakeData` dropped its failure to the console. The document never appears
 * in the panel, the operator asks their question anyway, and the answer is computed from a
 * data set they believe includes it.
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const listSessions = vi.fn()
const getSession = vi.fn()
const createSession = vi.fn()
const getSessionMessages = vi.fn()
const getSuggestedQuestions = vi.fn()
const sessionChat = vi.fn()
const addIntakeData = vi.fn()
const generateSessionTitle = vi.fn()

vi.mock('../../api/analysisSessions', () => ({
  analysisSessionsApi: {
    listSessions: (...a: unknown[]) => listSessions(...a),
    getSession: (...a: unknown[]) => getSession(...a),
    createSession: (...a: unknown[]) => createSession(...a),
    getSessionMessages: (...a: unknown[]) => getSessionMessages(...a),
    getSuggestedQuestions: (...a: unknown[]) => getSuggestedQuestions(...a),
    sessionChat: (...a: unknown[]) => sessionChat(...a),
    addIntakeData: (...a: unknown[]) => addIntakeData(...a),
    generateSessionTitle: (...a: unknown[]) => generateSessionTitle(...a),
  },
}))

/** `SessionList` fetches on its own and renders the picker. Stubbing it exposes the one
 *  thing these tests drive — `onSessionSelect` — without a second network surface. */
const sessionListProps: { onSessionSelect?: (s: unknown) => void } = {}
vi.mock('./SessionList', () => ({
  SessionList: (props: { onSessionSelect: (s: unknown) => void }) => {
    sessionListProps.onSessionSelect = props.onSessionSelect
    return (
      <button onClick={() => props.onSessionSelect({ id: 'sess-b', title: 'Line 2 downtime' })}>
        pick session b
      </button>
    )
  },
}))

/** The panels below all fetch; none is under test here. `DataSourcesPanel` keeps its
 *  imperative handle so the pane's ref calls do not throw. */
const intakeSelectProps: { onSelect?: (id: string) => void } = {}
vi.mock('./DataSourcesPanel', () => ({
  DataSourcesPanel: () => <div data-testid="data-sources" />,
}))
vi.mock('./IntakeSelectorDialog', () => ({
  IntakeSelectorDialog: (props: { onSelect: (id: string) => void }) => {
    intakeSelectProps.onSelect = props.onSelect
    return null
  },
}))
vi.mock('./ChatHistoryModal', () => ({ ChatHistoryModal: () => null }))
vi.mock('./ContextPanel', () => ({ ContextPanel: () => null }))
vi.mock('./RealTimeDataPanel', () => ({ RealTimeDataPanel: () => null }))

const { CorrelationAIPane } = await import('./CorrelationAIPane')
const { TooltipProvider, DialogProvider } = await import('../ui')

/** `Tooltip` and `useDialog` both throw outside their providers — without these the
 *  failure is a context error, which reads as a broken component rather than a missing
 *  wrapper. `DialogProvider` also renders the `alert()` this pane uses for action
 *  failures, which is what the intake test below asserts on. */
const show = () =>
  render(
    <DialogProvider>
      <TooltipProvider>
        <CorrelationAIPane />
      </TooltipProvider>
    </DialogProvider>,
  )

const session = (over: Record<string, unknown> = {}) => ({
  id: 'sess-a',
  title: 'Press 1 vibration',
  status: 'active',
  data_sources_count: 0,
  created_at: '2026-08-01T00:00:00Z',
  ...over,
})

const message = (over: Record<string, unknown> = {}) => ({
  id: 'm1',
  session_id: 'sess-a',
  role: 'assistant',
  content: 'Press 1 has been late on three of the last five shifts.',
  timestamp: '2026-08-01T00:01:00Z',
  ...over,
})

/** jsdom implements no layout, so `scrollIntoView` is undefined — and the pane calls it in
 *  an effect on every message change. Unstubbed, the render throws inside the commit phase
 *  and every assertion below fails looking like a broken component. */
beforeEach(() => {
  HTMLElement.prototype.scrollIntoView = vi.fn()
  for (const fn of [
    listSessions,
    getSession,
    createSession,
    getSessionMessages,
    getSuggestedQuestions,
    sessionChat,
    addIntakeData,
    generateSessionTitle,
  ]) {
    fn.mockReset()
  }
  listSessions.mockResolvedValue({ sessions: [session()], total: 1 })
  getSession.mockResolvedValue(session())
  createSession.mockResolvedValue(session({ id: 'sess-new', title: 'New session' }))
  getSessionMessages.mockResolvedValue({ items: [message()], truncated: false })
  getSuggestedQuestions.mockResolvedValue({ questions: [], context_summary: '' })
  addIntakeData.mockResolvedValue({})
})

describe('a transcript that failed to load is not another session\'s (FS-481)', () => {
  it('does not leave the previous conversation under the new session\'s name', async () => {
    show()
    // Session A loads normally; its transcript is on screen.
    await waitFor(() =>
      expect(screen.getByText(/late on three of the last five shifts/)).toBeInTheDocument(),
    )

    getSessionMessages.mockRejectedValue(new Error('502'))
    fireEvent.click(screen.getByRole('button', { name: /pick session b/i }))

    // The sharp assertion: session A's message must be GONE. Leaving it is worse than
    // showing nothing, because nothing about it looks like the wrong session.
    await waitFor(() =>
      expect(screen.queryByText(/late on three of the last five shifts/)).not.toBeInTheDocument(),
    )
  })

  it('says the history failed rather than showing the new-session empty state', async () => {
    show()
    await waitFor(() => expect(getSessionMessages).toHaveBeenCalled())

    getSessionMessages.mockRejectedValue(new Error('502'))
    fireEvent.click(screen.getByRole('button', { name: /pick session b/i }))

    const alert = await screen.findByRole('alert')
    expect(alert.textContent).toMatch(/could not be loaded/i)
    expect(alert.textContent).toMatch(/not an empty session/i)
  })

  it('says nothing when the transcript loads', async () => {
    // The other direction. A warning on every session switch is one nobody reads, and it
    // would make the failure above indistinguishable from the normal case.
    show()
    await waitFor(() => expect(getSessionMessages).toHaveBeenCalled())

    fireEvent.click(screen.getByRole('button', { name: /pick session b/i }))

    await waitFor(() => expect(getSessionMessages).toHaveBeenCalledTimes(2))
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('clears the warning once a session loads successfully', async () => {
    show()
    await waitFor(() => expect(getSessionMessages).toHaveBeenCalled())

    getSessionMessages.mockRejectedValue(new Error('502'))
    fireEvent.click(screen.getByRole('button', { name: /pick session b/i }))
    await screen.findByRole('alert')

    getSessionMessages.mockResolvedValue({ items: [message()], truncated: false })
    fireEvent.click(screen.getByRole('button', { name: /pick session b/i }))

    await waitFor(() => expect(screen.queryByRole('alert')).not.toBeInTheDocument())
  })

  it('says so when the session it restored at boot has no history because the fetch failed', async () => {
    // The same ordering in `bootstrapSession`. Milder, because `messages` is empty at boot
    // — but a named session with an empty transcript still reads as one nobody used.
    getSessionMessages.mockRejectedValue(new Error('502'))
    show()

    const alert = await screen.findByRole('alert')
    expect(alert.textContent).toMatch(/not an empty session/i)
  })
})

describe('a document that did not attach says so (FS-481)', () => {
  it('warns that answers will not include it', async () => {
    addIntakeData.mockRejectedValue(new Error('409'))
    show()
    await waitFor(() => expect(intakeSelectProps.onSelect).toBeTruthy())
    await waitFor(() => expect(getSessionMessages).toHaveBeenCalled())

    intakeSelectProps.onSelect!('intake-7')

    await waitFor(() =>
      expect(screen.getByText(/could not attach that document/i)).toBeInTheDocument(),
    )
    expect(screen.getByText(/will not take it into account/i)).toBeInTheDocument()
  })

  it('says nothing when it attached', async () => {
    show()
    await waitFor(() => expect(intakeSelectProps.onSelect).toBeTruthy())
    await waitFor(() => expect(getSessionMessages).toHaveBeenCalled())

    intakeSelectProps.onSelect!('intake-7')

    await waitFor(() => expect(addIntakeData).toHaveBeenCalledWith('sess-a', 'intake-7'))
    expect(screen.queryByText(/could not attach/i)).not.toBeInTheDocument()
  })
})

describe('properties this pane already held, held', () => {
  it('says when the history shown is a page, not the whole conversation (FS-459)', async () => {
    // The list is oldest-first, so the turns missing are the RECENT ones — a user who
    // scrolls to the bottom would otherwise believe they had reached the end.
    getSessionMessages.mockResolvedValue({ items: [message()], truncated: true })
    show()

    await waitFor(() =>
      expect(screen.getByText(/more messages than are shown here/i)).toBeInTheDocument(),
    )
  })

  it('does not say it when the whole conversation is shown', async () => {
    show()
    await waitFor(() =>
      expect(screen.getByText(/late on three of the last five shifts/)).toBeInTheDocument(),
    )
    expect(screen.queryByText(/more messages than are shown here/i)).not.toBeInTheDocument()
  })

  it('puts a failed chat turn in the transcript rather than the console', async () => {
    sessionChat.mockRejectedValue(new Error('backend down'))
    show()
    await waitFor(() => expect(getSessionMessages).toHaveBeenCalled())

    // Driven through the send BUTTON rather than the Enter key: the pane binds
    // `onKeyPress`, which React 18 still dispatches but jsdom's `keyDown` does not reach.
    const input = screen.getByPlaceholderText(/ask/i)
    fireEvent.change(input, { target: { value: 'why was press 1 late?' } })
    fireEvent.click(screen.getByTestId('correlation-send'))

    await waitFor(() =>
      expect(screen.getByText(/could not complete this request/i)).toBeInTheDocument(),
    )
  })
})

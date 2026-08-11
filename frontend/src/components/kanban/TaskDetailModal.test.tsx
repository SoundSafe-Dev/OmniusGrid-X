/**
 * The task detail modal (FS-651) — 604 lines, the largest of the kanban stubs.
 *
 * It carries nine mutations (assign, unassign, approve, reject, start, complete, move, save,
 * delete) and until this test they were all `try { … } finally { … }` with no catch, over a
 * store whose task mutations RE-RAISE (`kanbanStore.tsx:314-316,330-332`; move, approve,
 * start and complete do not catch at all). So a refused approval threw into an onClick
 * handler, reset the spinner, and changed nothing on screen. On the routes that close the
 * modal (approve, complete, delete) the failure at least left it open; on the ones that do
 * not — start, move, assign — a rejection and a success were pixel-identical.
 *
 * The assign dropdown's three-state chain was already correct and is pinned here so the next
 * edit cannot collapse it back to "No users available" on a failed fetch.
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const store = {
  updateTask: vi.fn(),
  approveTask: vi.fn(),
  startTask: vi.fn(),
  completeTask: vi.fn(),
  deleteTask: vi.fn(),
  moveTask: vi.fn(),
}
const promptDialog = vi.fn()
const apiGet = vi.fn()

vi.mock('../../stores/kanbanStore', () => ({ useKanban: () => store }))
vi.mock('../../api/client', () => ({ api: { get: (...a: unknown[]) => apiGet(...a) } }))
// `useDialog` arrives through the `../ui` barrel, which also carries `Button` — so the real
// module is spread back in rather than replaced, or every button in the modal disappears.
vi.mock('../ui', async () => ({
  ...(await vi.importActual<Record<string, unknown>>('../ui')),
  useDialog: () => ({ prompt: promptDialog }),
}))

import { TaskDetailModal } from './TaskDetailModal'

const TASK = {
  id: 't-1',
  title: 'Replace the seal',
  description: 'Line 3 filler',
  task_type: 'maintenance_pm',
  priority: 'high',
  status: 'in_progress',
  column_id: 'col-a',
  position: 0,
  time_logged_minutes: 90,
}

const COLUMNS = [
  { id: 'col-a', name: 'Doing' },
  { id: 'col-b', name: 'Done' },
] as never

const show = (task: Record<string, unknown> = {}) => {
  const onClose = vi.fn()
  render(
    <TaskDetailModal
      isOpen
      onClose={onClose}
      task={{ ...TASK, ...task } as never}
      columns={COLUMNS}
    />,
  )
  return { onClose }
}

beforeEach(() => {
  vi.clearAllMocks()
  apiGet.mockResolvedValue({
    data: { items: [{ id: 'u-1', full_name: 'Ada Lovelace', email: 'a@x' }] },
  })
  Object.values(store).forEach((fn) => fn.mockResolvedValue(undefined))
  vi.spyOn(console, 'error').mockImplementation(() => {})
})

describe('what it shows', () => {
  it('renders nothing when there is no task', () => {
    render(<TaskDetailModal isOpen onClose={vi.fn()} task={null as never} columns={COLUMNS} />)
    expect(screen.queryByText('Replace the seal')).toBeNull()
  })

  it('shows the title, the type label and the logged time', async () => {
    show()
    expect(await screen.findByText('Replace the seal')).toBeInTheDocument()
    expect(screen.getByText('Preventive Maintenance')).toBeInTheDocument()
    expect(screen.getByText('1h 30m')).toBeInTheDocument()
  })

  it('offers approve and reject only while approval is pending', async () => {
    show({ approval_status: 'pending' })
    expect(await screen.findByRole('button', { name: 'Approve' })).toBeInTheDocument()
  })

  it('does not offer them once the task is approved', async () => {
    show({ approval_status: 'approved' })
    await screen.findByText('Replace the seal')
    expect(screen.queryByRole('button', { name: 'Approve' })).toBeNull()
  })
})

describe('a mutation that fails', () => {
  // THE FINDING. The store re-raises; the handlers caught nothing.
  it('says so when completing fails, and does not close', async () => {
    store.completeTask.mockRejectedValue(new Error('409'))
    const { onClose } = show()
    fireEvent.click(await screen.findByRole('button', { name: /complete/i }))
    expect(await screen.findByRole('alert')).toHaveTextContent(/could not complete this task/i)
    expect(onClose).not.toHaveBeenCalled()
  })

  it('says so when a move fails — the case with no other visible signal', async () => {
    // `handleMove` never closed the modal and never changed anything the user could see,
    // so a rejected move was indistinguishable from a successful one.
    store.moveTask.mockRejectedValue(new Error('403'))
    show()
    fireEvent.change(await screen.findByRole('combobox'), { target: { value: 'col-b' } })
    expect(await screen.findByRole('alert')).toHaveTextContent(/could not move this task/i)
  })

  it('says so when a delete fails, and keeps the confirmation open', async () => {
    store.deleteTask.mockRejectedValue(new Error('500'))
    const { onClose } = show()
    fireEvent.click(await screen.findByRole('button', { name: 'Delete' }))
    fireEvent.click(screen.getAllByRole('button', { name: 'Delete' })[1])
    expect(await screen.findByRole('alert')).toHaveTextContent(/could not delete this task/i)
    expect(onClose).not.toHaveBeenCalled()
  })

  it('says so when an approval fails', async () => {
    store.approveTask.mockRejectedValue(new Error('403'))
    show({ approval_status: 'pending' })
    fireEvent.click(await screen.findByRole('button', { name: 'Approve' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(/could not approve this task/i)
  })

  it('leaves the controls usable so the action can be retried', async () => {
    store.completeTask.mockRejectedValue(new Error('409'))
    show()
    fireEvent.click(await screen.findByRole('button', { name: /complete/i }))
    await screen.findByRole('alert')
    await waitFor(() =>
      expect(screen.getByRole('button', { name: /complete/i })).not.toBeDisabled(),
    )
  })

  it('clears the message when the next attempt is made', async () => {
    store.completeTask.mockRejectedValueOnce(new Error('409')).mockResolvedValue(undefined)
    const { onClose } = show()
    fireEvent.click(await screen.findByRole('button', { name: /complete/i }))
    await screen.findByRole('alert')
    fireEvent.click(screen.getByRole('button', { name: /complete/i }))
    await waitFor(() => expect(onClose).toHaveBeenCalled())
    expect(screen.queryByRole('alert')).toBeNull()
  })
})

describe('a mutation that succeeds', () => {
  it('completes and closes', async () => {
    const { onClose } = show()
    fireEvent.click(await screen.findByRole('button', { name: /complete/i }))
    await waitFor(() => expect(onClose).toHaveBeenCalled())
    expect(store.completeTask).toHaveBeenCalledWith('t-1')
  })

  it('moves to the column the operator picked', async () => {
    show()
    fireEvent.change(await screen.findByRole('combobox'), { target: { value: 'col-b' } })
    await waitFor(() => expect(store.moveTask).toHaveBeenCalledWith('t-1', 'col-b'))
    expect(screen.queryByRole('alert')).toBeNull()
  })

  it('saves the edited title', async () => {
    show()
    fireEvent.click(await screen.findByRole('button', { name: 'Edit' }))
    fireEvent.change(screen.getByDisplayValue('Replace the seal'), {
      target: { value: 'Replace both seals' },
    })
    fireEvent.click(screen.getByRole('button', { name: /save changes/i }))
    await waitFor(() =>
      expect(store.updateTask).toHaveBeenCalledWith('t-1', { title: 'Replace both seals' }),
    )
  })
})

describe('rejecting needs a reason', () => {
  it('does not call the server when the prompt is dismissed', async () => {
    promptDialog.mockResolvedValue(null)
    show({ approval_status: 'pending' })
    fireEvent.click(await screen.findByRole('button', { name: 'Reject' }))
    await waitFor(() => expect(promptDialog).toHaveBeenCalled())
    expect(store.approveTask).not.toHaveBeenCalled()
  })

  it('sends the reason it was given', async () => {
    promptDialog.mockResolvedValue('Wrong line')
    show({ approval_status: 'pending' })
    fireEvent.click(await screen.findByRole('button', { name: 'Reject' }))
    await waitFor(() =>
      expect(store.approveTask).toHaveBeenCalledWith('t-1', 'reject', 'Wrong line'),
    )
  })
})

describe('the assignee dropdown keeps its three states apart', () => {
  it('offers the users it loaded', async () => {
    show()
    fireEvent.click(await screen.findByRole('button', { name: /unassigned/i }))
    expect(await screen.findByText('Ada Lovelace')).toBeInTheDocument()
  })

  it('says the load failed rather than showing an empty organisation', async () => {
    // "No users available" on a failed fetch reads as a company with nobody in it, and the
    // operator stops trying to assign instead of retrying.
    apiGet.mockRejectedValue(new Error('offline'))
    show()
    fireEvent.click(await screen.findByRole('button', { name: /unassigned/i }))
    expect(await screen.findByText(/could not load users/i)).toBeInTheDocument()
  })

  it('says "no users" only when the server really returned none', async () => {
    apiGet.mockResolvedValue({ data: { items: [] } })
    show()
    fireEvent.click(await screen.findByRole('button', { name: /unassigned/i }))
    expect(await screen.findByText(/no users available/i)).toBeInTheDocument()
  })

  it('assigns the user that was clicked', async () => {
    show()
    fireEvent.click(await screen.findByRole('button', { name: /unassigned/i }))
    fireEvent.click(await screen.findByText('Ada Lovelace'))
    await waitFor(() =>
      expect(store.updateTask).toHaveBeenCalledWith('t-1', { assigned_to: 'u-1' }),
    )
  })

  it('sends an explicit null to unassign', async () => {
    // A missing key would leave the assignment in place; the API needs the null.
    show({ assigned_to: 'u-1' })
    fireEvent.click(await screen.findByRole('button', { name: /ada lovelace/i }))
    fireEvent.click(await screen.findByRole('button', { name: 'Unassign' }))
    await waitFor(() => expect(store.updateTask).toHaveBeenCalledWith('t-1', { assigned_to: null }))
  })
})

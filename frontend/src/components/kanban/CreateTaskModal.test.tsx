/**
 * The create-task modal (FS-651).
 *
 * 216 lines, previously a `() => null` stub. The store's `createTask` answers **null** on
 * failure and logs to the console — so before this the modal simply stopped spinning and sat
 * there with the form still filled. A refused create and a slow one looked identical, and the
 * only sensible thing a user can do with that is press the button again.
 *
 * `mutationFailureIsVisible` sweeps `useMutation` hooks and cannot see this one: it is a
 * hand-rolled async call. The class is the same and the sweep's scope is a hypothesis
 * (rule 62) — which is why the test is here rather than in the sweep.
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

const createTask = vi.fn()
vi.mock('../../stores/kanbanStore', () => ({ useKanban: () => ({ createTask }) }))

import { CreateTaskModal } from './CreateTaskModal'

const show = (over: Record<string, unknown> = {}) => {
  const onClose = vi.fn()
  render(
    <CreateTaskModal
      isOpen
      onClose={onClose}
      boardId="b-1"
      defaultColumnId="col-a"
      {...(over as Record<string, never>)}
    />,
  )
  return { onClose }
}

const submit = () => fireEvent.submit(document.querySelector('form')!)

describe('the guard before the write', () => {
  it('renders nothing when closed', () => {
    show({ isOpen: false })
    expect(document.querySelector('form')).toBeNull()
  })

  it('does not call the server without a title', async () => {
    // The submit button is enabled, so the guard is the only thing stopping an empty task
    // being created — and an untitled card on a board is a card nobody can action.
    show()
    submit()
    await new Promise((r) => setTimeout(r, 0))
    expect(createTask).not.toHaveBeenCalled()
  })
})

describe('a successful create', () => {
  it('sends the typed title and closes', async () => {
    createTask.mockResolvedValue({ id: 't-9' })
    const { onClose } = show()
    await userEvent.type(screen.getByLabelText(/title/i), 'Replace the seal')
    submit()
    await waitFor(() => expect(onClose).toHaveBeenCalled())
    expect(createTask).toHaveBeenCalledWith(
      expect.objectContaining({ title: 'Replace the seal', board_id: 'b-1', column_id: 'col-a' }),
    )
  })
})

describe('a refused create', () => {
  it('says so, rather than leaving the form sitting there', async () => {
    // THE FINDING. `createTask` returns null and logs to the console; the modal used to
    // show nothing at all, so the user could not tell a rejection from a slow network.
    createTask.mockResolvedValue(null)
    show()
    await userEvent.type(screen.getByLabelText(/title/i), 'Replace the seal')
    submit()
    expect(await screen.findByRole('alert')).toHaveTextContent(/was not created/i)
  })

  it('keeps the modal open and the form filled', async () => {
    // Closing on a failed write is the worse half of the same bug: the user believes the
    // task exists and has to retype it when they find it does not.
    createTask.mockResolvedValue(null)
    const { onClose } = show()
    await userEvent.type(screen.getByLabelText(/title/i), 'Replace the seal')
    submit()
    await screen.findByRole('alert')
    expect(onClose).not.toHaveBeenCalled()
    expect(screen.getByLabelText(/title/i)).toHaveValue('Replace the seal')
  })

  it('re-enables the button so the user can retry', async () => {
    // The `finally` is what makes this true. Without it one refused create disables the
    // form for the life of the modal.
    createTask.mockResolvedValue(null)
    show()
    await userEvent.type(screen.getByLabelText(/title/i), 'Replace the seal')
    submit()
    await screen.findByRole('alert')
    // `getByRole` matches two — the heading is also rendered as a button — so this asks
    // for the submit control specifically.
    await waitFor(() =>
      expect(document.querySelector('button[type="submit"]')).not.toBeDisabled(),
    )
  })

  it('clears a previous error when the user tries again', async () => {
    // A stale error beside a successful create is the same lie in reverse.
    createTask.mockResolvedValueOnce(null).mockResolvedValue({ id: 't-9' })
    const { onClose } = show()
    await userEvent.type(screen.getByLabelText(/title/i), 'Replace the seal')
    submit()
    await screen.findByRole('alert')
    submit()
    await waitFor(() => expect(onClose).toHaveBeenCalled())
  })
})

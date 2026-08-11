/**
 * The promise-based dialog primitives (FS-652).
 *
 * 181 lines, no test, and **load-bearing since 2026-08-08**: the admin Users page was moved
 * off `window.confirm` onto this, so a deactivation now depends on it resolving correctly.
 * A confirm that resolves `true` when the operator pressed Cancel deactivates a user nobody
 * asked to deactivate — which is exactly the class of failure the native dialogs were
 * replaced to avoid, and the replacement had never been exercised.
 *
 * The native ones are worth replacing for a reason this file also pins: `window.confirm`
 * blocks the event loop and is suppressed outright in some embedded/webview contexts, so a
 * destructive action guarded by it can proceed with no prompt at all.
 */
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { DialogProvider, useDialog } from './DialogProvider'

function Harness({ onResult }: { onResult: (v: unknown) => void }) {
  const { confirm, alert } = useDialog()
  return (
    <>
      <button onClick={async () => onResult(await confirm({ title: 'Deactivate this user?', destructive: true }))}>
        ask
      </button>
      <button onClick={async () => { await alert({ title: 'It failed', message: 'Insufficient rights' }); onResult('alerted') }}>
        tell
      </button>
    </>
  )
}

const show = (onResult: (v: unknown) => void) =>
  render(<DialogProvider><Harness onResult={onResult} /></DialogProvider>)

describe('confirm', () => {
  it('resolves true when confirmed', async () => {
    const onResult = vi.fn()
    show(onResult)
    await userEvent.click(screen.getByRole('button', { name: 'ask' }))
    await screen.findByText('Deactivate this user?')
    await userEvent.click(screen.getByRole('button', { name: /confirm|deactivate|ok|yes/i }))
    await waitFor(() => expect(onResult).toHaveBeenCalledWith(true))
  })

  it('resolves FALSE when cancelled, which is the whole point', async () => {
    // A confirm that resolves truthy on cancel deactivates a user nobody asked to
    // deactivate. `window.confirm` cannot get this wrong; a hand-rolled promise can.
    const onResult = vi.fn()
    show(onResult)
    await userEvent.click(screen.getByRole('button', { name: 'ask' }))
    await screen.findByText('Deactivate this user?')
    await userEvent.click(screen.getByRole('button', { name: /cancel|no/i }))
    await waitFor(() => expect(onResult).toHaveBeenCalledWith(false))
  })

  it('closes after answering, so the next call is not answered by the last dialog', async () => {
    const onResult = vi.fn()
    show(onResult)
    await userEvent.click(screen.getByRole('button', { name: 'ask' }))
    await userEvent.click(await screen.findByRole('button', { name: /cancel|no/i }))
    await waitFor(() => expect(screen.queryByText('Deactivate this user?')).not.toBeInTheDocument())
  })
})

describe('alert', () => {
  it('resolves once dismissed, so an awaiting caller continues', async () => {
    // `await alert(...)` is used to sequence a message before the caller moves on. If the
    // promise never settles the caller hangs silently — no error, no screen change.
    const onResult = vi.fn()
    show(onResult)
    await userEvent.click(screen.getByRole('button', { name: 'tell' }))
    await screen.findByText('It failed')
    await userEvent.click(screen.getByRole('button', { name: /ok|close|dismiss/i }))
    await waitFor(() => expect(onResult).toHaveBeenCalledWith('alerted'))
  })

  it('shows the message, not just the title', async () => {
    // The title says something went wrong; the MESSAGE says why, and it is where the
    // server's reason is carried. A dialog that renders only the title tells an admin
    // that a write failed and nothing about whether retrying is worth it.
    show(vi.fn())
    await userEvent.click(screen.getByRole('button', { name: 'tell' }))
    expect(await screen.findByText(/Insufficient rights/)).toBeInTheDocument()
  })
})

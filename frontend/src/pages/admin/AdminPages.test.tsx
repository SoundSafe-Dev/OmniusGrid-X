import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { axe } from 'jest-axe'
import { describe, expect, it, vi, beforeEach } from 'vitest'

import { UsersPage } from './AdminPages'

// This page shipped with its write affordances HIDDEN behind
// USER_MGMT_ENABLED = false, because create/update/delete pointed at
// /api/v1/auth/users routes that never existed. FS-221 added the real admin
// router and FS-224 enabled the UI, so the things worth locking in are:
//
//  * the buttons are actually visible now (a regression to `false` would silently
//    remove the whole surface again);
//  * the client sends the SERVER's field names — the form carries `name`, the API
//    wants `full_name`, and a straight pass-through 422s;
//  * update sends only what changed, so editing a name cannot flip is_active;
//  * the destructive confirm describes DEACTIVATION, which is what the server does.

const getUsers = vi.fn()
const createUser = vi.fn()
const updateUser = vi.fn()
const deleteUser = vi.fn()

vi.mock('../../api', () => ({
  authApi: {
    getUsers: (params: unknown) => getUsers(params),
    createUser: (d: unknown) => createUser(d),
    updateUser: (id: string, d: unknown) => updateUser(id, d),
    deleteUser: (id: string) => deleteUser(id),
  },
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}))

const confirmMock = vi.fn()
const alertMock = vi.fn()

vi.mock('../../components/ui', async () => {
  const actual = await vi.importActual<Record<string, unknown>>('../../components/ui')
  return {
    ...actual,
    Tooltip: ({ children }: any) => <>{children}</>,
    TooltipTrigger: ({ children }: any) => children,
    TooltipContent: () => null,
    useDialog: () => ({ confirm: confirmMock, alert: alertMock }),
  }
})

const USER = {
  id: 'u-1',
  name: 'Dana Operator',
  email: 'dana@test.local',
  role: 'operator',
  isActive: true,
}

function page(items: unknown[] = [USER], total = items.length) {
  getUsers.mockResolvedValue({ items, total, skip: 0, limit: 50, hasMore: total > items.length })
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <UsersPage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  confirmMock.mockResolvedValue(true)
  createUser.mockResolvedValue(USER)
  updateUser.mockResolvedValue(USER)
  deleteUser.mockResolvedValue(undefined)
})

describe('UsersPage', () => {
  it('renders users and no longer hides the write affordances', async () => {
    page()
    expect(await screen.findByText('Dana Operator')).toBeInTheDocument()

    // The flag being true is the whole point of FS-224.
    expect(screen.getByRole('button', { name: /add user/i })).toBeInTheDocument()
    // And the "provisioned on the backend" explanation must be gone.
    expect(
      screen.queryByText(/self-serve create\/edit\/delete isn't available/i),
    ).not.toBeInTheDocument()
  })

  it('shows an empty state rather than a blank table', async () => {
    page([])
    expect(await screen.findByText(/no users found/i)).toBeInTheDocument()
  })

  it('confirms with DEACTIVATION wording, not deletion', async () => {
    page()
    await screen.findByText('Dana Operator')

    // Targeted by accessible name — the icon-only buttons had none until this
    // sprint, which is what made a positional lookup the only option.
    await userEvent.click(
      screen.getByRole('button', { name: 'Deactivate Dana Operator' }),
    )

    await waitFor(() => expect(confirmMock).toHaveBeenCalled())
    const opts = confirmMock.mock.calls[0][0]
    expect(opts.destructive).toBe(true)
    // The server keeps the row, so promising irreversibility was simply untrue.
    expect(opts.title).toMatch(/deactivat/i)
    expect(opts.message).not.toMatch(/cannot be undone/i)
    await waitFor(() => expect(deleteUser).toHaveBeenCalledWith('u-1'))
  })

  it('does not deactivate when the admin cancels', async () => {
    confirmMock.mockResolvedValue(false)
    page()
    await screen.findByText('Dana Operator')
    await userEvent.click(
      screen.getByRole('button', { name: 'Deactivate Dana Operator' }),
    )
    await waitFor(() => expect(confirmMock).toHaveBeenCalled())
    expect(deleteUser).not.toHaveBeenCalled()
  })

  it('has no detectable accessibility violations', async () => {
    const { container } = page()
    await screen.findByText('Dana Operator')
    const results = await axe(container)
    expect(results).toHaveNoViolations()
  })
})

// The list endpoint used to return the whole organisation: it declared no query
// parameters, so the `{ skip, limit }` this client has always sent were dropped
// silently by FastAPI. The handler now paginates for real, which means this page can
// no longer assume one request is the whole list — and a table that shows the first
// page with no indication of the rest is the same silent truncation wearing a
// different hat.
describe('UsersPage — a failed write does not pass for a successful one', () => {
  // FOUND BY THE MUTATION SWEEP. All three user mutations had `onSuccess` and no
  // `onError`, so a rejected request left the modal open (create/update) or the row
  // exactly where it was (deactivate) and said nothing at all.
  //
  // Deactivate is the one that matters. "Row still there" is precisely what a SUCCESSFUL
  // deactivation looks like until the list refetches — the server keeps the row — so
  // there was nothing to notice, and an admin who believes they revoked someone's access
  // and did not has a security problem they cannot see.
  //
  // The idiom was already in this file: `alert` from useDialog is used for the
  // missing-field checks. Only the failures skipped it.

  it('tells the admin when a deactivation did not happen', async () => {
    deleteUser.mockRejectedValue({ response: { data: { detail: 'Insufficient rights' } } })
    page()
    await screen.findByText('Dana Operator')
    await userEvent.click(
      screen.getByRole('button', { name: 'Deactivate Dana Operator' }),
    )
    await waitFor(() => expect(alertMock).toHaveBeenCalled())
    const opts = alertMock.mock.calls[0][0]
    expect(opts.title).toMatch(/could not remove the user/i)
    // The reason has to reach the screen: "it failed" and "you are not allowed to do
    // this" send an admin to different places.
    expect(opts.message).toMatch(/Insufficient rights/)
  })

  it('says the access is unchanged rather than leaving it ambiguous', async () => {
    deleteUser.mockRejectedValue(new Error('unreachable'))
    page()
    await screen.findByText('Dana Operator')
    await userEvent.click(
      screen.getByRole('button', { name: 'Deactivate Dana Operator' }),
    )
    await waitFor(() => expect(alertMock).toHaveBeenCalled())
    const opts = alertMock.mock.calls[0][0]
    expect(`${opts.title} ${opts.message}`).toMatch(/access is unchanged|Nothing has been changed/i)
    // And the row is still listed, which is the state the message now explains.
    expect(screen.getByText('Dana Operator')).toBeInTheDocument()
  })

  it('says nothing when the deactivation succeeds', async () => {
    // The positive control. Without it, "an alert appears on failure" is satisfied by a
    // page that alerts on every deactivation, which is noise dressed as safety.
    page()
    await screen.findByText('Dana Operator')
    await userEvent.click(
      screen.getByRole('button', { name: 'Deactivate Dana Operator' }),
    )
    await waitFor(() => expect(deleteUser).toHaveBeenCalledWith('u-1'))
    expect(alertMock).not.toHaveBeenCalled()
  })

  it('tells the admin when a user could not be created', async () => {
    // The modal simply stayed open with the form still filled — feedback of a sort, but
    // a slow network reads identically to a rejected payload.
    createUser.mockRejectedValue({ response: { data: { detail: 'Email already in use' } } })
    page()
    await screen.findByText('Dana Operator')
    await userEvent.click(screen.getByRole('button', { name: /add user/i }))
    // The form label is "Name"; the API field is `full_name`. Asserting on the label
    // the page actually renders, not on the wire name.
    await userEvent.type(screen.getByLabelText(/^name$/i), 'New Person')
    await userEvent.type(screen.getByLabelText(/email/i), 'new@test.local')
    await userEvent.type(screen.getByLabelText(/password/i), 'hunter2hunter2')
    await userEvent.click(screen.getByRole('button', { name: /^create user$/i }))
    await waitFor(() => expect(alertMock).toHaveBeenCalled())
    // Index arithmetic, not `.at(-1)`: this project's TS lib target predates it, and
    // the same slip already cost a run earlier in this sweep.
    const calls = alertMock.mock.calls
    expect(calls[calls.length - 1][0].message).toMatch(/Email already in use/)
  })
})

describe('UsersPage pagination', () => {
  beforeEach(() => {
    getUsers.mockReset()
    confirmMock.mockReset()
  })

  it('asks for an explicit page size rather than taking the server default', async () => {
    page()
    await screen.findByText('Dana Operator')
    expect(getUsers).toHaveBeenCalledWith(expect.objectContaining({ limit: 50 }))
  })

  it('says how many users are hidden when the org exceeds a page', async () => {
    page([USER], 120)
    expect(await screen.findByText(/Showing 1 of 120 users/)).toBeInTheDocument()
  })

  it('shows nothing about paging when the org fits on one page', async () => {
    page([USER])
    await screen.findByText('Dana Operator')
    expect(screen.queryByRole('button', { name: 'Show more' })).not.toBeInTheDocument()
    expect(screen.queryByText(/Showing 1 of/)).not.toBeInTheDocument()
  })

  it('requests a larger page when the admin asks for more', async () => {
    page([USER], 120)
    await screen.findByRole('button', { name: 'Show more' })
    await userEvent.click(screen.getByRole('button', { name: 'Show more' }))
    await waitFor(() =>
      expect(getUsers).toHaveBeenCalledWith(expect.objectContaining({ limit: 100 })),
    )
  })

  it('states the server ceiling instead of ending the list quietly', async () => {
    // The handler rejects limit > 200, so "Show more" cannot keep going forever. What
    // it must not do is stop offering more while saying nothing.
    page([USER], 500)
    await screen.findByRole('button', { name: 'Show more' })
    for (let i = 0; i < 3; i++) {
      await userEvent.click(screen.getByRole('button', { name: 'Show more' }))
    }
    await waitFor(() =>
      expect(getUsers).toHaveBeenCalledWith(expect.objectContaining({ limit: 200 })),
    )
    expect(await screen.findByText(/Showing the first 200/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Show more' })).not.toBeInTheDocument()
  })
})

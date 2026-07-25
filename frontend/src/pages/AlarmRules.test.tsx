import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { axe } from 'jest-axe'
import { describe, expect, it, vi, beforeEach } from 'vitest'

import AlarmRules from './AlarmRules'
import { AlarmRule } from '../types'

// What these tests protect:
//
// * PATCH semantics on the enable/disable toggle. Sending the whole form there
//   would overwrite whatever another operator changed in the meantime, and
//   sending defaults for omitted fields would silently reset a rule's threshold.
//   So the toggle must send ONLY `isEnabled`.
// * That deleting goes through the accessible confirm dialog rather than a native
//   `window.confirm` (suppressed in embedded webviews, so a destructive action
//   would proceed unconfirmed).
// * Loading / empty / error states, because an operator seeing a blank page
//   cannot tell "no rules configured" from "the request failed".

const list = vi.fn()
const create = vi.fn()
const update = vi.fn()
const remove = vi.fn()

vi.mock('../api/alarmRules', () => ({
  alarmRulesApi: {
    list: (f: unknown) => list(f),
    create: (p: unknown) => create(p),
    update: (id: string, p: unknown) => update(id, p),
    remove: (id: string) => remove(id),
  },
}))

const confirmMock = vi.fn()
const alertMock = vi.fn()

vi.mock('../components/ui', async () => {
  const { forwardRef } = await import('react')
  return {
    Button: ({ children, ...rest }: any) => <button {...rest}>{children}</button>,
    Input: forwardRef(({ label, helperText, ...rest }: any, ref: any) => (
      <label>
        {label}
        <input ref={ref} aria-label={label} {...rest} />
      </label>
    )),
    Select: forwardRef(({ label, options, placeholder, ...rest }: any, ref: any) => (
      <label>
        {label}
        <select ref={ref} aria-label={label} {...rest}>
          {placeholder && <option value="">{placeholder}</option>}
          {options?.map((o: any) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
      </label>
    )),
    Modal: ({ isOpen, title, children }: any) =>
      isOpen ? (
        <div role="dialog" aria-label={title}>
          {children}
        </div>
      ) : null,
    useDialog: () => ({ confirm: confirmMock, alert: alertMock }),
  }
})

const RULE: AlarmRule = {
  id: 'rule-1',
  organizationId: 'org-1',
  name: 'Spindle temperature critical',
  description: 'Bearing temperature above the ISO limit',
  metricName: 'temperature',
  comparator: 'gt',
  threshold: 80,
  durationSeconds: 300,
  hysteresis: 2,
  severity: 'critical',
  alarmCode: 'TEMP_HIGH',
  messageTemplate: null,
  assetId: null,
  assetTypeId: null,
  workcellId: null,
  isEnabled: true,
  createdBy: null,
  createdAt: '2026-07-01T00:00:00Z',
  updatedAt: '2026-07-01T00:00:00Z',
}

function page(items: AlarmRule[] = [RULE]) {
  list.mockResolvedValue({
    items,
    total: items.length,
    skip: 0,
    limit: 100,
    hasMore: false,
  })
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <AlarmRules />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  confirmMock.mockResolvedValue(true)
  update.mockResolvedValue(RULE)
  create.mockResolvedValue(RULE)
  remove.mockResolvedValue(undefined)
})

describe('AlarmRules', () => {
  it('renders a rule with its condition and duration in words', async () => {
    page()
    expect(await screen.findByText('Spindle temperature critical')).toBeInTheDocument()
    // The condition has to be readable at a glance — "temperature > 80 for 5m",
    // not a comparator enum the operator has to decode.
    expect(screen.getByText(/temperature > 80/)).toBeInTheDocument()
    expect(screen.getByText(/for 5m/)).toBeInTheDocument()
    expect(screen.getByText('critical')).toBeInTheDocument()
  })

  it('shows a loading state', () => {
    list.mockReturnValue(new Promise(() => {}))
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter>
          <AlarmRules />
        </MemoryRouter>
      </QueryClientProvider>,
    )
    expect(screen.getByRole('status')).toHaveTextContent(/loading/i)
  })

  it('distinguishes an empty list from a failure', async () => {
    page([])
    const empty = await screen.findByText('No alarm rules yet')
    expect(empty).toBeInTheDocument()
    // The empty state must say what the consequence is, not just "no data".
    expect(screen.getByText(/only appear when an edge agent decides/i)).toBeInTheDocument()
  })

  it('shows an error state when the request fails', async () => {
    list.mockRejectedValue(new Error('boom'))
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter>
          <AlarmRules />
        </MemoryRouter>
      </QueryClientProvider>,
    )
    expect(await screen.findByRole('alert')).toHaveTextContent(/could not load/i)
  })

  it('sends ONLY isEnabled when toggling, not the whole rule', async () => {
    page()
    const toggle = await screen.findByRole('button', { name: 'Enabled' })
    await userEvent.click(toggle)

    await waitFor(() => expect(update).toHaveBeenCalled())
    const [id, payload] = update.mock.calls[0]
    expect(id).toBe('rule-1')
    // The precise assertion is the point: a fuller payload would clobber
    // concurrent edits and could reset fields the operator never touched.
    expect(payload).toEqual({ isEnabled: false })
  })

  it('creates a rule from the form', async () => {
    page()
    await userEvent.click(await screen.findByRole('button', { name: /new rule/i }))

    const dialog = await screen.findByRole('dialog')
    expect(dialog).toBeInTheDocument()

    await userEvent.type(screen.getByLabelText('Name'), 'Coolant low')
    await userEvent.type(screen.getByLabelText('Metric'), 'pressure')
    await userEvent.type(screen.getByLabelText('Alarm code'), 'PRESSURE_LOW')
    await userEvent.click(screen.getByRole('button', { name: /create rule/i }))

    await waitFor(() => expect(create).toHaveBeenCalled())
    expect(create.mock.calls[0][0]).toMatchObject({
      name: 'Coolant low',
      metricName: 'pressure',
      alarmCode: 'PRESSURE_LOW',
    })
  })

  it('refuses to submit an incomplete rule and says which field', async () => {
    page()
    await userEvent.click(await screen.findByRole('button', { name: /new rule/i }))
    await userEvent.click(screen.getByRole('button', { name: /create rule/i }))

    expect(await screen.findByRole('alert')).toHaveTextContent(/name is required/i)
    expect(create).not.toHaveBeenCalled()
  })

  it('deletes only after the accessible confirm dialog is accepted', async () => {
    page()
    await userEvent.click(
      await screen.findByRole('button', { name: 'Delete Spindle temperature critical' }),
    )

    await waitFor(() => expect(confirmMock).toHaveBeenCalled())
    expect(confirmMock.mock.calls[0][0]).toMatchObject({ destructive: true })
    await waitFor(() => expect(remove).toHaveBeenCalledWith('rule-1'))
  })

  it('does not delete when the operator cancels', async () => {
    confirmMock.mockResolvedValue(false)
    page()
    await userEvent.click(
      await screen.findByRole('button', { name: 'Delete Spindle temperature critical' }),
    )
    await waitFor(() => expect(confirmMock).toHaveBeenCalled())
    expect(remove).not.toHaveBeenCalled()
  })

  it('has no detectable accessibility violations', async () => {
    const { container } = page()
    await screen.findByText('Spindle temperature critical')
    const results = await axe(container)
    expect(results).toHaveNoViolations()
  })
})

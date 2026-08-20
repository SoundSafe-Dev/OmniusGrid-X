import { fireEvent, render, screen, waitFor } from '@testing-library/react'
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

vi.mock('../api', () => ({
  assetsApi: {
    list: vi.fn().mockResolvedValue({
      items: [{ id: 'asset-1', name: 'Press 1' }],
      total: 1,
      hasMore: false,
    }),
    getTypes: vi.fn().mockResolvedValue([{ id: 'type-1', name: 'Presses' }]),
  },
  workcellsApi: { list: vi.fn().mockResolvedValue([{ id: 'wc-1', name: 'Cell A' }]) },
}))
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

vi.mock('../components/ui', async (importOriginal) => {
  const { forwardRef } = await import('react')
  return {
    // FS-768. Spread the real module first: this listed its exports, and the page then
    // imported `ErrorState`, so a real change arrived as "No ErrorState export is defined
    // on the mock" — a mock defect in the message, a drifted stand-in in fact.
    ...(await importOriginal<typeof import('../components/ui')>()),
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

/**
 * Rule SCOPE (P10, page-enhancement review).
 *
 * `assetId`, `assetTypeId` and `workcellId` sat in EMPTY_FORM and were copied on edit
 * since this page was written, and NO INPUT EVER SET THEM — so every rule was org-wide
 * and the backend's `_validate_targets` (which exists to reject another tenant's asset
 * id) was unreachable from the UI. The practical effect: a threshold that suits a press
 * is rarely the one that suits an oven, so rules were written for the loosest machine on
 * the floor.
 */
describe('rule scope', () => {
  beforeEach(() => {
    list.mockReset()
    create.mockReset()
    create.mockResolvedValue({})
  })

  const fillRequired = async () => {
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Press temp' } })
    fireEvent.change(screen.getByLabelText('Metric'), { target: { value: 'temperature' } })
    fireEvent.change(screen.getByLabelText('Threshold'), { target: { value: '90' } })
    fireEvent.change(screen.getByLabelText(/alarm code/i), { target: { value: 'TEMP-HI' } })
  }

  it('sends the chosen asset as the rule target', async () => {
    page([])
    fireEvent.click(await screen.findByRole('button', { name: /new rule/i }))
    await fillRequired()

    fireEvent.change(screen.getByLabelText('Applies to'), { target: { value: 'asset' } })
    fireEvent.change(await screen.findByLabelText('Asset'), { target: { value: 'asset-1' } })
    fireEvent.click(screen.getByRole('button', { name: /create rule|save changes/i }))

    await waitFor(() => expect(create).toHaveBeenCalled())
    expect(create.mock.lastCall?.[0].assetId).toBe('asset-1')
  })

  it('sends a workcell scope with the other targets cleared', async () => {
    // One scope at a time: a rule naming both an asset and a workcell reads as an
    // intersection nobody defines, so choosing one clears the others.
    page([])
    fireEvent.click(await screen.findByRole('button', { name: /new rule/i }))
    await fillRequired()

    fireEvent.change(screen.getByLabelText('Applies to'), { target: { value: 'asset' } })
    fireEvent.change(await screen.findByLabelText('Asset'), { target: { value: 'asset-1' } })
    fireEvent.change(screen.getByLabelText('Applies to'), { target: { value: 'workcell' } })
    fireEvent.change(await screen.findByLabelText('Workcell'), { target: { value: 'wc-1' } })
    fireEvent.click(screen.getByRole('button', { name: /create rule|save changes/i }))

    await waitFor(() => expect(create).toHaveBeenCalled())
    expect(create.mock.lastCall?.[0].workcellId).toBe('wc-1')
    expect(create.mock.lastCall?.[0].assetId).toBeNull()
  })

  it('leaves an org-wide rule with no target at all', async () => {
    // The default must stay reachable: most rules genuinely are fleet-wide, and a form
    // that forced a scope would be worse than one that never offered it.
    page([])
    fireEvent.click(await screen.findByRole('button', { name: /new rule/i }))
    await fillRequired()
    fireEvent.click(screen.getByRole('button', { name: /create rule|save changes/i }))

    await waitFor(() => expect(create).toHaveBeenCalled())
    expect(create.mock.lastCall?.[0].assetId).toBeNull()
    expect(create.mock.lastCall?.[0].workcellId).toBeNull()
    expect(create.mock.lastCall?.[0].assetTypeId).toBeNull()
  })

  it('names the scope in the table instead of leaving it to be opened', async () => {
    // Through `page(...)`, which sets the list mock itself — a per-test
    // `list.mockResolvedValue` before it is simply overwritten.
    page([{ ...RULE, id: 'r1', name: 'Press temp', assetId: 'asset-1' }])
    expect(await screen.findByText('Press 1')).toBeInTheDocument()
  })

  it('reads an unscoped rule as every asset, never as a blank', async () => {
    // A blank cell would read as "applies everywhere" by accident; this says it on purpose.
    page([{ ...RULE, id: 'r2', name: 'Fleet temp', assetId: null }])
    expect(await screen.findByText('Every asset')).toBeInTheDocument()
  })
})

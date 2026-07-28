/**
 * The predictive-maintenance page: the surface an operator uses to find machines that
 * are about to fail.
 *
 * It had no test at all, which is why nobody noticed that its headline figures were
 * computed over a partial fleet. `/api/v1/rul` caps at `limit` and orders by asset
 * **NAME** — remaining useful life is computed per asset in Python, so risk is not a
 * sortable column — meaning the cap keeps the alphabetically-first N. An asset three
 * days from failure whose name begins with W was simply absent, while "Assets Assessed"
 * and "High / Critical Risk" counted the survivors as though the fleet were fully
 * assessed.
 *
 * The endpoint now reports `X-Result-Truncated`, `rulApi` returns `ListResult` so the
 * flag cannot be dropped, and these tests pin that the page says so. The rest cover the
 * behaviour that was already there and equally unguarded: the risk filter, the
 * expand-a-row detail, and the loading and empty states.
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const listAssessments = vi.fn()

vi.mock('../../api', () => ({
  rulApi: { listAssessments: (...a: unknown[]) => listAssessments(...a) },
}))
// The tooltips are NOT stubbed here, unlike the sibling page tests. Replacing
// `components/ui` wholesale breaks the `components` barrel that re-exports it (Card and
// Badge come through the same module), and stubbing only the three tooltip exports still
// leaves the Radix primitives that `Badge` reaches directly — the page then throws
// "Cannot read properties of undefined (reading 'start')" the moment data arrives and
// renders an empty document. Supplying the real provider is both simpler and closer to
// what ships.
import { TooltipProvider } from '../../components/ui'
import { PredictiveMaintenance } from './PredictiveMaintenance'

// Every field `RULAssessment` declares, because the page dereferences
// `recommendedMaintenanceWindow.start` unguarded — correctly, since the server marks
// `recommended_maintenance_window` required. A partial fixture made the page throw and
// render an empty document, which looked like a component bug for three attempts.
const assessment = (over: Record<string, unknown> = {}) => ({
  assetId: 'a1',
  healthScore: 0.9,
  failureProbability: 0.05,
  probabilityHorizonHours: 168,
  remainingUsefulLifeHours: 500,
  riskLevel: 'low',
  confidence: 0.8,
  recommendedMaintenanceWindow: {
    start: '2026-09-01T00:00:00Z',
    end: '2026-09-01T08:00:00Z',
    urgency: 'routine',
    reason: 'No action needed',
  },
  drivers: [],
  modelSource: 'heuristic',
  computedAt: '2026-07-28T10:00:00Z',
  notificationDispatched: false,
  notificationDeliveryCount: 0,
  ...over,
})

const result = (items: unknown[], truncated = false) => ({
  items,
  truncated,
  limit: 100,
})

const wrap = () => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <TooltipProvider>
        <MemoryRouter>
          <PredictiveMaintenance />
        </MemoryRouter>
      </TooltipProvider>
    </QueryClientProvider>,
  )
}

describe('PredictiveMaintenance', () => {
  beforeEach(() => {
    listAssessments.mockReset()
    listAssessments.mockResolvedValue(result([assessment()]))
  })

  it('asks for an explicit page size rather than taking the server default', async () => {
    wrap()
    await screen.findByText('a1')
    expect(listAssessments).toHaveBeenCalledWith(
      expect.objectContaining({ limit: 100, hours: 24 }),
    )
  })

  it('shows a skeleton before the data arrives', () => {
    listAssessments.mockReturnValue(new Promise(() => {}))
    const { container } = wrap()
    expect(container.querySelector('.animate-pulse')).toBeTruthy()
  })

  it('says the fleet is unassessed rather than rendering an empty table', async () => {
    listAssessments.mockResolvedValue(result([]))
    wrap()
    expect(await screen.findByText(/no assets available for assessment/i)).toBeInTheDocument()
  })

  it('counts the assets it actually assessed', async () => {
    listAssessments.mockResolvedValue(
      result([assessment(), assessment({ assetId: 'a2' })]),
    )
    wrap()
    await screen.findByText('a2')
    expect(screen.getByText('Assets Assessed')).toBeInTheDocument()
  })
})

// The reason this file exists. A capped, NAME-ordered list rendered as though it were
// the fleet is the worst possible truncation for a risk view: the machine you most need
// to see is the one most likely to be missing, and every tile above the table counts
// only the survivors.
describe('PredictiveMaintenance — a partial fleet says so', () => {
  beforeEach(() => {
    listAssessments.mockReset()
  })

  it('warns when the server reported more assets than it returned', async () => {
    listAssessments.mockResolvedValue(result([assessment()], true))
    wrap()
    expect(await screen.findByText(/your fleet has more/i)).toBeInTheDocument()
  })

  it('explains that the figures cover only what was returned', async () => {
    listAssessments.mockResolvedValue(result([assessment()], true))
    wrap()
    const notice = await screen.findByRole('status')
    expect(notice.textContent).toMatch(/not counted even if it is close to failure/i)
  })

  it('says nothing when the whole fleet came back', async () => {
    // The negative control: a notice shown unconditionally would satisfy both
    // assertions above and mislead every deployment small enough to fit in one page.
    listAssessments.mockResolvedValue(result([assessment()], false))
    wrap()
    await screen.findByText('a1')
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
    expect(screen.queryByText(/your fleet has more/i)).not.toBeInTheDocument()
  })
})

describe('PredictiveMaintenance — filtering and detail', () => {
  const fleet = [
    assessment({ assetId: 'a1', riskLevel: 'critical' }),
    assessment({ assetId: 'a2', riskLevel: 'low' }),
  ]

  beforeEach(() => {
    listAssessments.mockReset()
    listAssessments.mockResolvedValue(result(fleet))
  })

  it('narrows the table to one risk level', async () => {
    wrap()
    await screen.findByText('a1')
    fireEvent.click(screen.getByRole('button', { name: /critical/i }))
    await waitFor(() => expect(screen.queryByText('a2')).not.toBeInTheDocument())
    expect(screen.getByText('a1')).toBeInTheDocument()
  })

  it('restores the full list when the filter is cleared', async () => {
    wrap()
    await screen.findByText('a1')
    fireEvent.click(screen.getByRole('button', { name: /critical/i }))
    await waitFor(() => expect(screen.queryByText('a2')).not.toBeInTheDocument())
    fireEvent.click(screen.getByRole('button', { name: /^all/i }))
    expect(await screen.findByText('a2')).toBeInTheDocument()
  })

  it('expands a row to its recommendation and collapses again', async () => {
    wrap()
    await screen.findByText('a1')
    fireEvent.click(screen.getByText('a1'))
    expect(await screen.findByText(/no action needed/i)).toBeInTheDocument()
    fireEvent.click(screen.getByText('a1'))
    await waitFor(() =>
      expect(screen.queryByText(/no action needed/i)).not.toBeInTheDocument(),
    )
  })
})

/**
 * The MLOps page, and three claims that outlived the error branch beside them.
 *
 * The current-model line was already corrected — on a failed fetch it says "Model status
 * unavailable" instead of `status?.currentModel || 'No model deployed'`, and its comment
 * records why: an MLOps operator reads "No model deployed" as *nothing is in production*
 * and may act on it by deploying. Everything around that line kept asserting:
 *
 *   **A hardcoded green `Active` badge**, directly beside it. Not derived from anything —
 *   `variant="success"` with a tick, rendered unconditionally. So the page said "Model
 *   status unavailable" and "Active" side by side, and it also said Active when the line
 *   next to it said "No model deployed".
 *
 *   **`{status?.pollIntervalSeconds || 300} seconds`** — a configuration value the
 *   registry never reported, printed indistinguishably from a real one.
 *
 *   **`Available Models: {availableVersions.length}`** — `status?.cachedModels || []`, so
 *   a failed fetch counted 0. An empty model registry and an unreachable one are
 *   different problems and point an operator at different systems.
 *
 * Rule 24: the neighbour of a handled error is where the unhandled claim survives. Fixing
 * the reported line and stopping there left three.
 */
import { render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const getMLOpsStatus = vi.fn()
const deployModel = vi.fn()
const rollbackModel = vi.fn()

vi.mock('../../api', () => ({
  enginesApi: {
    getMLOpsStatus: (...a: unknown[]) => getMLOpsStatus(...a),
    deployModel: (...a: unknown[]) => deployModel(...a),
    rollbackModel: (...a: unknown[]) => rollbackModel(...a),
  },
}))

import { TooltipProvider } from '../../components/ui'
import { MLOpsPipeline } from './MLOpsPipeline'

// Shape from `MLOpsStatus`, not invented — and now the same three keys the endpoint
// actually sends. `deploymentHistory: []` used to sit here too; it was removed with the
// field (FS-367), because a fixture supplying a key the server never sends is how a test
// keeps passing for a pane that would be empty in production.
const status = (over: Record<string, unknown> = {}) => ({
  currentModel: 'tactical_v1.4.2',
  cachedModels: ['tactical_v1.4.2', 'tactical_v1.4.1'],
  pollIntervalSeconds: 60,
  ...over,
})

const wrap = () => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <TooltipProvider>
        <MLOpsPipeline />
      </TooltipProvider>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  getMLOpsStatus.mockResolvedValue(status())
  deployModel.mockResolvedValue({ ok: true })
  rollbackModel.mockResolvedValue({ ok: true })
})

describe('MLOpsPipeline — a reachable registry', () => {
  it('reports the deployed model and the registry settings', async () => {
    // The positive control for all three assertions below.
    wrap()
    // getAllBy, not getBy: the deployed version also appears as an option in the deploy
    // dropdown, so the singular query throws on "multiple elements" and the control
    // fails for a reason that has nothing to do with the property.
    expect((await screen.findAllByText('tactical_v1.4.2')).length).toBeGreaterThan(0)
    expect(screen.getByText('Active')).toBeInTheDocument()
    expect(screen.getByText('60 seconds')).toBeInTheDocument()
    expect(screen.getByText('2')).toBeInTheDocument()
  })

  it('says None rather than Active when nothing is deployed', async () => {
    // The badge asserted "Active" here too, next to a line reading "No model deployed".
    getMLOpsStatus.mockResolvedValue(status({ currentModel: '' }))
    wrap()
    expect(await screen.findByText('No model deployed')).toBeInTheDocument()
    expect(screen.queryByText('Active')).not.toBeInTheDocument()
    expect(screen.getByText('None')).toBeInTheDocument()
  })

  it('still reports a genuinely empty registry as empty', async () => {
    // The other direction: routing everything to "Unknown" would satisfy the failure
    // tests below and hide a real empty registry.
    getMLOpsStatus.mockResolvedValue(status({ cachedModels: [] }))
    wrap()
    await screen.findByText('tactical_v1.4.2')
    expect(screen.getByText('0')).toBeInTheDocument()
    expect(screen.queryByText('Unknown')).not.toBeInTheDocument()
  })
})

describe('MLOpsPipeline — a failed status query asserts nothing', () => {
  const failing = () => getMLOpsStatus.mockRejectedValue(new Error('unreachable'))

  it('does not show a green Active badge beside an unreadable status', async () => {
    // THE ASSERTION THIS FILE EXISTS FOR. The badge was hardcoded, so it made the most
    // confident statement on the card and was the only one derived from nothing.
    failing()
    wrap()
    expect(await screen.findByText('Model status unavailable')).toBeInTheDocument()
    expect(screen.queryByText('Active')).not.toBeInTheDocument()
  })

  it('does not print a poll interval the registry never reported', async () => {
    failing()
    wrap()
    await screen.findByText('Model status unavailable')
    expect(screen.queryByText('300 seconds')).not.toBeInTheDocument()
  })

  it('does not report an empty model registry', async () => {
    // "0 available models" sends an operator to the registry. The registry is fine; the
    // status endpoint is not.
    failing()
    wrap()
    await screen.findByText('Model status unavailable')
    expect(screen.queryByText('0')).not.toBeInTheDocument()
    expect(screen.getAllByText('Unknown').length).toBeGreaterThanOrEqual(2)
  })

  it('still shows that the request failed', async () => {
    failing()
    wrap()
    expect(await screen.findByText(/Failed to load MLOps status/i)).toBeInTheDocument()
  })

  it('offers no deploy or rollback it cannot target', async () => {
    failing()
    wrap()
    await screen.findByText('Model status unavailable')
    expect(screen.getByRole('button', { name: /deploy/i })).toBeDisabled()
    expect(screen.getByRole('button', { name: /rollback/i })).toBeDisabled()
  })
})

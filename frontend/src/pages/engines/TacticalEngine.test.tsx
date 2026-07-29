/**
 * The tactical engine page — and the same defect twice on one screen.
 *
 * The safety-thresholds panel was already corrected: on a failed status query it used to
 * say "No safety thresholds reported by the engine", a definitive claim about SAFETY
 * LIMITS printed directly under a banner saying the fetch had failed. Its comment records
 * that fix.
 *
 * The Model Status badge, one screen above it, was left behind — a red `error` badge
 * reading **Not Loaded**, from `status?.modelLoaded ? 'Loaded' : 'Not Loaded'`. That is a
 * claim that edge inference is down, which is a callout. The truth was that the status
 * endpoint did not answer.
 *
 * Method rule 18: a guard wrong once is likeliest wrong again, and the second instance
 * was in the same file as the first. Fixing what was reported and stopping there is what
 * left it standing.
 *
 * These tests cover both panels, and both directions — the page must still report a model
 * that genuinely is not loaded, or the fix has replaced a false alarm with a blind spot.
 */
import { render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const getTacticalStatus = vi.fn()

vi.mock('../../api', () => ({
  enginesApi: { getTacticalStatus: (...a: unknown[]) => getTacticalStatus(...a) },
}))

import { TooltipProvider } from '../../components/ui'
import { TacticalEngine } from './TacticalEngine'

// Shape from `TacticalEngineStatus`, not invented.
const status = (over: Record<string, unknown> = {}) => ({
  modelLoaded: true,
  modelVersion: 'tactical_v1.4.2',
  maxLatencyTargetMs: 100,
  safetyThresholds: { max_spindle_rpm: 12000, max_nozzle_temp_c: 260 },
  ...over,
})

const wrap = () => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <TooltipProvider>
        <TacticalEngine />
      </TooltipProvider>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  getTacticalStatus.mockResolvedValue(status())
})

describe('TacticalEngine — a running engine', () => {
  it('reports the model and its thresholds', async () => {
    // The positive control for both panels.
    wrap()
    expect(await screen.findByText('Loaded')).toBeInTheDocument()
    expect(screen.getByText('tactical_v1.4.2')).toBeInTheDocument()
    expect(screen.getByText('max_spindle_rpm')).toBeInTheDocument()
    expect(screen.getByText('12000')).toBeInTheDocument()
  })

  it('still reports a model that genuinely is not loaded', async () => {
    // The direction that matters most: an engine with no model IS a callout, and routing
    // everything through "Unknown" would bury it while satisfying the test below.
    getTacticalStatus.mockResolvedValue(status({ modelLoaded: false }))
    wrap()
    expect(await screen.findByText('Not Loaded')).toBeInTheDocument()
    expect(screen.queryByText('Unknown')).not.toBeInTheDocument()
  })

  it('says the engine reported no thresholds when it genuinely reported none', async () => {
    getTacticalStatus.mockResolvedValue(status({ safetyThresholds: {} }))
    wrap()
    expect(
      await screen.findByText('No safety thresholds reported by the engine.'),
    ).toBeInTheDocument()
  })
})

describe('TacticalEngine — a failed status query is not an engine report', () => {
  const failing = () => getTacticalStatus.mockRejectedValue(new Error('unreachable'))

  it('does not report the model as not loaded', async () => {
    // THE ASSERTION THIS FILE EXISTS FOR. A red badge reading "Not Loaded" says edge
    // inference is down — from a request that never returned.
    failing()
    wrap()
    expect(await screen.findByText('Unknown')).toBeInTheDocument()
    expect(screen.queryByText('Not Loaded')).not.toBeInTheDocument()
  })

  it('does not claim the engine reported no safety thresholds', async () => {
    // The half that was already fixed, pinned so it cannot regress.
    failing()
    wrap()
    expect(
      await screen.findByText(/Thresholds unavailable while the engine status cannot be read/i),
    ).toBeInTheDocument()
    expect(
      screen.queryByText('No safety thresholds reported by the engine.'),
    ).not.toBeInTheDocument()
  })

  it('still shows that the request failed', async () => {
    failing()
    wrap()
    expect(
      await screen.findByText(/Failed to load tactical engine status/i),
    ).toBeInTheDocument()
  })
})

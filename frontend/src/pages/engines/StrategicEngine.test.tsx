/**
 * The strategic engine page — the one the emptiness sweep could not see.
 *
 * On a failed recommendations query this rendered:
 *
 *     No pending recommendations. Check back later for new suggestions from the cloud
 *     strategic engine.
 *
 * "Check back later" is an instruction to stop looking, given to someone whose
 * recommendations could not be fetched. Beside it, three summary tiles read 0 Pending,
 * 0 Approved and 0 Rejected — counts of nothing, derived from nothing.
 *
 * THE INTERESTING PART IS WHY THE SWEEP MISSED IT, twice over:
 *
 *   The phrase is about a hundred characters and `EMPTY_PHRASE` capped at forty. A
 *   helpful empty state is longer than a terse one, so the cap bit hardest on the pages
 *   that explained themselves best.
 *
 *   Once the cap was widened it STILL passed, because the nearest error branch within the
 *   proximity window was `{optimizeMutation.isError ? …}` — a different mutation, in a
 *   different card. Proximity had found an error branch that guards something else
 *   entirely. The page's own failure banner is a hundred lines above and guards nothing
 *   below it either.
 *
 * Both blind spots are closed in `failureIsNotEmptiness.test.ts`, each with a control
 * that fails against this file as it was.
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const getStrategicRecommendations = vi.fn()
const getRecommendationHistory = vi.fn()
const approveRecommendation = vi.fn()
const rejectRecommendation = vi.fn()
const optimize = vi.fn()

vi.mock('../../api', () => ({
  enginesApi: {
    getStrategicRecommendations: (...a: unknown[]) => getStrategicRecommendations(...a),
    getRecommendationHistory: (...a: unknown[]) => getRecommendationHistory(...a),
    approveRecommendation: (...a: unknown[]) => approveRecommendation(...a),
    rejectRecommendation: (...a: unknown[]) => rejectRecommendation(...a),
  },
  twinOptimizerApi: { optimize: (...a: unknown[]) => optimize(...a) },
  defaultOptimizeRequest: () => ({ objective: 'throughput', candidates: [] }),
}))

vi.mock('../../stores/authStore', () => ({
  useAuthStore: (selector: any) =>
    selector({ user: { id: 'user-42', email: 'op@example.com' } }),
}))

import { TooltipProvider } from '../../components/ui'
import { StrategicEngine } from './StrategicEngine'

// Shape from `StrategicRecommendation`, not invented.
const rec = (over: Record<string, unknown> = {}) => ({
  recommendationId: 'rec-1',
  assetId: 'a-1',
  assetName: 'CNC Mill #1',
  type: 'schedule_change',
  recommendationType: 'schedule_change',
  priority: 7,
  description: 'Move the Tuesday changeover to the night shift',
  // EXACTLY the keys `/engines/strategic/recommendations` sends, after the casing seam:
  // `oee_improvement` and `cost_reduction`. It used to say `costSavings`, a name no
  // endpoint produces, so the card's cost figure agreed with the fixture and with
  // nothing else (rule 50).
  expectedImpact: { oeeImprovement: 4.2, costReduction: 1800 },
  confidence: 0.82,
  validUntil: '2026-08-30T00:00:00Z',
  requiresApproval: true,
  status: 'pending' as const,
  createdAt: '2026-07-28T09:00:00Z',
  ...over,
})

// "Pending Recommendations" is BOTH a summary-tile label and a Card title further down,
// so `getByText` throws on "multiple elements" and a positional `[0]` would silently
// depend on DOM order. The tile is the one whose label has a sibling holding the figure.
const tileValue = (label: string): string => {
  const tile = screen
    .getAllByText(label)
    .find((el) => el.previousElementSibling?.className.includes('text-2xl'))
  if (!tile) throw new Error(`no summary tile labelled "${label}"`)
  return tile.previousElementSibling!.textContent ?? ''
}

const wrap = () => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <TooltipProvider>
        <StrategicEngine />
      </TooltipProvider>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  getStrategicRecommendations.mockResolvedValue([rec()])
  // Default: a server that predates the history route. The tests describing the
  // pre-route world (the "cannot see decisions" pair) rely on this; the post-route
  // tests override it.
  getRecommendationHistory.mockResolvedValue(null)
  approveRecommendation.mockResolvedValue(undefined)
  rejectRecommendation.mockResolvedValue(undefined)
  optimize.mockResolvedValue({
    objective: 'throughput',
    evaluatedCandidates: 2,
    recommendations: [],
  })
})

describe('StrategicEngine — recommendations that arrived', () => {
  it('lists a pending recommendation', async () => {
    // The positive control for everything below.
    wrap()
    expect(
      await screen.findByText('Move the Tuesday changeover to the night shift'),
    ).toBeInTheDocument()
  })

  it('counts it in the summary tile', async () => {
    wrap()
    await screen.findByText('Move the Tuesday changeover to the night shift')
    expect(tileValue('Pending Recommendations')).toBe('1')
  })

  it('says there are none when the engine genuinely has none', async () => {
    // The direction that keeps the fix honest: an engine with nothing to suggest is a
    // real state and must still read as one.
    getStrategicRecommendations.mockResolvedValue([])
    wrap()
    expect(
      await screen.findByText(/No pending recommendations\. Check back later/i),
    ).toBeInTheDocument()
    expect(tileValue('Pending Recommendations')).toBe('0')
  })
})

describe('StrategicEngine — a failed query suggests nothing about the engine', () => {
  const failing = () =>
    getStrategicRecommendations.mockRejectedValue(new Error('unreachable'))

  it('does not tell the operator to check back later', async () => {
    // THE ASSERTION THIS FILE EXISTS FOR.
    failing()
    wrap()
    await waitFor(() =>
      expect(screen.getByText(/Recommendations could not be loaded/i)).toBeInTheDocument(),
    )
    expect(
      screen.queryByText(/No pending recommendations\. Check back later/i),
    ).not.toBeInTheDocument()
  })

  it('refuses the inference rather than merely withholding the list', async () => {
    failing()
    wrap()
    const notice = await screen.findByRole('alert')
    expect(notice.textContent).toMatch(
      /does not mean the strategic engine has nothing to suggest/i,
    )
  })

  it('does not count zero pending, approved and rejected', async () => {
    // Three tiles reading 0 beside a failure banner. Zero approved recommendations is a
    // statement about a review queue nobody could read.
    failing()
    wrap()
    await screen.findByRole('alert')
    for (const label of ['Pending Recommendations', 'Approved', 'Rejected']) {
      expect(tileValue(label)).toBe('—')
    }
  })

  it('still shows that the request failed', async () => {
    failing()
    wrap()
    expect(
      await screen.findByText(/Failed to load recommendations/i),
    ).toBeInTheDocument()
  })
})

describe('StrategicEngine — the expected-impact grid', () => {
  const wrapWith = async (impact: Record<string, unknown>) => {
    getStrategicRecommendations.mockResolvedValue([rec({ expectedImpact: impact })])
    wrap()
    await screen.findByText('Move the Tuesday changeover to the night shift')
  }

  it('shows the cost reduction the server actually sends', async () => {
    // THE FINDING. The grid named `costSavings`; the key is `cost_reduction`, so the figure
    // never appeared — on a card whose entire purpose is to justify approving the change.
    await wrapWith({ costReduction: 4200 })
    expect(screen.getByText('Cost Reduction')).toBeInTheDocument()
    expect(screen.getByText('$4,200')).toBeInTheDocument()
  })

  it('shows an impact the grid was never written for', async () => {
    // `expectedImpact` is free-form and each recommendation type sends a different set. A
    // throughput gain or an RUL extension had nowhere to go in three fixed slots, so the box
    // rendered empty for two of the engine's three demo recommendations.
    await wrapWith({ throughputGain: 0.04, rulExtensionDays: 45 })
    expect(screen.getByText('Throughput Gain')).toBeInTheDocument()
    expect(screen.getByText('RUL Extension')).toBeInTheDocument()
    expect(screen.getByText('45 days')).toBeInTheDocument()
  })

  it('labels a key nobody has named yet rather than dropping it', async () => {
    await wrapWith({ scrapReduction: 12 })
    expect(screen.getByText('Scrap Reduction')).toBeInTheDocument()
    expect(screen.getByText('12')).toBeInTheDocument()
  })

  it('does not render a slot for an impact that was not sent', async () => {
    // The control: labelling whatever arrives must not mean labelling everything. A card
    // listing every impact the platform knows about, mostly blank, is the fixed grid again.
    await wrapWith({ costReduction: 4200 })
    expect(screen.queryByText('Throughput Gain')).not.toBeInTheDocument()
    expect(screen.queryByText('OEE Impact')).not.toBeInTheDocument()
  })
})

/**
 * FS-366 — "0 approved" is a claim about the world, and it was false.
 *
 * `GET /engines/strategic/recommendations` calls `get_pending_recommendations()` and its
 * response model declares nine fields: recommendation_id, asset_id, type, priority,
 * description, expected_impact, confidence, valid_until, requires_approval. No `status`,
 * no `approved_at`, no `rejected_at`. Verified against a running backend — those nine keys
 * and no others.
 *
 * So `historyRecs` is empty BY CONSTRUCTION. The page rendered that as `0 Approved` and
 * `0 Rejected` beside a History card containing an empty div. Approving a recommendation
 * works — the endpoint returns 200 — so a user could approve three and watch the counter
 * stay at zero, which reads as "nothing happened" rather than "this view cannot see what
 * happened".
 *
 * `strategic_engine.get_recommendation_history()` exists in the service and no route
 * exposes it, so the data is there and unreachable. That is the cross-lane half
 * (`engines.py`); this half is refusing to state a number the page cannot know.
 */
describe('StrategicEngine — decision history it cannot see', () => {
  const withoutStatus = () => {
    // EXACTLY what the API sends: the fixture above carries `status` and `createdAt`,
    // which the real endpoint does not, and that difference is the whole bug.
    const { status, createdAt, assetName, ...wire } = rec()
    return wire
  }

  it('shows — rather than 0 for approvals it cannot enumerate', async () => {
    getStrategicRecommendations.mockResolvedValue([withoutStatus()])
    wrap()
    await waitFor(() => expect(getStrategicRecommendations).toHaveBeenCalled())

    await waitFor(() => expect(tileValue('Approved')).toBe('—'))
    expect(tileValue('Rejected')).toBe('—')
  })

  it('says why the history is empty instead of showing a blank card', async () => {
    getStrategicRecommendations.mockResolvedValue([withoutStatus()])
    wrap()
    expect(
      await screen.findByText(/Decision history is not available from the API/i),
    ).toBeInTheDocument()
  })

  it('still counts normally once an endpoint sends status', async () => {
    // The control, and the reason the flag is derived from the payload rather than
    // hardcoded: the day a route exposes get_recommendation_history(), this page must
    // light up with no further change. Without this test, "always show —" would pass
    // every assertion above.
    getStrategicRecommendations.mockResolvedValue([
      rec({ recommendationId: 'r1', status: 'approved' }),
      rec({ recommendationId: 'r2', status: 'approved' }),
      rec({ recommendationId: 'r3', status: 'rejected' }),
    ])
    wrap()
    await waitFor(() => expect(tileValue('Approved')).toBe('2'))
    expect(tileValue('Rejected')).toBe('1')
    expect(
      screen.queryByText(/Decision history is not available from the API/i),
    ).not.toBeInTheDocument()
  })

  it('does not blame the API contract when the request simply failed', async () => {
    // THE HOLE `failureIsNotEmptiness` CAUGHT in the first draft of the original fix,
    // restated for the history route (P4): a history REQUEST that fails and a server
    // that LACKS the route are different statements. The client maps a 404 to null
    // (absent) and rethrows everything else, so only a genuine failure lands here —
    // and it must not read as "the API cannot do this".
    getRecommendationHistory.mockRejectedValue(new Error('network down'))
    wrap()
    expect(await screen.findByText(/History could not be loaded/i)).toBeInTheDocument()
    expect(
      screen.queryByText(/Decision history is not available from the API/i),
    ).not.toBeInTheDocument()
    expect(
      screen.queryByText(/No recommendations have been approved or rejected yet/i),
    ).not.toBeInTheDocument()
  })

  it('counts the tiles from the history endpoint when it exists', async () => {
    // The day FS-567's route landed, this page had to light up — that was the promise
    // the "—" convention made. The history endpoint is now the source of the counts.
    getRecommendationHistory.mockResolvedValue({
      items: [
        rec({ recommendationId: 'h1', status: 'approved' }),
        rec({ recommendationId: 'h2', status: 'approved' }),
        rec({ recommendationId: 'h3', status: 'rejected' }),
      ],
      engineStopped: false,
      truncated: false,
    })
    wrap()
    await waitFor(() => expect(tileValue('Approved')).toBe('2'))
    expect(tileValue('Rejected')).toBe('1')
  })

  it('warns when the strategic loop behind the data is not running', async () => {
    // The X-Engine-Not-Running header, finally read (P4): the engine pages could render
    // confident status for a dead loop, because the signal rode a header no frontend
    // code looked at.
    getRecommendationHistory.mockResolvedValue({ items: [], engineStopped: true, truncated: false })
    wrap()
    expect(await screen.findByText(/engine loop not running/i)).toBeInTheDocument()
  })

  it('says when the decision log is cut rather than complete', async () => {
    getRecommendationHistory.mockResolvedValue({
      items: [rec({ recommendationId: 'h1', status: 'approved' })],
      engineStopped: false,
      truncated: true,
    })
    wrap()
    expect(await screen.findByText(/most recent decisions only/i)).toBeInTheDocument()
  })

  it('sends the real operator and a real reason on rejection', async () => {
    // 'current-user' and 'User rejected' were string constants — an audit trail of
    // nobody, for no stated reason. The prompt's Cancel aborts instead of submitting.
    const promptSpy = vi.spyOn(window, 'prompt').mockReturnValue('Cost model is stale')
    wrap()
    const reject = await screen.findByRole('button', { name: /reject/i })
    fireEvent.click(reject)
    await waitFor(() =>
      expect(rejectRecommendation).toHaveBeenCalledWith('rec-1', 'user-42', 'Cost model is stale'),
    )
    promptSpy.mockRestore()
  })

  it('cancelling the rejection prompt rejects nothing', async () => {
    const promptSpy = vi.spyOn(window, 'prompt').mockReturnValue(null)
    wrap()
    fireEvent.click(await screen.findByRole('button', { name: /reject/i }))
    expect(rejectRecommendation).not.toHaveBeenCalled()
    promptSpy.mockRestore()
  })

  it('distinguishes "nothing decided yet" from "cannot see decisions"', async () => {
    // Both render an empty list; they are not the same statement and must not read the
    // same. This is the pair the original code collapsed into one blank div.
    getStrategicRecommendations.mockResolvedValue([rec({ status: 'pending' })])
    wrap()
    expect(
      await screen.findByText(/No recommendations have been approved or rejected yet/i),
    ).toBeInTheDocument()
    expect(tileValue('Approved')).toBe('0')
  })
})

/**
 * The OEE detail panel, extracted for P7 and given a loss breakdown for P8.
 *
 * Two properties this file exists for, both of the class this repository keeps buying:
 *
 *   * an unmeasured factor renders "—", not "100%" — the server returns 1.0 as the
 *     neutral multiplier, which is correct arithmetic and reads as a perfect score;
 *   * a failed loss request renders as a FAILED REQUEST, not as a lossless machine.
 *     Proven necessary by mutation: replacing that copy with "No losses recorded"
 *     passed every test in `pages/OEE.test.tsx`, because nothing there drives the
 *     losses query to failure.
 */
import { render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { describe, expect, it, vi, beforeEach } from 'vitest'

const getAssetOEE = vi.fn()
const getLosses = vi.fn()

vi.mock('../../api', () => ({
  dashboardApi: { getAssetOEE: (...a: unknown[]) => getAssetOEE(...a) },
  oeeApi: { getLosses: (...a: unknown[]) => getLosses(...a) },
}))

const { OEEDetailPanel } = await import('./OEEDetailPanel')

const detail = (over: Record<string, unknown> = {}) => ({
  assetId: 'a1',
  assetName: 'CNC Mill #1',
  timeRange: 'last 24h',
  availability: 0.9,
  performance: 1.0,
  quality: 1.0,
  oee: 0.9,
  stateDurations: { execute: 3600 },
  totalPlannedTimeSeconds: 7200,
  ...over,
})

const losses = (over: Record<string, unknown> = {}) => ({
  assetId: 'a1',
  periodHours: 24,
  oee: 62.5,
  losses: {
    availability: { percentage: 12.5, minutes: 90, category: 'downtime' },
    performance: { percentage: 20, impact: '18s vs 14s ideal', category: 'speed' },
    quality: { percentage: 5, rejectedParts: 4, totalParts: 80, category: 'defects' },
  },
  totalLossPercentage: 37.5,
  potentialOee: 62.5,
  ...over,
})

const show = () => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <OEEDetailPanel assetId="a1" assetName="CNC Mill #1" hours={24} />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  getAssetOEE.mockReset()
  getLosses.mockReset()
  getAssetOEE.mockResolvedValue(detail())
  getLosses.mockResolvedValue(losses())
})

describe('the loss breakdown', () => {
  it('orders the losses biggest first — it is a Pareto, not a list', async () => {
    show()
    // Anchor on the loss percentages, which only the breakdown renders (the factor grid
    // above shows the factors themselves, not their losses). Performance is the largest
    // loss in the fixture, so it must lead even though Availability leads the grid.
    // Scoped to the breakdown section, since the factor grid above also renders
    // percentages and comes first in the DOM.
    // "biggest first", not /loss breakdown/i — that also matches the LOADING text
    // ("Loading loss breakdown…"), so the first draft raced its own fixture and read
    // an empty section.
    const heading = await screen.findByText(/biggest first/i)
    const section = heading.parentElement!
    const percentages = Array.from(section.querySelectorAll('span'))
      .map((el) => el.textContent?.trim())
      .filter((text) => /^\d+\.\d%$/.test(text ?? ''))
    expect(percentages).toEqual(['20.0%', '12.5%', '5.0%'])
  })

  it('says the three losses sum rather than share a whole', async () => {
    // The server's own comment: three independent factors added together, so the total
    // can exceed 100. A stacked bar or a percent-of-total pie would draw an arithmetic
    // that does not exist.
    show()
    expect(await screen.findByText(/independent factors/i)).toBeInTheDocument()
  })

  it('renders a failed loss request as a failure, not as a lossless machine', async () => {
    getLosses.mockRejectedValue(new Error('500'))
    show()
    expect(await screen.findByText(/loss breakdown unavailable/i)).toBeInTheDocument()
    expect(screen.queryByText(/no losses/i)).not.toBeInTheDocument()
  })

  it('asks for the window it was given', async () => {
    show()
    await waitFor(() => expect(getLosses).toHaveBeenCalled())
    expect(getLosses.mock.calls[0][1]).toBe(24)
  })
})

describe('an unmeasured factor', () => {
  it('renders — rather than a perfect 100%', async () => {
    getAssetOEE.mockResolvedValue(
      detail({ quality: 1.0, qualityMeasured: false, performanceMeasured: true }),
    )
    show()
    await screen.findByText('Quality')
    // The dash appears for quality; a "100.0%" for it would be the defect.
    expect(await screen.findAllByText('—')).toBeTruthy()
  })

  it('labels OEE an upper bound when a factor stood in', async () => {
    getAssetOEE.mockResolvedValue(detail({ qualityMeasured: false }))
    show()
    expect(await screen.findByText(/upper bound/i)).toBeInTheDocument()
  })

  it('treats absent flags as measured — an older server must not dash a healthy fleet', async () => {
    getAssetOEE.mockResolvedValue(detail())
    show()
    await screen.findByText('Quality')
    expect(screen.queryByText(/upper bound/i)).not.toBeInTheDocument()
  })
})

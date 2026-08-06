/**
 * The historian page — a capped window, and the file that leaves the building.
 *
 * One of FS-364's untested routed pages. Most of what it does it already does well, and
 * this file exists mostly to keep that true: it distinguishes a failed query from an empty
 * window, distinguishes an unavailable asset list from an empty one, and renders
 * `hasMore` as "(more available)" so an operator can see the window was capped.
 *
 * **What the file did not say** (FS-479). `exportCsv` wrote the header and the points and
 * stopped. The screen carried the caveat; the CSV did not — and the CSV is the artefact
 * that leaves: filed, mailed, opened in a spreadsheet by somebody who never saw this page
 * and reads it as the history of that metric over that window.
 *
 * That is the same class as the intake risk score (FS-456): a truncation the producer knows
 * about, reaching the screen and not the artefact. The preamble goes at the
 * TOP because spreadsheet software shows the first rows, and a caveat below ten thousand
 * points is a caveat nobody reads.
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const query = vi.fn()
const list = vi.fn()

vi.mock('../../api', () => ({
  historianApi: { query: (...a: unknown[]) => query(...a) },
  assetsApi: { list: (...a: unknown[]) => list(...a) },
}))

const { Historian } = await import('./Historian')

const point = (i: number) => ({
  timestamp: `2026-08-0${(i % 9) + 1}T00:00:00Z`,
  average: 20 + i,
  minimum: 19 + i,
  maximum: 21 + i,
  sampleCount: 60,
})

const result = (over: Record<string, unknown> = {}) => ({
  assetId: 'asset-1',
  metric: 'temperature',
  granularity: 'raw',
  start: '2026-08-01T00:00:00Z',
  end: '2026-08-02T00:00:00Z',
  effectiveStart: '2026-08-01T00:00:00Z',
  offset: 0,
  limit: 1000,
  count: 2,
  hasMore: false,
  points: [point(0), point(1)],
  ...over,
})

function show() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, refetchInterval: false } },
  })
  return render(
    <QueryClientProvider client={client}>
      <Historian />
    </QueryClientProvider>,
  )
}

/** Run a query by pressing the page's own button, so the test drives the real path.
 *
 * WAITS FOR THE BUTTON TO ENABLE FIRST. `effectiveAssetId` falls back to `assets[0]?.id`,
 * so the button is disabled until the asset list resolves — clicking before then does
 * nothing, and every assertion downstream fails looking like a broken page rather than a
 * test that pressed too early. (Rule 77: asking a question before the answer exists
 * returns "no".)
 */
async function runQuery() {
  const run = await screen.findByRole('button', { name: /query/i })
  await waitFor(() => expect(run).not.toBeDisabled())
  fireEvent.click(run)
}

beforeEach(() => {
  query.mockReset()
  list.mockReset()
  list.mockResolvedValue({ items: [{ id: 'asset-1', name: 'Press 1' }], total: 1 })
})

describe('a capped result is capped in the file too (FS-479)', () => {
  let captured: string

  beforeEach(() => {
    captured = ''
    // The export builds a Blob and clicks an anchor; both are stubbed so the CSV's TEXT is
    // what gets asserted rather than the download mechanics.
    vi.stubGlobal(
      'Blob',
      class {
        constructor(parts: string[]) {
          captured = parts.join('')
        }
      },
    )
    URL.createObjectURL = vi.fn(() => 'blob:x')
    URL.revokeObjectURL = vi.fn()
  })

  it('marks the CSV partial when more points exist', async () => {
    query.mockResolvedValue(result({ hasMore: true, count: 2, limit: 2 }))
    show()
    await runQuery()

    fireEvent.click(await screen.findByRole('button', { name: /export csv/i }))

    expect(captured).toMatch(/^# PARTIAL/)
    expect(captured).toContain('limit 2')
    // And still carries the data — a warning that costs the rows is not an improvement.
    expect(captured).toContain('timestamp,average,minimum,maximum,sample_count')
    expect(captured).toContain('2026-08-01T00:00:00Z')
  })

  it('says nothing when the whole window was returned', async () => {
    // The other direction. A caveat on every export is one nobody reads, and it would make
    // the capped case indistinguishable from the complete one.
    query.mockResolvedValue(result({ hasMore: false }))
    show()
    await runQuery()

    fireEvent.click(await screen.findByRole('button', { name: /export csv/i }))

    expect(captured).not.toMatch(/PARTIAL/)
    expect(captured.startsWith('timestamp,')).toBe(true)
  })
})

describe('the screen already says it, and must keep saying it', () => {
  it('shows (more available) when the window was capped', async () => {
    query.mockResolvedValue(result({ hasMore: true }))
    show()
    await runQuery()

    await waitFor(() =>
      expect(screen.getByText(/more available/i)).toBeInTheDocument(),
    )
  })

  it('does not when it was not', async () => {
    query.mockResolvedValue(result())
    show()
    await runQuery()

    await waitFor(() => expect(screen.getByText(/2 points/i)).toBeInTheDocument())
    expect(screen.queryByText(/more available/i)).not.toBeInTheDocument()
  })
})

describe('a failed query is not an empty window', () => {
  it('says which it was', async () => {
    query.mockRejectedValue(new Error('boom'))
    show()
    await runQuery()

    const alert = await screen.findByRole('alert')
    expect(alert.textContent).toMatch(/not an empty window/i)
    expect(screen.queryByText(/No data points in this window/i)).not.toBeInTheDocument()
  })

  it('shows the empty state when the window really is empty', async () => {
    query.mockResolvedValue(result({ points: [], count: 0 }))
    show()
    await runQuery()

    await waitFor(() =>
      expect(screen.getByText(/No data points in this window/i)).toBeInTheDocument(),
    )
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })
})

describe('an unavailable asset list is not an empty one', () => {
  it('says so', async () => {
    // "No assets" tells an operator their fleet is empty. "Asset list unavailable" tells
    // them the request failed. Only one of those is ever true at a time.
    list.mockRejectedValue(new Error('down'))
    show()

    await waitFor(() =>
      expect(screen.getByText(/Asset list unavailable/i)).toBeInTheDocument(),
    )
  })
})

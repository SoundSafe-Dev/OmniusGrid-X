import { FC, useMemo, useState } from 'react'
import { useInfiniteQuery, useQuery } from '@tanstack/react-query'
import {
  Line, LineChart, ResponsiveContainer, Tooltip as RTooltip, XAxis, YAxis, CartesianGrid,
} from 'recharts'
import { telemetryApi } from '../../api'
import type { TelemetryHistoryPage, TelemetryPoint } from '../../types'

// Historical telemetry line chart (task 8): fetches telemetryApi.getHistoryPage and
// renders a selectable metric over time. Complements the realtime charts, which
// are WebSocket-driven; this one is for stored history + aggregation.
//
// FS-126: paged via the FS-89 time-series envelope. The first page covers the
// selected time range; "Load older" walks backwards using meta.oldest as the
// next end_time cursor while meta.hasMore gates the affordance. Older points
// are prepended to the series; the newest page renders exactly as before.
interface Props {
  assetId: string
  height?: number
}

const AGGS: Array<{ label: string; value?: '1min' | '5min' | '1hour' }> = [
  { label: 'Raw', value: undefined },
  { label: '1m', value: '1min' },
  { label: '5m', value: '5min' },
  { label: '1h', value: '1hour' },
]

// Time-range presets: the first page requests [now - ms, now].
const RANGES: Array<{ label: string; ms: number }> = [
  { label: '1h', ms: 60 * 60 * 1000 },
  { label: '6h', ms: 6 * 60 * 60 * 1000 },
  { label: '24h', ms: 24 * 60 * 60 * 1000 },
  { label: '7d', ms: 7 * 24 * 60 * 60 * 1000 },
]

export const TelemetryHistoryChart: FC<Props> = ({ assetId, height = 260 }) => {
  const [metric, setMetric] = useState<string | undefined>(undefined)
  const [agg, setAgg] = useState<'1min' | '5min' | '1hour' | undefined>(undefined)
  const [range, setRange] = useState<string>('24h')

  const { data: available } = useQuery({
    queryKey: ['metrics', assetId],
    queryFn: () => telemetryApi.getAvailableMetrics(assetId),
  })
  const activeMetric = metric ?? available?.metrics?.[0]

  const {
    data: history,
    isLoading,
    isError,
    refetch,
    hasNextPage,
    isFetchingNextPage,
    fetchNextPage,
  } = useInfiniteQuery({
    queryKey: ['history', assetId, activeMetric, agg, range],
    queryFn: ({ pageParam }) => {
      const rangeMs = RANGES.find((r) => r.label === range)?.ms ?? RANGES[2].ms
      return telemetryApi.getHistoryPage(assetId, {
        metricName: activeMetric,
        aggregation: agg,
        startTime: new Date(Date.now() - rangeMs).toISOString(),
        // Cursor paging (FS-89): the next older page ends where the previous
        // page's oldest point was.
        endTime: pageParam ?? undefined,
      })
    },
    initialPageParam: null as string | null,
    getNextPageParam: (lastPage: TelemetryHistoryPage) =>
      lastPage.meta.hasMore ? lastPage.meta.oldest : null,
    enabled: !!activeMetric,
  })

  const series = useMemo(() => {
    // pages[0] is the newest window; later pages are older, so prepend them.
    const merged: TelemetryPoint[] = (history?.pages ?? [])
      .slice()
      .reverse()
      .flatMap((p) => p.items)
    merged.sort((a, b) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime())
    // The end_time cursor is inclusive on some backends: drop boundary duplicates.
    const deduped = merged.filter((p, i) => i === 0 || p.timestamp !== merged[i - 1].timestamp)
    return deduped.map((p) => ({ t: new Date(p.timestamp).toLocaleTimeString(), value: p.value }))
  }, [history])

  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-2 mb-2">
        <div className="flex items-center gap-2">
          <select
            aria-label="Metric"
            className="text-sm px-2 py-1 bg-opsgrid-bg border border-opsgrid-border rounded text-opsgrid-text"
            value={activeMetric ?? ''}
            onChange={(e) => setMetric(e.target.value)}
          >
            {(available?.metrics ?? []).map((m) => <option key={m} value={m}>{m}</option>)}
          </select>
          <button
            onClick={() => fetchNextPage()}
            disabled={!hasNextPage || isFetchingNextPage}
            className="text-xs px-2 py-1 rounded border border-opsgrid-border text-opsgrid-text-secondary disabled:opacity-40 disabled:cursor-not-allowed"
            title="Fetch the next older page of points"
          >
            {isFetchingNextPage ? 'Loading…' : 'Load older'}
          </button>
        </div>
        <div className="flex items-center gap-3">
          <div className="flex gap-1" role="group" aria-label="Time range">
            {RANGES.map((r) => (
              <button
                key={r.label}
                onClick={() => setRange(r.label)}
                className={`text-xs px-2 py-1 rounded border ${range === r.label ? 'bg-opsgrid-primary text-opsgrid-bg border-opsgrid-primary' : 'border-opsgrid-border text-opsgrid-text-secondary'}`}
              >
                {r.label}
              </button>
            ))}
          </div>
          <div className="flex gap-1" role="group" aria-label="Aggregation">
            {AGGS.map((a) => (
              <button
                key={a.label}
                onClick={() => setAgg(a.value)}
                className={`text-xs px-2 py-1 rounded border ${agg === a.value ? 'bg-opsgrid-primary text-opsgrid-bg border-opsgrid-primary' : 'border-opsgrid-border text-opsgrid-text-secondary'}`}
              >
                {a.label}
              </button>
            ))}
          </div>
        </div>
      </div>
      {isLoading ? (
        <div className="text-sm text-opsgrid-text-secondary py-8 text-center">Loading history…</div>
      ) : isError ? (
        /* A FAILED QUERY IS NOT AN ABSENCE OF TELEMETRY. Without this branch a rejected
           request fell through to "No history for this metric", which an engineer
           diagnosing a machine reads as "this sensor produced nothing in that window" —
           a conclusion about the equipment drawn from a failure of the request. */
        <div className="text-sm py-8 text-center space-y-2" role="alert">
          <p className="text-status-alarm">
            Couldn’t load history — this is a loading failure, not an absence of data.
          </p>
          <button
            type="button"
            onClick={() => refetch()}
            className="text-xs underline text-opsgrid-text-secondary hover:text-opsgrid-text"
          >
            Retry
          </button>
        </div>
      ) : series.length === 0 ? (
        <div className="text-sm text-opsgrid-text-secondary py-8 text-center">No history for this metric</div>
      ) : (
        <ResponsiveContainer width="100%" height={height}>
          <LineChart data={series} margin={{ top: 5, right: 10, bottom: 5, left: -10 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#2a2f3a" />
            <XAxis dataKey="t" tick={{ fontSize: 10, fill: '#8b93a7' }} minTickGap={40} />
            <YAxis tick={{ fontSize: 10, fill: '#8b93a7' }} />
            <RTooltip contentStyle={{ background: '#1a1f2b', border: '1px solid #2a2f3a', fontSize: 12 }} />
            <Line type="monotone" dataKey="value" stroke="#4ade80" dot={false} strokeWidth={2} isAnimationActive={false} />
          </LineChart>
        </ResponsiveContainer>
      )}
    </div>
  )
}

export default TelemetryHistoryChart

import { FC, useMemo, useState } from 'react'
import { useQuery } from 'react-query'
import {
  Line, LineChart, ResponsiveContainer, Tooltip as RTooltip, XAxis, YAxis, CartesianGrid,
} from 'recharts'
import { telemetryApi } from '../../api'

// Historical telemetry line chart (task 8): fetches telemetryApi.getHistory and
// renders a selectable metric over time. Complements the realtime charts, which
// are WebSocket-driven; this one is for stored history + aggregation.
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

export const TelemetryHistoryChart: FC<Props> = ({ assetId, height = 260 }) => {
  const [metric, setMetric] = useState<string | undefined>(undefined)
  const [agg, setAgg] = useState<'1min' | '5min' | '1hour' | undefined>(undefined)

  const { data: available } = useQuery(['metrics', assetId], () => telemetryApi.getAvailableMetrics(assetId))
  const activeMetric = metric ?? available?.metrics?.[0]

  const { data: history, isLoading } = useQuery(
    ['history', assetId, activeMetric, agg],
    () => telemetryApi.getHistory(assetId, { metricName: activeMetric, aggregation: agg }),
    { enabled: !!activeMetric }
  )

  const series = useMemo(
    () => (history ?? []).map((p) => ({ t: new Date(p.timestamp).toLocaleTimeString(), value: p.value })),
    [history]
  )

  return (
    <div>
      <div className="flex items-center justify-between mb-2">
        <select
          aria-label="Metric"
          className="text-sm px-2 py-1 bg-opsgrid-bg border border-opsgrid-border rounded text-opsgrid-text"
          value={activeMetric ?? ''}
          onChange={(e) => setMetric(e.target.value)}
        >
          {(available?.metrics ?? []).map((m) => <option key={m} value={m}>{m}</option>)}
        </select>
        <div className="flex gap-1">
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
      {isLoading ? (
        <div className="text-sm text-opsgrid-text-secondary py-8 text-center">Loading history…</div>
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

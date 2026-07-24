import { FC, ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import {
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip as RTooltip,
  XAxis,
  YAxis,
} from 'recharts'
import {
  Activity,
  AlertTriangle,
  Box,
  CheckCircle,
  Gauge,
  Package,
} from 'lucide-react'
import { dashboardApi, alarmsApi } from '../api'
import { dashboardAnalyticsApi } from '../api/dashboardAnalytics'
import { Tooltip, TooltipTrigger, TooltipContent } from '../components/ui'
import { chartPalette, orderSeverities, severityColor } from '../components/charts/chartPalette'
import { useUIStore } from '../stores/uiStore'

/** Window for every trend on this page. FS-194 turns this into a control. */
const HOURS = 24
const BUCKET = '1hour' as const

const fmtTime = (iso: string) =>
  new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })

const fmtNum = (n: number | null | undefined) =>
  n == null ? '—' : n.toLocaleString(undefined, { maximumFractionDigits: 1 })

/**
 * Widget shell. Each widget owns its loading/empty/error state so one failing
 * query degrades a single card instead of blanking the page — the route-level
 * ErrorBoundary is the last resort, not the first.
 */
const Widget: FC<{
  title: string
  subtitle?: string
  to?: string
  isLoading?: boolean
  isError?: boolean
  isEmpty?: boolean
  emptyLabel?: string
  height?: number
  children: ReactNode
  className?: string
}> = ({
  title,
  subtitle,
  to,
  isLoading,
  isError,
  isEmpty,
  emptyLabel = 'No data in this window',
  height = 240,
  children,
  className = '',
}) => (
  <section
    aria-label={title}
    className={`bg-opsgrid-panel border border-opsgrid-border rounded-lg ${className}`}
  >
    <div className="flex items-start justify-between px-4 py-3 border-b border-opsgrid-border">
      <div>
        <h3 className="text-base font-semibold text-opsgrid-text">{title}</h3>
        {subtitle && (
          <p className="text-xs text-opsgrid-text-secondary mt-0.5">{subtitle}</p>
        )}
      </div>
      {to && (
        <Link to={to} className="text-sm text-opsgrid-primary hover:underline shrink-0">
          View all
        </Link>
      )}
    </div>
    <div className="p-4" style={{ minHeight: height }}>
      {isLoading ? (
        <div
          role="status"
          aria-live="polite"
          className="h-full flex items-center justify-center text-sm text-opsgrid-text-secondary"
          style={{ minHeight: height - 32 }}
        >
          Loading…
        </div>
      ) : isError ? (
        <div
          role="alert"
          className="h-full flex items-center justify-center text-sm text-status-alarm"
          style={{ minHeight: height - 32 }}
        >
          Couldn’t load this data
        </div>
      ) : isEmpty ? (
        <div
          className="h-full flex items-center justify-center text-sm text-opsgrid-text-secondary"
          style={{ minHeight: height - 32 }}
        >
          {emptyLabel}
        </div>
      ) : (
        children
      )}
    </div>
  </section>
)

const Dashboard: FC = () => {
  const theme = useUIStore((s) => s.theme)
  const palette = chartPalette(theme === 'dark' ? 'dark' : 'light')

  const overviewQ = useQuery({
    queryKey: ['dashboard-overview'],
    queryFn: () => dashboardApi.getOverview(),
    refetchInterval: 30000,
  })
  const alarmsQ = useQuery({
    queryKey: ['active-alarms'],
    queryFn: () => alarmsApi.getActive(),
    refetchInterval: 30000,
  })
  const availabilityQ = useQuery({
    queryKey: ['dash-availability', HOURS, BUCKET],
    queryFn: () => dashboardAnalyticsApi.getAvailabilityTrend(HOURS, BUCKET),
  })
  const throughputQ = useQuery({
    queryKey: ['dash-throughput', HOURS, BUCKET],
    queryFn: () => dashboardAnalyticsApi.getThroughput(HOURS, BUCKET),
  })
  const alarmTrendQ = useQuery({
    queryKey: ['dash-alarm-trend', HOURS, BUCKET],
    queryFn: () => dashboardAnalyticsApi.getAlarmTrend(HOURS, BUCKET),
  })
  const healthQ = useQuery({
    queryKey: ['dash-health', HOURS],
    queryFn: () => dashboardAnalyticsApi.getHealthDistribution(HOURS),
  })
  const atRiskQ = useQuery({
    queryKey: ['dash-at-risk', HOURS],
    queryFn: () => dashboardAnalyticsApi.getAssetsAtRisk(HOURS, 5),
  })

  const overview = overviewQ.data
  const axisProps = {
    stroke: palette.axis,
    tick: { fill: palette.mutedText, fontSize: 11 },
    tickLine: false,
  }
  const tooltipStyle = {
    contentStyle: {
      background: 'var(--color-panel)',
      border: '1px solid var(--color-border)',
      borderRadius: 8,
      fontSize: 12,
      color: 'var(--color-text)',
    },
    labelStyle: { color: 'var(--color-text-secondary)' },
  }

  const kpis = [
    {
      label: 'Total Assets',
      value: fmtNum(overview?.totalAssets),
      icon: Box,
      tone: 'text-opsgrid-primary',
      tip: 'Registered manufacturing assets in your organization',
    },
    {
      label: 'Active',
      value: fmtNum(overview?.activeAssets),
      icon: CheckCircle,
      tone: 'text-status-running',
      tip: 'Assets currently marked active',
    },
    {
      label: 'Availability',
      value:
        availabilityQ.data == null
          ? '—'
          : `${fmtNum(availabilityQ.data.averageAvailabilityPct)}%`,
      icon: Gauge,
      tone: 'text-opsgrid-text',
      // Naming this "Availability" rather than "OEE" is deliberate — see FS-192.
      tip: 'Run time ÷ elapsed time over the last 24h. Availability only — not full OEE.',
    },
    {
      label: 'Parts (24h)',
      value: fmtNum(throughputQ.data?.totals.totalParts),
      icon: Package,
      tone: 'text-opsgrid-text',
      tip: 'Total parts reported by asset counters in the last 24 hours',
    },
    {
      label: 'Active Alarms',
      value: fmtNum(overview?.activeAlarms),
      icon: AlertTriangle,
      tone:
        (overview?.criticalAlarms || 0) > 0 ? 'text-status-alarm' : 'text-status-warning',
      tip: 'Alarms currently requiring attention',
    },
    {
      label: 'Critical',
      value: fmtNum(overview?.criticalAlarms),
      icon: Activity,
      tone: 'text-status-alarm',
      tip: 'Critical-severity alarms requiring immediate action',
    },
  ]

  const severities = alarmTrendQ.data ? orderSeverities(alarmTrendQ.data.severities) : []
  const alarmTotal =
    alarmTrendQ.data?.series.reduce((acc, p) => acc + (p.total as number), 0) ?? 0

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-2xl font-bold text-opsgrid-text">Operations Overview</h1>
        <p className="text-sm text-opsgrid-text-secondary">
          Live fleet status — trends over the last 24 hours
        </p>
      </div>

      {/* KPI row — headline numbers belong in stat tiles, not a bar chart. */}
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4">
        {kpis.map((kpi) => {
          const Icon = kpi.icon
          return (
            <Tooltip key={kpi.label}>
              <TooltipTrigger asChild>
                <div className="bg-opsgrid-panel border border-opsgrid-border rounded-lg p-4">
                  <div className="flex items-center justify-between gap-2">
                    <div className="min-w-0">
                      <p className="text-sm text-opsgrid-text-secondary truncate">
                        {kpi.label}
                      </p>
                      <p className={`text-2xl font-bold ${kpi.tone}`}>{kpi.value}</p>
                    </div>
                    <Icon className={kpi.tone} size={22} aria-hidden="true" />
                  </div>
                </div>
              </TooltipTrigger>
              <TooltipContent>{kpi.tip}</TooltipContent>
            </Tooltip>
          )
        })}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* Single series -> no legend; the title names it. */}
        <Widget
          title="Fleet Availability"
          subtitle="Run time ÷ elapsed — availability only, not full OEE"
          to="/oee"
          isLoading={availabilityQ.isLoading}
          isError={availabilityQ.isError}
          isEmpty={!availabilityQ.data?.series?.length}
        >
          <ResponsiveContainer width="100%" height={200}>
            <LineChart
              data={availabilityQ.data?.series ?? []}
              margin={{ top: 5, right: 12, bottom: 0, left: -12 }}
            >
              <CartesianGrid strokeDasharray="3 3" stroke={palette.grid} vertical={false} />
              <XAxis dataKey="timestamp" tickFormatter={fmtTime} {...axisProps} />
              <YAxis domain={[0, 100]} unit="%" {...axisProps} />
              <RTooltip
                {...tooltipStyle}
                labelFormatter={(v) => new Date(v as string).toLocaleString()}
                formatter={(v: number) => [`${fmtNum(v)}%`, 'Availability']}
              />
              <Line
                type="monotone"
                dataKey="availabilityPct"
                name="Availability"
                stroke={palette.series1}
                strokeWidth={2}
                dot={false}
                connectNulls={false}
                isAnimationActive={false}
              />
            </LineChart>
          </ResponsiveContainer>
        </Widget>

        <Widget
          title="Throughput"
          subtitle={
            throughputQ.data?.totals.qualityPct == null
              ? 'Parts produced — quality needs good/total counters'
              : `Parts produced — ${fmtNum(throughputQ.data.totals.qualityPct)}% good`
          }
          isLoading={throughputQ.isLoading}
          isError={throughputQ.isError}
          isEmpty={!throughputQ.data?.series?.length}
        >
          <ResponsiveContainer width="100%" height={200}>
            <LineChart
              data={throughputQ.data?.series ?? []}
              margin={{ top: 5, right: 12, bottom: 0, left: -12 }}
            >
              <CartesianGrid strokeDasharray="3 3" stroke={palette.grid} vertical={false} />
              <XAxis dataKey="timestamp" tickFormatter={fmtTime} {...axisProps} />
              <YAxis {...axisProps} />
              <RTooltip
                {...tooltipStyle}
                labelFormatter={(v) => new Date(v as string).toLocaleString()}
              />
              <Line
                type="monotone"
                dataKey="totalParts"
                name="Total parts"
                stroke={palette.series1}
                strokeWidth={2}
                dot={false}
                isAnimationActive={false}
              />
              <Line
                type="monotone"
                dataKey="goodParts"
                name="Good parts"
                stroke={palette.series2}
                strokeWidth={2}
                dot={false}
                isAnimationActive={false}
              />
            </LineChart>
          </ResponsiveContainer>
          {/* 2 series -> identity must not be color-alone. */}
          <ul className="flex gap-4 mt-2 text-xs text-opsgrid-text-secondary">
            <li className="flex items-center gap-1.5">
              <span
                className="inline-block w-3 h-0.5 rounded"
                style={{ background: palette.series1 }}
                aria-hidden="true"
              />
              Total parts
            </li>
            <li className="flex items-center gap-1.5">
              <span
                className="inline-block w-3 h-0.5 rounded"
                style={{ background: palette.series2 }}
                aria-hidden="true"
              />
              Good parts
            </li>
          </ul>
        </Widget>

        {/* Severity is ORDINAL -> single-hue ramp, darker = more severe. */}
        <Widget
          title="Alarms over time"
          subtitle="Stacked by severity — darker is more severe"
          to="/alarms"
          isLoading={alarmTrendQ.isLoading}
          isError={alarmTrendQ.isError}
          isEmpty={alarmTotal === 0}
          emptyLabel="No alarms in this window"
        >
          <ResponsiveContainer width="100%" height={200}>
            <BarChart
              data={alarmTrendQ.data?.series ?? []}
              margin={{ top: 5, right: 12, bottom: 0, left: -12 }}
            >
              <CartesianGrid strokeDasharray="3 3" stroke={palette.grid} vertical={false} />
              <XAxis dataKey="timestamp" tickFormatter={fmtTime} {...axisProps} />
              <YAxis allowDecimals={false} {...axisProps} />
              <RTooltip
                {...tooltipStyle}
                labelFormatter={(v) => new Date(v as string).toLocaleString()}
              />
              {severities.map((sev, i) => (
                <Bar
                  key={sev}
                  dataKey={sev}
                  name={sev}
                  stackId="alarms"
                  fill={severityColor(sev, palette)}
                  // 2px surface gap between stacked segments.
                  stroke="var(--color-panel)"
                  strokeWidth={2}
                  radius={i === severities.length - 1 ? [4, 4, 0, 0] : undefined}
                  isAnimationActive={false}
                />
              ))}
            </BarChart>
          </ResponsiveContainer>
          <ul className="flex flex-wrap gap-3 mt-2 text-xs text-opsgrid-text-secondary">
            {severities.map((sev) => (
              <li key={sev} className="flex items-center gap-1.5">
                <span
                  className="inline-block w-2.5 h-2.5 rounded-sm"
                  style={{ background: severityColor(sev, palette) }}
                  aria-hidden="true"
                />
                {sev}
              </li>
            ))}
          </ul>
        </Widget>

        {/* Color encodes nothing here — the axis carries band identity. */}
        <Widget
          title="Asset health"
          subtitle={
            healthQ.data?.averageHealth == null
              ? 'Distribution across the fleet'
              : `Distribution — average ${fmtNum(healthQ.data.averageHealth)}/100`
          }
          isLoading={healthQ.isLoading}
          isError={healthQ.isError}
          isEmpty={!healthQ.data?.assetCount}
          emptyLabel="No active assets"
        >
          <ResponsiveContainer width="100%" height={200}>
            <BarChart
              data={healthQ.data?.bands ?? []}
              layout="vertical"
              margin={{ top: 5, right: 24, bottom: 0, left: 24 }}
            >
              <CartesianGrid strokeDasharray="3 3" stroke={palette.grid} horizontal={false} />
              <XAxis type="number" allowDecimals={false} {...axisProps} />
              <YAxis
                type="category"
                dataKey="band"
                width={70}
                tickFormatter={(b: string) => b.replace('_', ' ')}
                {...axisProps}
              />
              <RTooltip {...tooltipStyle} formatter={(v: number) => [v, 'Assets']} />
              <Bar
                dataKey="count"
                name="Assets"
                fill={palette.series1}
                radius={[0, 4, 4, 0]}
                isAnimationActive={false}
              />
            </BarChart>
          </ResponsiveContainer>
        </Widget>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* A ranked list is a table, not a chart. */}
        <Widget
          title="Assets at risk"
          subtitle="Lowest health first"
          to="/assets"
          isLoading={atRiskQ.isLoading}
          isError={atRiskQ.isError}
          isEmpty={!atRiskQ.data?.items?.length}
          emptyLabel="No assets scored yet"
          height={220}
        >
          <table className="w-full text-sm">
            <caption className="sr-only">Assets with the lowest health scores</caption>
            <thead>
              <tr className="text-left text-xs text-opsgrid-text-secondary">
                <th scope="col" className="font-medium pb-2">Asset</th>
                <th scope="col" className="font-medium pb-2 text-right">Health</th>
                <th scope="col" className="font-medium pb-2 text-right">Avail.</th>
                <th scope="col" className="font-medium pb-2 text-right">Alarms/h</th>
              </tr>
            </thead>
            <tbody>
              {(atRiskQ.data?.items ?? []).map((a) => (
                <tr key={a.assetId} className="border-t border-opsgrid-border">
                  <td className="py-2 pr-2">
                    <Link
                      to={`/assets/${a.assetId}`}
                      className="text-opsgrid-text hover:underline"
                    >
                      {a.assetName}
                    </Link>
                  </td>
                  <td className="py-2 text-right tabular-nums font-medium">
                    {fmtNum(a.healthScore)}
                  </td>
                  <td className="py-2 text-right tabular-nums text-opsgrid-text-secondary">
                    {fmtNum(a.availabilityPct)}%
                  </td>
                  <td className="py-2 text-right tabular-nums text-opsgrid-text-secondary">
                    {fmtNum(a.alarmRatePerHour)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Widget>

        <Widget
          title={`Active alarms (${alarmsQ.data?.count ?? 0})`}
          to="/alarms"
          isLoading={alarmsQ.isLoading}
          isError={alarmsQ.isError}
          isEmpty={!(alarmsQ.data?.count ?? 0)}
          emptyLabel="No active alarms"
          height={220}
        >
          <ul className="space-y-2">
            {(alarmsQ.data?.alarms ?? []).slice(0, 5).map((alarm: any) => (
              <li
                key={alarm.id}
                className="flex items-center gap-3 p-2 bg-opsgrid-bg rounded-lg"
              >
                <span
                  className="w-2 h-2 rounded-full shrink-0"
                  style={{ background: severityColor(alarm.severity, palette) }}
                  aria-hidden="true"
                />
                <div className="flex-1 min-w-0">
                  <p className="font-medium truncate text-opsgrid-text">{alarm.message}</p>
                  <p className="text-xs text-opsgrid-text-secondary truncate">
                    {alarm.assetName} • {new Date(alarm.occurredAt).toLocaleString()}
                  </p>
                </div>
                <span className="px-2 py-0.5 rounded text-xs font-medium bg-opsgrid-bg text-opsgrid-text-secondary border border-opsgrid-border shrink-0">
                  {alarm.severity}
                </span>
              </li>
            ))}
          </ul>
        </Widget>
      </div>

      {/* Assets by PackML state — kept from the original page. */}
      <Widget
        title="Assets by PackML state"
        isLoading={overviewQ.isLoading}
        isError={overviewQ.isError}
        isEmpty={!Object.keys(overview?.assetsByState ?? {}).length}
        emptyLabel="No assets reporting state"
        height={120}
      >
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4">
          {Object.entries(overview?.assetsByState || {}).map(([state, count]) => {
            const describe = (s: string) => {
              switch (s) {
                case 'Execute': return 'Asset is actively producing parts'
                case 'Idle': return 'Asset is available but not producing'
                case 'Held': return 'Asset paused, awaiting operator intervention'
                case 'Suspended': return 'Asset suspended by external command'
                case 'Aborted': return 'Asset stopped due to error or emergency'
                case 'Stopped': return 'Asset in planned stopped state'
                case 'Starting': return 'Asset is starting up'
                case 'Completing': return 'Asset is completing current operation'
                case 'Complete': return 'Asset has completed operation'
                case 'Resetting': return 'Asset is resetting to initial state'
                default: return 'Asset state'
              }
            }
            return (
              <Tooltip key={state}>
                <TooltipTrigger asChild>
                  <div className="bg-opsgrid-bg rounded-lg p-3 text-center">
                    <div
                      className={`text-2xl font-bold ${
                        state === 'Execute'
                          ? 'text-packml-execute'
                          : state === 'Idle'
                          ? 'text-packml-idle'
                          : state === 'Held' || state === 'Suspended'
                          ? 'text-packml-held'
                          : state === 'Aborted'
                          ? 'text-packml-aborted'
                          : 'text-opsgrid-text'
                      }`}
                    >
                      {count as number}
                    </div>
                    <div className="text-sm text-opsgrid-text-secondary mt-1">{state}</div>
                  </div>
                </TooltipTrigger>
                <TooltipContent>{describe(state)}</TooltipContent>
              </Tooltip>
            )
          })}
        </div>
      </Widget>
    </div>
  )
}

export default Dashboard

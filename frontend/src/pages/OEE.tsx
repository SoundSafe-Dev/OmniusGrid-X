import { FC, Fragment, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { BarChart3, TrendingUp, Clock, ChevronDown, ChevronRight } from 'lucide-react'
import { dashboardApi } from '../api'
import { Button, Tooltip, TooltipTrigger, TooltipContent } from '../components/ui'
import { ExportButton } from '../components/common'
import { useAuth } from '../hooks/useAuth'

const OEE: FC = () => {
  const { isAdmin } = useAuth()
  // Clicking a row expands an inline OEE breakdown for that asset (the row
  // tooltip has always promised this; the handler was never wired).
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const { data: fleetOEE, isLoading, isError, refetch } = useQuery({
    queryKey: ['fleet-oee'],
    queryFn: () => dashboardApi.getFleetOEE(),
  })

  // The FleetOEE type does not (yet) declare fleetAveragePerformance, but the
  // API can return it; narrow locally so the 100% fallback below is preserved.
  const fleetAveragePerformance =
    fleetOEE &&
    'fleetAveragePerformance' in fleetOEE &&
    typeof fleetOEE.fleetAveragePerformance === 'number'
      ? fleetOEE.fleetAveragePerformance
      : undefined

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="text-opsgrid-text-secondary">Loading...</div>
      </div>
    )
  }

  // A FAILED FLEET LOAD SAID NOTHING AT ALL. There was no error branch, and on failure
  // `fleetOEE` is undefined — so `fleetOEE?.assets?.length === 0` is false, the empty
  // state below does not render either, and the page showed an OEE table with no rows
  // and no explanation. Silently empty is worse than wrongly labelled: there is nothing
  // for the reader to disbelieve.
  if (isError) {
    return (
      <div className="flex flex-col items-center justify-center h-64 gap-3" role="alert">
        <p className="text-status-alarm">
          Couldn’t load fleet OEE — this is a loading failure, not an idle fleet.
        </p>
        <Button variant="secondary" onClick={() => refetch()}>
          Retry
        </Button>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <Tooltip>
          <TooltipTrigger asChild>
            <h2 className="text-xl font-semibold flex items-center gap-2">
              <BarChart3 size={24} />
              Overall Equipment Effectiveness (OEE)
            </h2>
          </TooltipTrigger>
          <TooltipContent>Measure of manufacturing productivity</TooltipContent>
        </Tooltip>
        <div className="flex items-center gap-3">
          <Tooltip>
            <TooltipTrigger asChild>
              <div className="text-sm text-opsgrid-text-secondary">
                {fleetOEE?.timeRange || 'Last 24 hours'}
              </div>
            </TooltipTrigger>
            <TooltipContent>Time range for OEE calculation</TooltipContent>
          </Tooltip>
          {isAdmin && (
            <ExportButton
              endpoint="/api/v1/exports/oee/summary"
              params={{ time_window_hours: 24 }}
              format="pdf"
              label="Export PDF"
              filename="oee_summary.pdf"
            />
          )}
        </div>
      </div>

      {/* Fleet Summary */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <Tooltip>
          <TooltipTrigger asChild>
            <div className="bg-opsgrid-panel border border-opsgrid-border rounded-lg p-6">
              <div className="flex items-center gap-3 mb-2">
                <Clock className="text-opsgrid-primary" size={24} />
                <p className="text-opsgrid-text-secondary">Availability</p>
              </div>
              <p className="text-3xl font-bold">
                {fleetOEE?.fleetAverageAvailability == null
                  ? '—'
                  : `${(fleetOEE.fleetAverageAvailability * 100).toFixed(1)}%`}
              </p>
              <p className="text-sm text-opsgrid-text-secondary mt-1">
                Time equipment was available to run
              </p>
            </div>
          </TooltipTrigger>
          <TooltipContent>Percentage of scheduled time equipment is available for production</TooltipContent>
        </Tooltip>

        <Tooltip>
          <TooltipTrigger asChild>
            <div className="bg-opsgrid-panel border border-opsgrid-border rounded-lg p-6">
              <div className="flex items-center gap-3 mb-2">
                <TrendingUp className="text-packml-execute" size={24} />
                <p className="text-opsgrid-text-secondary">Performance</p>
              </div>
              <p className="text-3xl font-bold">
                {((fleetAveragePerformance ?? NaN) * 100 || 100).toFixed(1)}%
              </p>
              <p className="text-sm text-opsgrid-text-secondary mt-1">
                Speed vs ideal cycle time
              </p>
            </div>
          </TooltipTrigger>
          <TooltipContent>Actual production speed compared to ideal cycle time</TooltipContent>
        </Tooltip>

        <Tooltip>
          <TooltipTrigger asChild>
            <div className="bg-opsgrid-panel border border-opsgrid-border rounded-lg p-6">
              <div className="flex items-center gap-3 mb-2">
                <BarChart3 className="text-status-running" size={24} />
                <p className="text-opsgrid-text-secondary">Fleet Availability</p>
              </div>
              <p className="text-3xl font-bold">
                {fleetOEE?.fleetAverageAvailability == null
                  ? '—'
                  : `${(fleetOEE.fleetAverageAvailability * 100).toFixed(1)}%`}
              </p>
              <p className="text-sm text-opsgrid-text-secondary mt-1">
                Run time ÷ planned time — not full OEE
              </p>
            </div>
          </TooltipTrigger>
          <TooltipContent>Overall Equipment Effectiveness: A × P × Q</TooltipContent>
        </Tooltip>
      </div>

      {/* Asset OEE Table */}
      <div className="bg-opsgrid-panel border border-opsgrid-border rounded-lg">
        <div className="p-4 border-b border-opsgrid-border">
          <h3 className="text-lg font-semibold">
            Asset OEE Breakdown ({fleetOEE?.assetCount || 0} assets)
          </h3>
        </div>
        
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr className="bg-opsgrid-bg">
                <Tooltip>
                  <TooltipTrigger asChild>
                    <th className="text-left p-4 text-opsgrid-text-secondary font-medium">Asset</th>
                  </TooltipTrigger>
                  <TooltipContent>Asset name and identifier</TooltipContent>
                </Tooltip>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <th className="text-center p-4 text-opsgrid-text-secondary font-medium">Availability</th>
                  </TooltipTrigger>
                  <TooltipContent>Asset availability percentage</TooltipContent>
                </Tooltip>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <th className="text-center p-4 text-opsgrid-text-secondary font-medium">OEE</th>
                  </TooltipTrigger>
                  <TooltipContent>Overall Equipment Effectiveness score</TooltipContent>
                </Tooltip>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <th className="text-right p-4 text-opsgrid-text-secondary font-medium">Status</th>
                  </TooltipTrigger>
                  <TooltipContent>Performance status indicator</TooltipContent>
                </Tooltip>
              </tr>
            </thead>
            <tbody className="divide-y divide-opsgrid-border">
              {fleetOEE?.assets?.map((asset: any) => {
                const isExpanded = expandedId === asset.assetId
                const toggle = () => setExpandedId(isExpanded ? null : asset.assetId)
                return (
                <Fragment key={asset.assetId}>
                <tr
                  className="hover:bg-opsgrid-bg/50 cursor-pointer"
                  role="button"
                  tabIndex={0}
                  aria-expanded={isExpanded}
                  onClick={toggle}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                      e.preventDefault()
                      toggle()
                    }
                  }}
                >
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <td className="p-4">
                        <div className="flex items-center gap-2">
                          {isExpanded ? (
                            <ChevronDown size={16} className="text-opsgrid-text-secondary shrink-0" />
                          ) : (
                            <ChevronRight size={16} className="text-opsgrid-text-secondary shrink-0" />
                          )}
                          <div>
                            <p className="font-medium">{asset.assetName}</p>
                            <p className="text-sm text-opsgrid-text-secondary">{asset.assetId}</p>
                          </div>
                        </div>
                      </td>
                    </TooltipTrigger>
                    <TooltipContent>Click to view detailed OEE metrics for {asset.assetName}</TooltipContent>
                  </Tooltip>
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <td className="p-4 text-center">
                        <div className="flex items-center justify-center gap-2">
                          <div className="w-24 h-2 bg-opsgrid-bg rounded-full overflow-hidden">
                            <div
                              className="h-full bg-opsgrid-primary"
                              style={{ width: `${asset.availability * 100}%` }}
                            />
                          </div>
                          <span className="text-sm">{(asset.availability * 100).toFixed(1)}%</span>
                        </div>
                      </td>
                    </TooltipTrigger>
                    <TooltipContent>Availability: {(asset.availability * 100).toFixed(1)}%</TooltipContent>
                  </Tooltip>
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <td className="p-4 text-center">
                        <span
                          className={`font-semibold ${
                            asset.oee > 0.8
                              ? 'text-status-running'
                              : asset.oee > 0.5
                              ? 'text-packml-held'
                              : 'text-status-alarm'
                          }`}
                        >
                          {(asset.oee * 100).toFixed(1)}%
                        </span>
                      </td>
                    </TooltipTrigger>
                    <TooltipContent>
                      {asset.oee > 0.8 ? 'Excellent performance' : asset.oee > 0.5 ? 'Good performance' : 'Needs improvement'}
                    </TooltipContent>
                  </Tooltip>
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <td className="p-4 text-right">
                        <span
                          className={`inline-block w-3 h-3 rounded-full ${
                            asset.oee > 0.8
                              ? 'bg-status-running'
                              : asset.oee > 0.5
                              ? 'bg-packml-held'
                              : 'bg-status-alarm'
                          }`}
                        />
                      </td>
                    </TooltipTrigger>
                    <TooltipContent>
                      {asset.oee > 0.8 ? 'Running well' : asset.oee > 0.5 ? 'Needs attention' : 'Critical'}
                    </TooltipContent>
                  </Tooltip>
                </tr>
                {isExpanded && (
                  <tr className="bg-opsgrid-bg/30">
                    <td colSpan={4} className="p-4">
                      <OEEDetailPanel assetId={asset.assetId} assetName={asset.assetName} />
                    </td>
                  </tr>
                )}
                </Fragment>
                )
              })}
            </tbody>
          </table>
        </div>
        
        {fleetOEE?.assets?.length === 0 && (
          <div className="p-8 text-center text-opsgrid-text-secondary">
            No OEE data available
          </div>
        )}
      </div>
    </div>
  )
}

// Inline per-asset OEE breakdown, fetched on expand via the existing
// /dashboard/assets/:id/oee endpoint (dashboardApi.getAssetOEE).
const OEEDetailPanel: FC<{ assetId: string; assetName: string }> = ({ assetId, assetName }) => {
  const { data, isLoading, isError } = useQuery({
    queryKey: ['asset-oee', assetId],
    queryFn: () => dashboardApi.getAssetOEE(assetId),
  })

  if (isLoading) {
    return <div className="text-sm text-opsgrid-text-secondary">Loading OEE detail for {assetName}…</div>
  }
  if (isError || !data) {
    return <div className="text-sm text-status-alarm">Couldn’t load OEE detail for {assetName}.</div>
  }

  const pct = (v: number) => `${((v ?? 0) * 100).toFixed(1)}%`

  // A factor the server could not measure comes back as 1.0 — the neutral multiplier
  // for the OEE product, which is the correct arithmetic and the wrong thing to print.
  // "100%" reads as a perfect score; this is the absence of a measurement. The server
  // has flagged the difference since FS-234 and nothing read the flags, so an asset
  // with no part counters displayed flawless quality.
  //
  // Absent flags are treated as measured: older responses predate them, and defaulting
  // the other way would put "—" on every asset in a deployment that is fine.
  const qualityMeasured = data.qualityMeasured !== false
  const performanceMeasured = data.performanceMeasured !== false
  // OEE is Availability × Performance × Quality, so it inherits any stand-in: with
  // either factor unmeasured the product is an upper bound, not a result.
  const oeeIsBounded = !qualityMeasured || !performanceMeasured

  const factors: Array<{
    label: string
    value: number
    hint: string
    measured: boolean
  }> = [
    {
      label: 'Availability',
      value: data.availability,
      hint: 'Uptime vs planned time',
      measured: true,
    },
    {
      label: 'Performance',
      value: data.performance,
      hint: performanceMeasured
        ? 'Speed vs ideal cycle time'
        : 'No ideal cycle time recorded for this asset',
      measured: performanceMeasured,
    },
    {
      label: 'Quality',
      value: data.quality,
      hint: qualityMeasured
        ? `Good units vs total${
            data.totalParts ? ` (${data.goodParts ?? 0}/${data.totalParts})` : ''
          }`
        : 'No part counters reporting for this asset',
      measured: qualityMeasured,
    },
    {
      label: oeeIsBounded ? 'OEE (upper bound)' : 'OEE',
      value: data.oee,
      hint: oeeIsBounded
        ? 'Unmeasured factors count as 100%, so the real figure is lower'
        : 'Availability × Performance × Quality',
      measured: true,
    },
  ]

  const states = Object.entries(data.stateDurations ?? {})
    .filter(([, seconds]) => seconds > 0)
    .sort((a, b) => b[1] - a[1])
  const fmtDuration = (seconds: number) => {
    const h = Math.floor(seconds / 3600)
    const m = Math.round((seconds % 3600) / 60)
    return h > 0 ? `${h}h ${m}m` : `${m}m`
  }

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {factors.map((f) => (
          <div key={f.label} className="rounded-lg border border-opsgrid-border p-3">
            <p className="text-xs text-opsgrid-text-secondary">{f.label}</p>
            <p
              className={`text-2xl font-semibold ${
                f.measured ? '' : 'text-opsgrid-text-secondary'
              }`}
              title={f.measured ? undefined : 'Not measured'}
            >
              {f.measured ? pct(f.value) : '—'}
            </p>
            <p className="text-xs text-opsgrid-text-secondary mt-1">{f.hint}</p>
          </div>
        ))}
      </div>

      <div>
        <p className="text-sm font-medium mb-2">
          State breakdown{data.timeRange ? ` · ${data.timeRange}` : ''}
        </p>
        {states.length === 0 ? (
          <p className="text-sm text-opsgrid-text-secondary">
            No recorded state time in this window (expected offline — PackML state comes from a live edge agent).
          </p>
        ) : (
          <div className="space-y-1.5">
            {states.map(([state, seconds]) => {
              const share = data.totalPlannedTimeSeconds
                ? (seconds / data.totalPlannedTimeSeconds) * 100
                : 0
              return (
                <div key={state} className="flex items-center gap-3 text-sm">
                  <span className="w-28 shrink-0 capitalize">{state?.replace(/_/g, ' ')}</span>
                  <div className="flex-1 h-2 bg-opsgrid-bg rounded-full overflow-hidden">
                    <div className="h-full bg-opsgrid-primary" style={{ width: `${Math.min(share, 100)}%` }} />
                  </div>
                  <span className="w-16 text-right text-opsgrid-text-secondary">{fmtDuration(seconds)}</span>
                </div>
              )
            })}
          </div>
        )}
      </div>
    </div>
  )
}

export default OEE

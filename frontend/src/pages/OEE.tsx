import { FC, Fragment, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { BarChart3, TrendingUp, Clock, ChevronDown, ChevronRight } from 'lucide-react'
import { dashboardApi } from '../api'
import { OEEDetailPanel } from '../components/oee'
import { Button, Tooltip, TooltipTrigger, TooltipContent } from '../components/ui'
import { ExportButton } from '../components/common'
import { useAuth } from '../hooks/useAuth'

// P8 (page-enhancement review): the page was pinned to the endpoint's 24h default with
// no control, and the PDF export hardcoded `time_window_hours: 24` beside it — so an
// export could not disagree with the table because neither could move. One selector now
// drives the fleet query, the per-asset panels and the export together.
const RANGES: { key: string; label: string; hours: number }[] = [
  { key: '8h', label: 'Last 8 hours', hours: 8 },
  { key: '24h', label: 'Last 24 hours', hours: 24 },
  { key: '7d', label: 'Last 7 days', hours: 24 * 7 },
]

const OEE: FC = () => {
  const { isAdmin } = useAuth()
  // Clicking a row expands an inline OEE breakdown for that asset (the row
  // tooltip has always promised this; the handler was never wired).
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const [range, setRange] = useState('24h')
  const hours = RANGES.find((r) => r.key === range)?.hours ?? 24
  const { data: fleetOEE, isLoading, isError, refetch } = useQuery({
    queryKey: ['fleet-oee', hours],
    queryFn: () => dashboardApi.getFleetOEE(hours),
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
          <select
            aria-label="Time range"
            value={range}
            onChange={(e) => setRange(e.target.value)}
            className="bg-opsgrid-bg border border-opsgrid-border rounded px-2 py-1.5 text-sm text-opsgrid-text focus:border-opsgrid-primary focus:outline-none"
          >
            {RANGES.map((r) => (
              <option key={r.key} value={r.key}>{r.label}</option>
            ))}
          </select>
          {isAdmin && (
            <ExportButton
              endpoint="/api/v1/exports/oee/summary"
              params={{ time_window_hours: hours }}
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
              {/* NOT `(asset: any)`. The `FleetOEE` type already described these rows
                  correctly — four fields, no `oee` — and the `any` is the only reason
                  `asset.oee` compiled at all. Typed, the compiler rejects it. */}
              {fleetOEE?.assets?.map((asset) => {
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
                  {/* THIS ENDPOINT DOES NOT COMPUTE OEE (FS-399). `/dashboard/fleet/oee`
                      returns `{assetId, assetName, availability, availabilityOnly}` and
                      sets `availabilityOnly: true` to say so explicitly. `asset.oee` was
                      never on the wire, so this rendered `NaN%` — and the ternaries below
                      it, comparing `undefined > 0.8`, fell through to their last branch.
                      Three-factor OEE comes from `/dashboard/assets/{id}/oee`, as the
                      `FleetOEE` type's own docstring says. */}
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <td className="p-4 text-center">
                        <span className="font-semibold text-opsgrid-text-secondary">—</span>
                      </td>
                    </TooltipTrigger>
                    <TooltipContent>
                      Not computed by the fleet endpoint — it reports availability only.
                      Expand the row for this asset&apos;s three-factor OEE.
                    </TooltipContent>
                  </Tooltip>
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <td className="p-4 text-right">
                        {/* DRIVEN BY AVAILABILITY, WHICH IS WHAT THIS ENDPOINT MEASURES.
                            It read `asset.oee`, so every comparison was against `undefined`
                            and every asset in the fleet got the red alarm dot and the word
                            "Critical" — a fleet-wide fault verdict manufactured from a
                            field nobody sends. Same shape as the geofence-alert ternary
                            that made every alert read "Violation". */}
                        <span
                          className={`inline-block w-3 h-3 rounded-full ${
                            asset.availability > 0.8
                              ? 'bg-status-running'
                              : asset.availability > 0.5
                              ? 'bg-packml-held'
                              : 'bg-status-alarm'
                          }`}
                        />
                      </td>
                    </TooltipTrigger>
                    <TooltipContent>
                      {asset.availability > 0.8
                        ? 'Available'
                        : asset.availability > 0.5
                        ? 'Reduced availability'
                        : 'Little or no run time'}
                      {' '}(availability only — this endpoint does not compute OEE)
                    </TooltipContent>
                  </Tooltip>
                </tr>
                {isExpanded && (
                  <tr className="bg-opsgrid-bg/30">
                    <td colSpan={4} className="p-4">
                      <OEEDetailPanel
                        assetId={asset.assetId}
                        assetName={asset.assetName}
                        hours={hours}
                      />
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
export default OEE

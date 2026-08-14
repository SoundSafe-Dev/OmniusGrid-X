import { FC } from 'react'
import { useQuery } from '@tanstack/react-query'
import { dashboardApi, oeeApi } from '../../api'

/**
 * Three-factor OEE for one asset, rendered HONESTLY (extracted for P7).
 *
 * This lived inside `pages/OEE.tsx` as a local component, so the asset page — where an
 * operator actually stands when asking "how is this machine doing" — had no OEE at all
 * while the fleet table had a good one. Extracted rather than copied: the conventions
 * below are the content, and a second copy would drift from them.
 *
 * The conventions, each bought by a finding: a factor the server could not measure comes
 * back as 1.0 (the neutral multiplier — correct arithmetic, wrong thing to print), so an
 * unmeasured factor renders "—" and not "100%"; OEE inherits any stand-in and is labelled
 * an upper bound when it does; and absent measured-flags are treated as measured, because
 * an older server predates them and defaulting the other way would dash every asset in a
 * healthy deployment.
 */
export const OEEDetailPanel: FC<{
  assetId: string
  assetName: string
  /** Window in hours. The fleet table expands at the endpoint's own default; the
   *  asset page and the OEE page's range selector pass their chosen window. */
  hours?: number
}> = ({ assetId, assetName, hours }) => {
  const { data, isLoading, isError } = useQuery({
    queryKey: ['asset-oee', assetId, hours ?? 'default'],
    queryFn: () => dashboardApi.getAssetOEE(assetId, hours),
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

      <OEELossBreakdown assetId={assetId} hours={hours} />
    </div>
  )
}

/**
 * Where the OEE is going (P8) — `GET /api/v1/oee/losses/{asset}`, an endpoint that had
 * no frontend caller at all. "Where is my OEE going" is the question the number exists
 * to raise, and until now the product could not answer it.
 *
 * The three losses are INDEPENDENT factors summed, not shares of a whole — the server
 * says so in its own comment, and the total can exceed 100. So the bars are scaled to
 * the largest loss, not to 100 or to the total: a stacked bar or a percent-of-total pie
 * would be drawing an arithmetic that does not exist.
 */
const OEELossBreakdown: FC<{ assetId: string; hours?: number }> = ({ assetId, hours }) => {
  const { data, isLoading, isError } = useQuery({
    queryKey: ['asset-oee-losses', assetId, hours ?? 'default'],
    queryFn: () => oeeApi.getLosses(assetId, hours),
  })

  if (isLoading) {
    return <p className="text-sm text-opsgrid-text-secondary">Loading loss breakdown…</p>
  }
  // Stated, not hidden: an absent breakdown is a failed request or a mock-mode
  // deployment, never "this asset has no losses".
  if (isError || !data) {
    return (
      <p className="text-sm text-opsgrid-text-secondary">
        Loss breakdown unavailable — this is a failed request, not a lossless machine.
      </p>
    )
  }

  const rows = [
    {
      label: 'Availability',
      percentage: data.losses.availability.percentage,
      detail: `${Math.round(data.losses.availability.minutes)} min down · ${data.losses.availability.category}`,
    },
    {
      label: 'Performance',
      percentage: data.losses.performance.percentage,
      detail: `${data.losses.performance.impact} · ${data.losses.performance.category}`,
    },
    {
      label: 'Quality',
      percentage: data.losses.quality.percentage,
      detail:
        data.losses.quality.totalParts
          ? `${data.losses.quality.rejectedParts ?? 0}/${data.losses.quality.totalParts} rejected · ${data.losses.quality.category}`
          : data.losses.quality.category,
    },
  ].sort((a, b) => b.percentage - a.percentage) // Pareto: biggest loss first

  const largest = Math.max(...rows.map((r) => r.percentage), 1)

  return (
    <div>
      <p className="text-sm font-medium mb-2">
        Loss breakdown · biggest first
        {data.periodHours ? ` · last ${data.periodHours}h` : ''}
      </p>
      <div className="space-y-1.5">
        {rows.map((row) => (
          <div key={row.label} className="flex items-center gap-3 text-sm">
            <span className="w-28 shrink-0">{row.label}</span>
            <div className="flex-1 h-2 bg-opsgrid-bg rounded-full overflow-hidden">
              <div
                className="h-full bg-status-warning"
                style={{ width: `${Math.min((row.percentage / largest) * 100, 100)}%` }}
              />
            </div>
            <span className="w-14 text-right text-opsgrid-text-secondary">
              {row.percentage.toFixed(1)}%
            </span>
          </div>
        ))}
      </div>
      <p className="text-xs text-opsgrid-text-secondary mt-2">
        {/* NOT a percentage of anything: three independent factors added together, which
            is why the bars scale to the largest loss rather than to 100. */}
        Recover all three and OEE would be {data.potentialOee.toFixed(1)}%.
        The three losses are independent factors, so they sum to {data.totalLossPercentage.toFixed(1)}
        {' '}rather than to a share of 100.
      </p>
    </div>
  )
}

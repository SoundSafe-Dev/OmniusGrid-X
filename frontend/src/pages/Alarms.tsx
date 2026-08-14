import { FC, useMemo, useState } from 'react'
import { AlertTriangle, CheckCircle, Bell, CheckCheck, X } from 'lucide-react'
import { Link } from 'react-router-dom'
import {
  useAlarms,
  useActiveAlarms,
  useAcknowledgeAlarm,
  useAcknowledgeAllAlarms,
  useClearAlarm,
  useAssets,
} from '../hooks'
import { Tooltip, TooltipTrigger, TooltipContent } from '../components/ui'
import type { AlarmSeverity } from '../types'

// The backend defaults to the last 24 hours when no time range is sent, so the range
// selector always sends an explicit start_time — including for "All time", which sends
// the epoch. Before this control existed the page sent nothing and the "Total Alarms"
// tile showed a silent 24h count under an "All alarms in system history" tooltip.
const RANGES: { key: string; label: string; hours: number | null }[] = [
  { key: '24h', label: 'Last 24h', hours: 24 },
  { key: '7d', label: 'Last 7 days', hours: 24 * 7 },
  { key: '30d', label: 'Last 30 days', hours: 24 * 30 },
  { key: 'all', label: 'All time', hours: null },
]

const EPOCH_ISO = new Date(0).toISOString()

const Alarms: FC = () => {
  // FS-127: page through the FS-82 envelope. Page size comes from the limit the
  // backend echoes back; skip is part of the queryKey via the hook's filters.
  const [skip, setSkip] = useState(0)

  // Filter bar (page-enhancement P1). Every value here maps onto a query param
  // `alarmsApi.list` already supported and the page never sent — the whole
  // filter feature is a wire, not a backend change.
  const [severity, setSeverity] = useState<AlarmSeverity | ''>('')
  const [status, setStatus] = useState('') // '' | 'active' | 'cleared'
  const [acked, setAcked] = useState('') // '' | 'yes' | 'no'
  const [assetId, setAssetId] = useState('')
  const [range, setRange] = useState('24h')

  const startTime = useMemo(() => {
    const hours = RANGES.find((r) => r.key === range)?.hours
    if (hours == null) return EPOCH_ISO
    return new Date(Date.now() - hours * 3600 * 1000).toISOString()
  }, [range])

  const filters = useMemo(
    () => ({
      skip,
      severity: severity || undefined,
      isActive: status === '' ? undefined : status === 'active',
      acknowledged: acked === '' ? undefined : acked === 'yes',
      assetId: assetId || undefined,
      startTime,
    }),
    [skip, severity, status, acked, assetId, startTime],
  )

  const { data: alarmsData, isLoading, isError } = useAlarms(filters)
  const alarms = alarmsData?.items || []
  const total = alarmsData?.total ?? 0
  const limit = alarmsData?.limit || alarms.length || 1
  const rangeStart = total === 0 ? 0 : (alarmsData?.skip ?? skip) + 1
  const rangeEnd = (alarmsData?.skip ?? skip) + alarms.length
  const rangeLabel = RANGES.find((r) => r.key === range)?.label ?? range

  // Asset filter options. 200 covers the fleets this deploys to today; the dropdown
  // shows a truncation hint rather than silently narrowing the filter if it grows past
  // that (the FleetOverview 500-cap lesson).
  const { data: assetsPage } = useAssets({ limit: 200 })

  const anyFilterActive = severity !== '' || status !== '' || acked !== '' || assetId !== '' || range !== '24h'
  const setFilter = (setter: (v: any) => void) => (value: string) => {
    setter(value)
    setSkip(0) // a new filter starts from page one, or the range text lies
  }

  // `isError`, not just `data`. This polls every ten seconds and react-query keeps the last
  // successful `data` across a failure, so both cards below reported a count from an unknown
  // time ago — and on a cold failure `activeAlarms?.count || 0` is 0, which renders "Active 0"
  // and, worse, "Acknowledged {total}": a feed that never answered says every alarm on the
  // page has been dealt with. This is the page an operator opens BECAUSE they are worried.
  const { data: activeAlarms, isError: activeCountUnavailable } = useActiveAlarms()
  const activeCount = activeCountUnavailable ? null : activeAlarms?.count ?? null

  // Invalidates the shared ['alarms'] key, refreshing both list and active queries.
  const acknowledgeMutation = useAcknowledgeAlarm()
  const acknowledgeAllMutation = useAcknowledgeAllAlarms()
  const clearMutation = useClearAlarm()
  // A failed acknowledgement said nothing (FS-480). The row stays exactly as it was —
  // which is what it looks like for the moment before the list refetches — so the
  // reasonable reading is that it worked. On a critical alarm that means somebody believes
  // it is acknowledged and nobody is coming. The same banner now carries clear and
  // acknowledge-all failures for the same reason.
  const [ackError, setAckError] = useState<string | null>(null)

  // Acknowledge-with-note: one row at a time expands into a note input. The plain
  // Acknowledge button stays one-click — floor speed first, paperwork optional.
  const [noteFor, setNoteFor] = useState<string | null>(null)
  const [noteText, setNoteText] = useState('')

  const acknowledge = (alarm: any, comment?: string) => {
    setAckError(null)
    acknowledgeMutation.mutate(
      { alarmId: alarm.id, comment: comment || undefined },
      {
        onError: () =>
          setAckError(
            `Could not acknowledge "${alarm.message ?? alarm.id}". It is still unacknowledged.`,
          ),
        onSuccess: () => {
          setNoteFor(null)
          setNoteText('')
        },
      },
    )
  }

  const getSeverityColor = (severity: string) => {
    switch (severity) {
      case 'critical':
        return 'bg-status-alarm text-white'
      case 'high':
        return 'bg-status-warning text-opsgrid-bg'
      case 'medium':
        return 'bg-packml-held text-opsgrid-bg'
      default:
        return 'bg-opsgrid-text-secondary text-opsgrid-bg'
    }
  }

  const getSeverityDescription = (severity: string) => {
    switch (severity) {
      case 'critical': return 'Critical: Immediate action required, potential safety issue';
      case 'high': return 'High: Prompt action required';
      case 'medium': return 'Medium: Address soon';
      case 'low': return 'Low: Monitor, no immediate action';
      default: return severity;
    }
  }

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="text-opsgrid-text-secondary">Loading...</div>
      </div>
    )
  }

  // A failed fetch previously rendered the header over an empty list — a blank
  // screen with no error indication.
  if (isError) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="text-center">
          <p className="text-status-alarm">Failed to load alarms.</p>
          <p className="text-sm text-opsgrid-text-secondary mt-1">
            Check your connection and try again.
          </p>
        </div>
      </div>
    )
  }

  const selectClass =
    'bg-opsgrid-bg border border-opsgrid-border rounded px-2 py-1.5 text-sm text-opsgrid-text focus:border-opsgrid-primary focus:outline-none'

  return (
    <div className="space-y-6">
      {/* A failed acknowledgement, said out loud (FS-480). Above the summary so it is
          visible without scrolling to the row that failed. */}
      {ackError && (
        <div
          role="alert"
          className="rounded border border-status-alarm/40 bg-status-alarm/10 px-3 py-2 text-sm text-status-alarm"
        >
          {ackError}
        </div>
      )}

      {/* Summary Cards */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <Tooltip>
          <TooltipTrigger asChild>
            <div className="bg-opsgrid-panel border border-opsgrid-border rounded-lg p-4">
              <div className="flex items-center gap-3">
                <Bell className="text-opsgrid-primary" size={24} />
                <div>
                  <p className="text-sm text-opsgrid-text-secondary">
                    Alarms ({rangeLabel.toLowerCase()})
                  </p>
                  <p className="text-2xl font-bold">{total}</p>
                </div>
              </div>
            </div>
          </TooltipTrigger>
          {/* The tile names its window. It used to say "All alarms in system history"
              over a backend that silently defaulted to the last 24 hours. */}
          <TooltipContent>Alarms matching the current filters, {rangeLabel.toLowerCase()}</TooltipContent>
        </Tooltip>

        <Tooltip>
          <TooltipTrigger asChild>
            <div className="bg-opsgrid-panel border border-opsgrid-border rounded-lg p-4">
              <div className="flex items-center gap-3">
                <AlertTriangle className="text-status-alarm" size={24} />
                <div>
                  <p className="text-sm text-opsgrid-text-secondary">Active</p>
                  <p className="text-2xl font-bold">
                    {activeCount ?? <span className="text-opsgrid-text-secondary">—</span>}
                  </p>
                </div>
              </div>
            </div>
          </TooltipTrigger>
          <TooltipContent>Currently active, unacknowledged alarms</TooltipContent>
        </Tooltip>

        <Tooltip>
          <TooltipTrigger asChild>
            <div className="bg-opsgrid-panel border border-opsgrid-border rounded-lg p-4">
              <div className="flex items-center gap-3">
                <CheckCircle className="text-status-running" size={24} />
                <div className="flex-1">
                  <p className="text-sm text-opsgrid-text-secondary">Bulk actions</p>
                  {/* No number here on purpose. The old tile derived
                      `total - activeCount`, which mixed a filtered-window total with a
                      global active count — a subtraction whose meaning changed with
                      every filter. An action belongs here; a scope-mixed number does not. */}
                  {activeCount === null ? (
                    <p className="text-2xl font-bold text-opsgrid-text-secondary">—</p>
                  ) : activeCount === 0 ? (
                    <p className="text-sm text-opsgrid-text-secondary mt-1.5">
                      Nothing active to acknowledge
                    </p>
                  ) : (
                    <button
                      onClick={() => {
                        setAckError(null)
                        acknowledgeAllMutation.mutate(
                          { severity: severity || undefined },
                          {
                            onError: () =>
                              setAckError(
                                'Could not acknowledge all alarms. They are still unacknowledged.',
                              ),
                          },
                        )
                      }}
                      disabled={acknowledgeAllMutation.isPending}
                      className="mt-1 flex items-center gap-1 px-3 py-1.5 text-sm rounded border border-opsgrid-border text-opsgrid-text-secondary hover:border-opsgrid-primary hover:text-opsgrid-primary disabled:opacity-40"
                    >
                      <CheckCheck size={16} />
                      {acknowledgeAllMutation.isPending
                        ? 'Acknowledging…'
                        : severity
                          ? `Acknowledge all ${severity}`
                          : 'Acknowledge all'}
                    </button>
                  )}
                </div>
              </div>
            </div>
          </TooltipTrigger>
          <TooltipContent>
            Acknowledge-all scopes to the severity filter when one is set
          </TooltipContent>
        </Tooltip>
      </div>

      {/* Alarms List */}
      <div className="bg-opsgrid-panel border border-opsgrid-border rounded-lg">
        <div className="p-4 border-b border-opsgrid-border space-y-3">
          <div className="flex items-center justify-between">
            <Tooltip>
              <TooltipTrigger asChild>
                <h2 className="text-lg font-semibold">Alarm History</h2>
              </TooltipTrigger>
              <TooltipContent>Alarm history for the selected window and filters</TooltipContent>
            </Tooltip>
            {anyFilterActive && (
              <button
                onClick={() => {
                  setSeverity('')
                  setStatus('')
                  setAcked('')
                  setAssetId('')
                  setRange('24h')
                  setSkip(0)
                }}
                className="flex items-center gap-1 text-sm text-opsgrid-text-secondary hover:text-opsgrid-primary"
              >
                <X size={14} /> Reset filters
              </button>
            )}
          </div>

          {/* Every control below maps 1:1 onto a query param the API client already
              supported (severity / is_active / acknowledged / asset_id / start_time). */}
          <div className="flex flex-wrap items-center gap-2">
            <select
              aria-label="Time range"
              value={range}
              onChange={(e) => setFilter(setRange)(e.target.value)}
              className={selectClass}
            >
              {RANGES.map((r) => (
                <option key={r.key} value={r.key}>{r.label}</option>
              ))}
            </select>

            <select
              aria-label="Severity"
              value={severity}
              onChange={(e) => setFilter(setSeverity)(e.target.value)}
              className={selectClass}
            >
              <option value="">All severities</option>
              <option value="critical">Critical</option>
              <option value="high">High</option>
              <option value="medium">Medium</option>
              <option value="low">Low</option>
            </select>

            <select
              aria-label="Status"
              value={status}
              onChange={(e) => setFilter(setStatus)(e.target.value)}
              className={selectClass}
            >
              <option value="">Active + cleared</option>
              <option value="active">Active only</option>
              <option value="cleared">Cleared only</option>
            </select>

            <select
              aria-label="Acknowledgement"
              value={acked}
              onChange={(e) => setFilter(setAcked)(e.target.value)}
              className={selectClass}
            >
              <option value="">Acked + unacked</option>
              <option value="no">Unacknowledged</option>
              <option value="yes">Acknowledged</option>
            </select>

            <select
              aria-label="Asset"
              value={assetId}
              onChange={(e) => setFilter(setAssetId)(e.target.value)}
              className={selectClass}
            >
              <option value="">All assets</option>
              {(assetsPage?.items ?? []).map((asset: any) => (
                <option key={asset.id} value={asset.id}>{asset.name}</option>
              ))}
              {assetsPage?.hasMore && (
                <option value="" disabled>
                  …list truncated at {assetsPage.items.length}
                </option>
              )}
            </select>
          </div>
        </div>

        <div className="divide-y divide-opsgrid-border">
          {alarms?.map((alarm: any) => (
            <div
              key={alarm.id}
              className={`p-4 flex items-center justify-between ${
                alarm.isActive ? 'bg-opsgrid-bg/50' : ''
              }`}
            >
              <div className="flex items-center gap-4">
                <Tooltip>
                  <TooltipTrigger asChild>
                    <span
                      className={`px-2 py-1 rounded text-xs font-medium ${getSeverityColor(
                        alarm.severity
                      )}`}
                    >
                      {alarm.severity}
                    </span>
                  </TooltipTrigger>
                  <TooltipContent>{getSeverityDescription(alarm.severity)}</TooltipContent>
                </Tooltip>

                <div>
                  <p className="font-medium">{alarm.message}</p>
                  {/* THE MACHINE, first (FS-448). This line read
                      `{alarmCode} • {occurredAt}` and named no asset at all — on the
                      dedicated alarms screen, where deciding what to do about an alarm
                      begins with knowing where to walk. The dashboard panel was given
                      `assetName` in FS-436 and `/api/v1/alarms/` has sent `asset_name`
                      since the same commit; the data was arriving here and nothing
                      rendered it.

                      Falls back to the code alone rather than printing a UUID or an empty
                      separator: the name is resolved by join and is null when the asset is
                      gone, and a bullet with nothing before it is what FS-436 was.

                      The name now LINKS to the asset (P1): the walk starts here. */}
                  <p className="text-sm text-opsgrid-text-secondary">
                    {alarm.assetName && alarm.assetId ? (
                      <>
                        <Link
                          to={`/assets/${alarm.assetId}`}
                          className="hover:text-opsgrid-primary underline-offset-2 hover:underline"
                        >
                          {alarm.assetName}
                        </Link>
                        {' • '}
                      </>
                    ) : alarm.assetName ? (
                      `${alarm.assetName} • `
                    ) : (
                      ''
                    )}
                    {alarm.alarmCode} • {new Date(alarm.occurredAt).toLocaleString()}
                  </p>
                </div>
              </div>

              <div className="flex items-center gap-4">
                <Tooltip>
                  <TooltipTrigger asChild>
                    <span
                      className={`px-2 py-1 rounded text-xs ${
                        alarm.isActive
                          ? 'bg-status-alarm/20 text-status-alarm'
                          : 'bg-status-running/20 text-status-running'
                      }`}
                    >
                      {alarm.isActive ? 'Active' : 'Cleared'}
                    </span>
                  </TooltipTrigger>
                  <TooltipContent>{alarm.isActive ? 'Alarm is currently active' : 'Alarm has been cleared'}</TooltipContent>
                </Tooltip>

                {alarm.isActive && !alarm.isAcknowledged && noteFor !== alarm.id && (
                  <>
                    <Tooltip>
                      <TooltipTrigger asChild>
                        <button
                          onClick={() => acknowledge(alarm)}
                          className="px-3 py-1 bg-opsgrid-primary text-white rounded text-sm hover:bg-opsgrid-primary/80"
                        >
                          Acknowledge
                        </button>
                      </TooltipTrigger>
                      <TooltipContent>Mark alarm as acknowledged</TooltipContent>
                    </Tooltip>
                    <button
                      onClick={() => {
                        setNoteFor(alarm.id)
                        setNoteText('')
                      }}
                      className="text-sm text-opsgrid-text-secondary hover:text-opsgrid-primary"
                      title="Acknowledge with a note"
                    >
                      + note
                    </button>
                  </>
                )}

                {alarm.isActive && !alarm.isAcknowledged && noteFor === alarm.id && (
                  <div className="flex items-center gap-2">
                    <input
                      autoFocus
                      value={noteText}
                      onChange={(e) => setNoteText(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter') acknowledge(alarm, noteText)
                        if (e.key === 'Escape') setNoteFor(null)
                      }}
                      placeholder="Acknowledgement note"
                      aria-label="Acknowledgement note"
                      className="bg-opsgrid-bg border border-opsgrid-border rounded px-2 py-1 text-sm w-56 focus:border-opsgrid-primary focus:outline-none"
                    />
                    <button
                      onClick={() => acknowledge(alarm, noteText)}
                      className="px-3 py-1 bg-opsgrid-primary text-white rounded text-sm hover:bg-opsgrid-primary/80"
                    >
                      Acknowledge
                    </button>
                    <button
                      onClick={() => setNoteFor(null)}
                      className="text-sm text-opsgrid-text-secondary hover:text-opsgrid-primary"
                      aria-label="Cancel note"
                    >
                      <X size={14} />
                    </button>
                  </div>
                )}

                {alarm.isActive && alarm.isAcknowledged && (
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <button
                        onClick={() => {
                          setAckError(null)
                          clearMutation.mutate(alarm.id, {
                            onError: () =>
                              setAckError(
                                `Could not clear "${alarm.message ?? alarm.id}". It is still active.`,
                              ),
                          })
                        }}
                        className="px-3 py-1 rounded text-sm border border-opsgrid-border text-opsgrid-text-secondary hover:border-opsgrid-primary hover:text-opsgrid-primary"
                      >
                        Clear
                      </button>
                    </TooltipTrigger>
                    <TooltipContent>
                      Mark the condition resolved — the alarm leaves the active list
                    </TooltipContent>
                  </Tooltip>
                )}

                {alarm.isAcknowledged && (
                  <span className="text-sm text-opsgrid-text-secondary">
                    Acknowledged
                  </span>
                )}
              </div>
            </div>
          ))}

          {alarms?.length === 0 && (
            <div className="p-8 text-center text-opsgrid-text-secondary">
              {anyFilterActive ? 'No alarms match the current filters' : 'No alarms found'}
            </div>
          )}
        </div>

        {/* Pagination (FS-127) */}
        {total > 0 && (
          <div className="p-4 border-t border-opsgrid-border flex items-center justify-between">
            <span className="text-sm text-opsgrid-text-secondary">
              {rangeStart}&ndash;{rangeEnd} of {total}
            </span>
            <div className="flex gap-2">
              <button
                onClick={() => setSkip(Math.max(0, skip - limit))}
                disabled={skip === 0}
                className="px-3 py-1 text-sm rounded border border-opsgrid-border text-opsgrid-text-secondary hover:border-opsgrid-primary disabled:opacity-40 disabled:cursor-not-allowed disabled:hover:border-opsgrid-border"
              >
                Previous
              </button>
              <button
                onClick={() => setSkip(skip + limit)}
                disabled={!alarmsData?.hasMore}
                className="px-3 py-1 text-sm rounded border border-opsgrid-border text-opsgrid-text-secondary hover:border-opsgrid-primary disabled:opacity-40 disabled:cursor-not-allowed disabled:hover:border-opsgrid-border"
              >
                Next
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

export default Alarms

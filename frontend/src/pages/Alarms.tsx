import { FC, useState } from 'react'
import { AlertTriangle, CheckCircle, Bell } from 'lucide-react'
import { useAlarms, useActiveAlarms, useAcknowledgeAlarm } from '../hooks'
import { Tooltip, TooltipTrigger, TooltipContent } from '../components/ui'

const Alarms: FC = () => {
  // FS-127: page through the FS-82 envelope. Page size comes from the limit the
  // backend echoes back; skip is part of the queryKey via the hook's filters.
  const [skip, setSkip] = useState(0)
  const { data: alarmsData, isLoading, isError } = useAlarms({ skip })
  const alarms = alarmsData?.items || []
  const total = alarmsData?.total ?? 0
  const limit = alarmsData?.limit || alarms.length || 1
  const rangeStart = total === 0 ? 0 : (alarmsData?.skip ?? skip) + 1
  const rangeEnd = (alarmsData?.skip ?? skip) + alarms.length

  // `isError`, not just `data`. This polls every ten seconds and react-query keeps the last
  // successful `data` across a failure, so both cards below reported a count from an unknown
  // time ago — and on a cold failure `activeAlarms?.count || 0` is 0, which renders "Active 0"
  // and, worse, "Acknowledged {total}": a feed that never answered says every alarm on the
  // page has been dealt with. This is the page an operator opens BECAUSE they are worried.
  const { data: activeAlarms, isError: activeCountUnavailable } = useActiveAlarms()
  const activeCount = activeCountUnavailable ? null : activeAlarms?.count ?? null

  // Invalidates the shared ['alarms'] key, refreshing both list and active queries.
  const acknowledgeMutation = useAcknowledgeAlarm()
  // A failed acknowledgement said nothing (FS-480). The row stays exactly as it was —
  // which is what it looks like for the moment before the list refetches — so the
  // reasonable reading is that it worked. On a critical alarm that means somebody believes
  // it is acknowledged and nobody is coming.
  //
  // The hook lives in `useAlarms.ts` and the sweep that catches this class scanned `.tsx`
  // only, so it was outside the sweep entirely.
  const [ackError, setAckError] = useState<string | null>(null)

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
                  <p className="text-sm text-opsgrid-text-secondary">Total Alarms</p>
                  <p className="text-2xl font-bold">{total}</p>
                </div>
              </div>
            </div>
          </TooltipTrigger>
          <TooltipContent>All alarms in system history</TooltipContent>
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
                <div>
                  <p className="text-sm text-opsgrid-text-secondary">Acknowledged</p>
                  <p className="text-2xl font-bold">
                    {activeCount === null
                      ? <span className="text-opsgrid-text-secondary">—</span>
                      : Math.max(0, total - activeCount)}
                  </p>
                </div>
              </div>
            </div>
          </TooltipTrigger>
          <TooltipContent>Alarms that have been acknowledged</TooltipContent>
        </Tooltip>
      </div>

      {/* Alarms List */}
      <div className="bg-opsgrid-panel border border-opsgrid-border rounded-lg">
        <div className="p-4 border-b border-opsgrid-border">
          <Tooltip>
            <TooltipTrigger asChild>
              <h2 className="text-lg font-semibold">Alarm History</h2>
            </TooltipTrigger>
            <TooltipContent>Complete history of all system alarms</TooltipContent>
          </Tooltip>
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
                      gone, and a bullet with nothing before it is what FS-436 was. */}
                  <p className="text-sm text-opsgrid-text-secondary">
                    {alarm.assetName ? `${alarm.assetName} • ` : ''}
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
                
                {alarm.isActive && !alarm.isAcknowledged && (
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <button
                        onClick={() => {
                          setAckError(null)
                          acknowledgeMutation.mutate(
                            { alarmId: alarm.id },
                            {
                              onError: () =>
                                setAckError(
                                  `Could not acknowledge "${alarm.message ?? alarm.id}". It is still unacknowledged.`,
                                ),
                            },
                          )
                        }}
                        className="px-3 py-1 bg-opsgrid-primary text-white rounded text-sm hover:bg-opsgrid-primary/80"
                      >
                        Acknowledge
                      </button>
                    </TooltipTrigger>
                    <TooltipContent>Mark alarm as acknowledged</TooltipContent>
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
              No alarms found
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

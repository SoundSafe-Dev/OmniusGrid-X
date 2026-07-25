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

  const { data: activeAlarms } = useActiveAlarms()

  // Invalidates the shared ['alarms'] key, refreshing both list and active queries.
  const acknowledgeMutation = useAcknowledgeAlarm()

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
                  <p className="text-2xl font-bold">{activeAlarms?.count || 0}</p>
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
                    {Math.max(0, total - (activeAlarms?.count || 0))}
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
                  <p className="text-sm text-opsgrid-text-secondary">
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
                        onClick={() => acknowledgeMutation.mutate({ alarmId: alarm.id })}
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

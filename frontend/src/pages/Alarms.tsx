import { FC } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, CheckCircle, Bell } from 'lucide-react'
import { alarmsApi } from '../api'
import { Tooltip, TooltipTrigger, TooltipContent } from '../components/ui'

const Alarms: FC = () => {
  const queryClient = useQueryClient()
  
  const { data: alarmsData, isLoading } = useQuery({
    queryKey: ['alarms-list'],
    queryFn: () => alarmsApi.list(),
  })
  const alarms = alarmsData?.items || []

  const { data: activeAlarms } = useQuery({
    queryKey: ['active-alarms'],
    queryFn: () => alarmsApi.getActive(),
  })

  const acknowledgeMutation = useMutation({
    mutationFn: (alarmId: string) => alarmsApi.acknowledge(alarmId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['alarms-list'] })
      queryClient.invalidateQueries({ queryKey: ['active-alarms'] })
    },
  })

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
                  <p className="text-2xl font-bold">{alarms?.length || 0}</p>
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
                    {(alarms?.length || 0) - (activeAlarms?.count || 0)}
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
                        onClick={() => acknowledgeMutation.mutate(alarm.id)}
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
      </div>
    </div>
  )
}

export default Alarms

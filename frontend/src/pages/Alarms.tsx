import { FC } from 'react'
import { useQuery, useMutation, useQueryClient } from 'react-query'
import { AlertTriangle, CheckCircle, Bell } from 'lucide-react'
import { alarmsApi } from '../api'

const Alarms: FC = () => {
  const queryClient = useQueryClient()
  
  const { data: alarmsData, isLoading } = useQuery('alarms-list', () =>
    alarmsApi.list()
  )
  const alarms = alarmsData?.items || []

  const { data: activeAlarms } = useQuery('active-alarms', () =>
    alarmsApi.getActive()
  )

  const acknowledgeMutation = useMutation(
    (alarmId: string) => alarmsApi.acknowledge(alarmId),
    {
      onSuccess: () => {
        queryClient.invalidateQueries('alarms-list')
        queryClient.invalidateQueries('active-alarms')
      },
    }
  )

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
        <div className="bg-opsgrid-panel border border-opsgrid-border rounded-lg p-4">
          <div className="flex items-center gap-3">
            <Bell className="text-opsgrid-primary" size={24} />
            <div>
              <p className="text-sm text-opsgrid-text-secondary">Total Alarms</p>
              <p className="text-2xl font-bold">{alarms?.length || 0}</p>
            </div>
          </div>
        </div>
        
        <div className="bg-opsgrid-panel border border-opsgrid-border rounded-lg p-4">
          <div className="flex items-center gap-3">
            <AlertTriangle className="text-status-alarm" size={24} />
            <div>
              <p className="text-sm text-opsgrid-text-secondary">Active</p>
              <p className="text-2xl font-bold">{activeAlarms?.count || 0}</p>
            </div>
          </div>
        </div>
        
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
      </div>

      {/* Alarms List */}
      <div className="bg-opsgrid-panel border border-opsgrid-border rounded-lg">
        <div className="p-4 border-b border-opsgrid-border">
          <h2 className="text-lg font-semibold">Alarm History</h2>
        </div>
        
        <div className="divide-y divide-opsgrid-border">
          {alarms?.map((alarm: any) => (
            <div
              key={alarm.id}
              className={`p-4 flex items-center justify-between ${
                alarm.is_active ? 'bg-opsgrid-bg/50' : ''
              }`}
            >
              <div className="flex items-center gap-4">
                <span
                  className={`px-2 py-1 rounded text-xs font-medium ${getSeverityColor(
                    alarm.severity
                  )}`}
                >
                  {alarm.severity}
                </span>
                
                <div>
                  <p className="font-medium">{alarm.message}</p>
                  <p className="text-sm text-opsgrid-text-secondary">
                    {alarm.alarm_code} • {new Date(alarm.occurred_at).toLocaleString()}
                  </p>
                </div>
              </div>
              
              <div className="flex items-center gap-4">
                <span
                  className={`px-2 py-1 rounded text-xs ${
                    alarm.is_active
                      ? 'bg-status-alarm/20 text-status-alarm'
                      : 'bg-status-running/20 text-status-running'
                  }`}
                >
                  {alarm.is_active ? 'Active' : 'Cleared'}
                </span>
                
                {alarm.is_active && !alarm.is_acknowledged && (
                  <button
                    onClick={() => acknowledgeMutation.mutate(alarm.id)}
                    className="px-3 py-1 bg-opsgrid-primary text-white rounded text-sm hover:bg-opsgrid-primary/80"
                  >
                    Acknowledge
                  </button>
                )}
                
                {alarm.is_acknowledged && (
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

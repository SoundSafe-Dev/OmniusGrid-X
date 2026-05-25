import { FC } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from 'react-query'
import { AlertTriangle, CheckCircle, Box, Activity } from 'lucide-react'
import { dashboardApi, alarmsApi } from '../api'
import { Tooltip, TooltipTrigger, TooltipContent } from '../components/ui'

const Dashboard: FC = () => {
  const { data: overview, isLoading, error } = useQuery('dashboard-overview', () =>
    dashboardApi.getOverview()
  )
  
  const { data: activeAlarms } = useQuery('active-alarms', () =>
    alarmsApi.getActive()
  )

  console.log('Dashboard render:', { isLoading, overview, error, activeAlarms })

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="text-opsgrid-text-secondary">Loading dashboard data...</div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="text-status-alarm">Error loading dashboard: {(error as Error).message}</div>
      </div>
    )
  }

  const stats = [
    {
      label: 'Total Assets',
      value: overview?.totalAssets || 0,
      icon: Box,
      color: 'text-opsgrid-primary',
      tooltip: 'Total number of registered manufacturing assets',
    },
    {
      label: 'Active',
      value: overview?.activeAssets || 0,
      icon: CheckCircle,
      color: 'text-status-running',
      tooltip: 'Assets currently in Execute or Running state',
    },
    {
      label: 'Active Alarms',
      value: overview?.activeAlarms || 0,
      icon: AlertTriangle,
      color: (overview?.criticalAlarms || 0) > 0 ? 'text-status-alarm' : 'text-status-warning',
      tooltip: 'Alarms currently requiring attention',
    },
    {
      label: 'Critical',
      value: overview?.criticalAlarms || 0,
      icon: Activity,
      color: 'text-status-alarm',
      tooltip: 'Critical severity alarms requiring immediate action',
    },
  ]

  return (
    <div className="space-y-6">
      {/* Stats Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        {stats.map((stat) => {
          const Icon = stat.icon
          return (
            <Tooltip key={stat.label}>
              <TooltipTrigger asChild>
                <div className="bg-opsgrid-panel border border-opsgrid-border rounded-lg p-4">
                  <div className="flex items-center justify-between">
                    <div>
                      <p className="text-sm text-opsgrid-text-secondary">{stat.label}</p>
                      <p className="text-2xl font-bold mt-1">{stat.value}</p>
                    </div>
                    <Icon className={`${stat.color}`} size={24} />
                  </div>
                </div>
              </TooltipTrigger>
              <TooltipContent>{stat.tooltip}</TooltipContent>
            </Tooltip>
          )
        })}
      </div>

      {/* Assets by State */}
      <div className="bg-opsgrid-panel border border-opsgrid-border rounded-lg p-4">
        <h3 className="text-lg font-semibold mb-4">Assets by PackML State</h3>
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4">
          {Object.entries(overview?.assetsByState || {}).map(([state, count]) => {
            const getStateDescription = (s: string) => {
              switch (s) {
                case 'Execute': return 'Asset is actively producing parts';
                case 'Idle': return 'Asset is available but not producing';
                case 'Held': return 'Asset paused, awaiting operator intervention';
                case 'Suspended': return 'Asset suspended by external command';
                case 'Aborted': return 'Asset stopped due to error or emergency';
                case 'Stopped': return 'Asset in planned stopped state';
                case 'Starting': return 'Asset is starting up';
                case 'Completing': return 'Asset is completing current operation';
                case 'Complete': return 'Asset has completed operation';
                case 'Resetting': return 'Asset is resetting to initial state';
                default: return 'Asset state';
              }
            };
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
                <TooltipContent>{getStateDescription(state)}</TooltipContent>
              </Tooltip>
            );
          })}
        </div>
      </div>

      {/* Active Alarms */}
      {(activeAlarms?.count || 0) > 0 && (
        <div className="bg-opsgrid-panel border border-opsgrid-border rounded-lg p-4">
          <div className="flex items-center justify-between mb-4">
            <Tooltip>
              <TooltipTrigger asChild>
                <h3 className="text-lg font-semibold text-status-alarm flex items-center gap-2">
                  <AlertTriangle size={20} />
                  Active Alarms ({activeAlarms?.count || 0})
                </h3>
              </TooltipTrigger>
              <TooltipContent>Alarms currently requiring attention</TooltipContent>
            </Tooltip>
            <Tooltip>
              <TooltipTrigger asChild>
                <Link
                  to="/alarms"
                  className="text-sm text-opsgrid-primary hover:underline"
                >
                  View All
                </Link>
              </TooltipTrigger>
              <TooltipContent>View all alarms in detail</TooltipContent>
            </Tooltip>
          </div>
          <div className="space-y-2">
            {activeAlarms?.alarms?.slice(0, 5).map((alarm: any) => {
              const getSeverityDescription = (s: string) => {
                switch (s) {
                  case 'critical': return 'Critical: Immediate action required, potential safety issue';
                  case 'high': return 'High: Prompt action required';
                  case 'medium': return 'Medium: Address soon';
                  case 'low': return 'Low: Monitor, no immediate action';
                  default: return s;
                }
              };
              return (
                <div key={alarm.id} className="flex items-center gap-3 p-3 bg-opsgrid-bg rounded-lg">
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <span
                        className={`w-2 h-2 rounded-full ${
                          alarm.severity === 'critical'
                            ? 'bg-status-alarm animate-pulse'
                            : alarm.severity === 'high'
                            ? 'bg-status-warning'
                            : 'bg-opsgrid-text-secondary'
                        }`}
                      />
                    </TooltipTrigger>
                    <TooltipContent>{getSeverityDescription(alarm.severity)}</TooltipContent>
                  </Tooltip>
                  <div className="flex-1">
                    <Tooltip>
                      <TooltipTrigger asChild>
                        <p className="font-medium">{alarm.message}</p>
                      </TooltipTrigger>
                      <TooltipContent>Alarm details: {alarm.message}</TooltipContent>
                    </Tooltip>
                    <p className="text-sm text-opsgrid-text-secondary">
                      {alarm.asset_name} • {new Date(alarm.occurred_at).toLocaleString()}
                    </p>
                  </div>
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <span
                        className={`px-2 py-1 rounded text-xs font-medium ${
                          alarm.severity === 'critical'
                            ? 'bg-status-alarm/20 text-status-alarm'
                            : alarm.severity === 'high'
                            ? 'bg-status-warning/20 text-status-warning'
                            : 'bg-opsgrid-text-secondary/20 text-opsgrid-text-secondary'
                        }`}
                      >
                        {alarm.severity}
                      </span>
                    </TooltipTrigger>
                    <TooltipContent>Severity: {alarm.severity}</TooltipContent>
                  </Tooltip>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  )
}

export default Dashboard

import { FC } from 'react'
import { useParams } from 'react-router-dom'
import { useQuery } from 'react-query'
import { ArrowLeft, Activity, Clock, Box } from 'lucide-react'
import { Link } from 'react-router-dom'
import { assetsApi, telemetryApi } from '../api'
import { Tooltip, TooltipTrigger, TooltipContent } from '../components/ui'
import { TelemetryHistoryChart } from '../components/charts'
import { TrendingUp } from 'lucide-react'

const AssetDetail: FC = () => {
  const { id } = useParams<{ id: string }>()
  
  const { data: asset, isLoading } = useQuery(['asset', id], () =>
    assetsApi.get(id!)
  )

  const { data: telemetry } = useQuery(
    ['telemetry', id],
    () => telemetryApi.getLatest(id!),
    { refetchInterval: 5000 }
  )

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="text-opsgrid-text-secondary">Loading...</div>
      </div>
    )
  }

  if (!asset) {
    return (
      <div className="text-center py-12">
        <p className="text-opsgrid-text-secondary">Asset not found</p>
        <Link to="/assets" className="text-opsgrid-primary hover:underline mt-4 inline-block">
          Back to Assets
        </Link>
      </div>
    )
  }

  const getStatusColor = (state: string) => {
    switch (state) {
      case 'Execute':
        return 'text-packml-execute'
      case 'Idle':
        return 'text-packml-idle'
      case 'Held':
      case 'Suspended':
        return 'text-packml-held'
      case 'Aborted':
        return 'text-packml-aborted'
      default:
        return 'text-opsgrid-text-secondary'
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-4">
        <Tooltip>
          <TooltipTrigger asChild>
            <Link
              to="/assets"
              className="flex items-center gap-2 text-opsgrid-text-secondary hover:text-opsgrid-text"
            >
              <ArrowLeft size={20} />
              Back
            </Link>
          </TooltipTrigger>
          <TooltipContent>Return to assets list</TooltipContent>
        </Tooltip>
      </div>

      {/* Header */}
      <div className="bg-opsgrid-panel border border-opsgrid-border rounded-lg p-6">
        <div className="flex items-start justify-between">
          <div className="flex items-center gap-4">
            <Tooltip>
              <TooltipTrigger asChild>
                <Box className="text-opsgrid-primary" size={32} />
              </TooltipTrigger>
              <TooltipContent>Asset icon</TooltipContent>
            </Tooltip>
            <div>
              <Tooltip>
                <TooltipTrigger asChild>
                  <h1 className="text-2xl font-bold">{asset.name}</h1>
                </TooltipTrigger>
                <TooltipContent>Asset name</TooltipContent>
              </Tooltip>
              <Tooltip>
                <TooltipTrigger asChild>
                  <p className="text-opsgrid-text-secondary">
                    {asset.vendor} {asset.model} • {asset.serialNumber}
                  </p>
                </TooltipTrigger>
                <TooltipContent>Asset vendor, model, and serial number</TooltipContent>
              </Tooltip>
            </div>
          </div>
          <Tooltip>
            <TooltipTrigger asChild>
              <div className="flex items-center gap-3">
                <span
                  className={`w-4 h-4 rounded-full ${getStatusColor(
                    asset.currentPackmlState
                  )} ${asset.currentPackmlState === 'Execute' ? 'animate-pulse' : ''}`}
                />
                <span className="text-lg font-semibold">{asset.currentPackmlState}</span>
              </div>
            </TooltipTrigger>
            <TooltipContent>Current PackML state</TooltipContent>
          </Tooltip>
        </div>
      </div>

      {/* Telemetry */}
      {telemetry && (
        <div className="bg-opsgrid-panel border border-opsgrid-border rounded-lg p-6">
          <Tooltip>
            <TooltipTrigger asChild>
              <h2 className="text-lg font-semibold mb-4 flex items-center gap-2">
                <Activity size={20} />
                Latest Telemetry
              </h2>
            </TooltipTrigger>
            <TooltipContent>Most recent sensor data from the asset</TooltipContent>
          </Tooltip>
          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
            {Array.isArray(telemetry) || (typeof telemetry === 'object' && 'metricName' in telemetry) === false ?
              // Multiple metrics case
              Object.entries(telemetry as Record<string, any>).map(([key, metric]) => (
                <Tooltip key={key}>
                  <TooltipTrigger asChild>
                    <div className="bg-opsgrid-bg rounded-lg p-4">
                      <p className="text-sm text-opsgrid-text-secondary capitalize">
                        {key.replace('_', ' ')}
                      </p>
                      <p className="text-xl font-semibold">
                        {metric.value}{metric.unit || ''}
                      </p>
                      <p className="text-xs text-opsgrid-text-secondary mt-1">
                        {new Date(metric.timestamp).toLocaleTimeString()}
                      </p>
                    </div>
                  </TooltipTrigger>
                  <TooltipContent>Latest reading for {key.replace('_', ' ')}</TooltipContent>
                </Tooltip>
              )) :
              // Single metric case
              <Tooltip>
                <TooltipTrigger asChild>
                  <div className="bg-opsgrid-bg rounded-lg p-4">
                    <p className="text-sm text-opsgrid-text-secondary capitalize">
                      {(telemetry as any).metricName?.replace('_', ' ')}
                    </p>
                    <p className="text-xl font-semibold">
                      {(telemetry as any).value}{(telemetry as any).unit || ''}
                    </p>
                    <p className="text-xs text-opsgrid-text-secondary mt-1">
                      {new Date((telemetry as any).timestamp).toLocaleString()}
                    </p>
                  </div>
                </TooltipTrigger>
                <TooltipContent>Latest reading for {(telemetry as any).metricName?.replace('_', ' ')}</TooltipContent>
              </Tooltip>
            }
          </div>
        </div>
      )}

      {/* Telemetry History (task B8): stored history + aggregation, complements
          the latest-values grid above. */}
      {id && (
        <div className="bg-opsgrid-panel border border-opsgrid-border rounded-lg p-6">
          <h2 className="text-lg font-semibold mb-4 flex items-center gap-2">
            <TrendingUp size={20} />
            Telemetry History
          </h2>
          <TelemetryHistoryChart assetId={id} />
        </div>
      )}

      {/* Connection Info */}
      <div className="bg-opsgrid-panel border border-opsgrid-border rounded-lg p-6">
        <Tooltip>
          <TooltipTrigger asChild>
            <h2 className="text-lg font-semibold mb-4 flex items-center gap-2">
              <Clock size={20} />
              Connection Details
            </h2>
          </TooltipTrigger>
          <TooltipContent>Asset connection and communication information</TooltipContent>
        </Tooltip>
        <div className="space-y-2 text-sm">
          <div className="flex justify-between">
            <Tooltip>
              <TooltipTrigger asChild>
                <span className="text-opsgrid-text-secondary">Last Seen</span>
              </TooltipTrigger>
              <TooltipContent>Last time asset communicated with the system</TooltipContent>
            </Tooltip>
            <Tooltip>
              <TooltipTrigger asChild>
                <span>{asset.lastSeen ? new Date(asset.lastSeen).toLocaleString() : 'Never'}</span>
              </TooltipTrigger>
              <TooltipContent>Timestamp of last communication</TooltipContent>
            </Tooltip>
          </div>
          <div className="flex justify-between">
            <Tooltip>
              <TooltipTrigger asChild>
                <span className="text-opsgrid-text-secondary">Status</span>
              </TooltipTrigger>
              <TooltipContent>Current connection status</TooltipContent>
            </Tooltip>
            <Tooltip>
              <TooltipTrigger asChild>
                <span className={asset.isActive ? 'text-status-running' : 'text-status-offline'}>
                  {asset.isActive ? 'Active' : 'Inactive'}
                </span>
              </TooltipTrigger>
              <TooltipContent>{asset.isActive ? 'Asset is currently connected' : 'Asset is not connected'}</TooltipContent>
            </Tooltip>
          </div>
          <div className="flex justify-between">
            <Tooltip>
              <TooltipTrigger asChild>
                <span className="text-opsgrid-text-secondary">Protocol</span>
              </TooltipTrigger>
              <TooltipContent>Communication protocol used by the asset</TooltipContent>
            </Tooltip>
            <Tooltip>
              <TooltipTrigger asChild>
                <span>{asset.connectionConfig?.protocol || 'Unknown'}</span>
              </TooltipTrigger>
              <TooltipContent>Protocol name (e.g., MQTT, OPC-UA, Modbus)</TooltipContent>
            </Tooltip>
          </div>
        </div>
      </div>
    </div>
  )
}

export default AssetDetail

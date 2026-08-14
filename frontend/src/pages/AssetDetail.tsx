import { FC, useMemo, useState } from 'react'
import { useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { ArrowLeft, Activity, Clock, Box, Wrench } from 'lucide-react'
import { Link } from 'react-router-dom'
import { assetsApi, telemetryApi, alarmsApi } from '../api'
// Badge from `components/ui`, NOT the top-level `components` barrel. That barrel
// statically re-exports FleetTrackerMap, GeoTabIntegration, MaintenancePanel and a
// recharts chart, so importing one Badge through it would pull the whole fleet surface
// into this page's module graph — the bundle-size trap the barrel's own comment warns
// about, and it would also drag all of it into this page's test.
import { Tooltip, TooltipTrigger, TooltipContent, Badge } from '../components/ui'
import { RealtimeTelemetryChart, TelemetryHistoryChart } from '../components/charts'
import { SensorPanels } from '../components/assets/SensorPanels'
import { CommandPanel } from '../components/commands'
import { TrendingUp } from 'lucide-react'
import { ExportButton } from '../components/common'
import { OEEDetailPanel } from '../components/oee'
import { useAcknowledgeAlarm } from '../hooks'
import { useAuth } from '../hooks/useAuth'
import { AlertTriangle, BarChart3 } from 'lucide-react'
import { formatDateTime } from '../utils/formatters'

const AssetDetail: FC = () => {
  const { id } = useParams<{ id: string }>()
  const { isAdmin, isOperator } = useAuth()

  const { data: asset, isLoading, isError } = useQuery({
    queryKey: ['asset', id],
    queryFn: () => assetsApi.get(id!),
  })

  const { data: telemetry } = useQuery({
    queryKey: ['telemetry', id],
    queryFn: () => telemetryApi.getLatest(id!),
    refetchInterval: 5000,
  })

  // Metrics for the live chart, derived from whatever the asset actually
  // reports. Keyed by the metric NAMES (a string), not the telemetry object
  // identity — the query refetches every 5s and the chart resubscribes to the
  // websocket whenever the metrics array changes.
  const liveMetricsKey = !telemetry
    ? ''
    : 'metricName' in (telemetry as any)
      ? ((telemetry as any).metricName ?? '')
      : Object.entries(telemetry as Record<string, unknown>)
          // record form maps metric name -> point object; the backend's
          // no-data envelope ({message: '...'}) must not become a "metric"
          .filter(([, v]) => v !== null && typeof v === 'object')
          .map(([k]) => k)
          .slice(0, 6)
          .join(',')
  const liveMetrics = useMemo(
    () => (liveMetricsKey ? liveMetricsKey.split(',') : undefined),
    [liveMetricsKey]
  )

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="text-opsgrid-text-secondary">Loading...</div>
      </div>
    )
  }

  // A failed fetch previously fell through to the "Asset not found" branch below,
  // which is misleading (it's a load error, not a missing asset). Distinguish
  // them so a transient failure reads as retryable, not as a 404.
  if (isError) {
    return (
      <div className="text-center py-12">
        <p className="text-status-alarm">Failed to load asset.</p>
        <p className="text-sm text-opsgrid-text-secondary mt-1">
          Check your connection and try again.
        </p>
        <Link to="/assets" className="text-opsgrid-primary hover:underline mt-4 inline-block">
          Back to Assets
        </Link>
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
                    {asset.sensorClass && (
                      <span className="ml-2 inline-block px-2 py-0.5 text-xs rounded bg-opsgrid-bg border border-opsgrid-border text-opsgrid-accent uppercase">
                        {asset.sensorClass}
                      </span>
                    )}
                  </p>
                </TooltipTrigger>
                <TooltipContent>Asset vendor, model, serial number, and sensor class</TooltipContent>
              </Tooltip>
            </div>
          </div>
          <div className="flex items-center gap-3">
            {/* MAINTENANCE MODE HAD NO READ PATH AT ALL. Migration 053 added the column,
                the admin endpoint writes it and the tactical engine reads it before
                dispatching a control command — but `AssetResponse` did not carry it, so
                an operator could take a machine out of service and see no sign of it
                anywhere. The PackML state keeps ticking over as normal, which is exactly
                what makes the omission dangerous: the page looks like it is telling you
                everything about the asset. */}
            {asset.maintenanceMode && (
              <Tooltip>
                <TooltipTrigger asChild>
                  <Badge variant="warning" size="md">
                    <Wrench size={14} className="mr-1" />
                    Maintenance
                  </Badge>
                </TooltipTrigger>
                <TooltipContent>
                  This asset is in maintenance mode. Game-theoretic engine commands are
                  suppressed until it is cleared.
                </TooltipContent>
              </Tooltip>
            )}
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
      </div>

      {isAdmin && (
        <div className="flex justify-end">
          <ExportButton
            endpoint={`/api/v1/exports/telemetry/${id}`}
            format="csv"
            label="Export telemetry CSV"
            filename={`telemetry_${asset.name}.csv`}
          />
        </div>
      )}

      {/* Alarms for THIS asset (P7, page-enhancement review). The page an operator opens
          to ask "what is wrong with this machine" had no alarms on it at all — they had to
          leave for /alarms and filter there, which until P1 they could not do either.
          `alarmsApi.list({assetId})` has supported this since the route existed. */}
      {id && <AssetAlarmsPanel assetId={id} />}

      {/* Three-factor OEE for this asset (P7). `getAssetOEE` and the honest detail panel
          both already existed — the panel was local to pages/OEE.tsx, so the fleet table
          had a good OEE breakdown and the asset page had none. */}
      {id && asset && (
        <div className="bg-opsgrid-panel border border-opsgrid-border rounded-lg p-6">
          <h2 className="text-lg font-semibold mb-4 flex items-center gap-2">
            <BarChart3 size={20} />
            OEE (last 24 hours)
          </h2>
          <OEEDetailPanel assetId={id} assetName={asset.name} hours={24} />
        </div>
      )}

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
                        {key?.replace('_', ' ')}
                      </p>
                      <p className="text-xl font-semibold">
                        {metric.value}{metric.unit || ''}
                      </p>
                      <p className="text-xs text-opsgrid-text-secondary mt-1">
                        {new Date(metric.timestamp).toLocaleTimeString()}
                      </p>
                    </div>
                  </TooltipTrigger>
                  <TooltipContent>Latest reading for {key?.replace('_', ' ')}</TooltipContent>
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

      {/* Type-aware sensor pane (sensor taxonomy): machinery gauges / audio /
          camera feed depending on the asset's sensor class. */}
      <SensorPanels
        asset={asset}
        telemetry={telemetry && !('metricName' in (telemetry as any)) ? (telemetry as any) : null}
      />

      {/* Live telemetry (FS-62): websocket-driven stream of the asset's own
          metrics, complements the polled latest-values grid above. Rendered
          once we know which metrics the asset reports. */}
      {id && liveMetrics && liveMetrics.length > 0 && (
        <RealtimeTelemetryChart
          assetId={id}
          assetName={asset.name}
          metrics={liveMetrics}
          height={340}
          title={`Live Telemetry — ${asset.name}`}
        />
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

      {/* Command Control (FS-62): operator/admin actions area. Backend enforces
          RBAC (@require_operator_or_admin on /api/v1/commands/submit). */}
      {id && isOperator && (
        <CommandPanel
          canEmergencyStop={isAdmin}
          assetId={id}
          assetName={asset.name}
          currentState={asset.currentPackmlState}
        />
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

/**
 * Active alarms on one asset, with inline acknowledgement (P7).
 *
 * Scoped by `assetId` and `isActive`, both long-supported query params. Failure is stated
 * rather than rendered as calm: "no active alarms" and "we could not ask" are different
 * facts about a machine, and only one of them means walk away.
 */
const AssetAlarmsPanel: FC<{ assetId: string }> = ({ assetId }) => {
  const { data, isLoading, isError } = useQuery({
    queryKey: ['asset-alarms', assetId],
    queryFn: () => alarmsApi.list({ assetId, isActive: true, limit: 25 }),
    refetchInterval: 15000,
  })
  const acknowledge = useAcknowledgeAlarm()
  const [ackError, setAckError] = useState<string | null>(null)

  const alarms = data?.items ?? []

  return (
    <div className="bg-opsgrid-panel border border-opsgrid-border rounded-lg p-6">
      <h2 className="text-lg font-semibold mb-4 flex items-center gap-2">
        <AlertTriangle size={20} />
        Active alarms
        {!isError && !isLoading && alarms.length > 0 && (
          <span className="text-sm font-normal text-status-alarm">({alarms.length})</span>
        )}
      </h2>

      {ackError && (
        <div
          role="alert"
          className="mb-3 rounded border border-status-alarm/40 bg-status-alarm/10 px-3 py-2 text-sm text-status-alarm"
        >
          {ackError}
        </div>
      )}

      {isLoading && <p className="text-sm text-opsgrid-text-secondary">Loading alarms…</p>}

      {isError && (
        <p className="text-sm text-status-alarm" role="alert">
          Could not load alarms for this asset — this is a failed request, not a quiet
          machine.
        </p>
      )}

      {!isLoading && !isError && alarms.length === 0 && (
        <p className="text-sm text-opsgrid-text-secondary">No active alarms on this asset.</p>
      )}

      <div className="divide-y divide-opsgrid-border">
        {alarms.map((alarm: any) => (
          <div key={alarm.id} className="py-3 flex items-center justify-between gap-4">
            <div className="min-w-0">
              <p className="font-medium truncate">{alarm.message}</p>
              <p className="text-sm text-opsgrid-text-secondary">
                {alarm.severity} • {alarm.alarmCode} • {formatDateTime(alarm.occurredAt)}
              </p>
            </div>
            {alarm.isAcknowledged ? (
              <span className="text-sm text-opsgrid-text-secondary shrink-0">Acknowledged</span>
            ) : (
              <button
                onClick={() => {
                  setAckError(null)
                  acknowledge.mutate(
                    { alarmId: alarm.id },
                    {
                      onError: () =>
                        setAckError(
                          `Could not acknowledge "${alarm.message ?? alarm.id}". It is still unacknowledged.`,
                        ),
                    },
                  )
                }}
                className="shrink-0 px-3 py-1 bg-opsgrid-primary text-white rounded text-sm hover:bg-opsgrid-primary/80"
              >
                Acknowledge
              </button>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}

export default AssetDetail

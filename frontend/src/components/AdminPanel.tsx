import { FC, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from 'react-query'
import { api } from '../api/client'
import { Power, RotateCcw, Database, Wrench, AlertTriangle, CheckCircle } from 'lucide-react'

const AdminPanel: FC = () => {
  const queryClient = useQueryClient()
  const [selectedAsset, setSelectedAsset] = useState<string>('')
  const [maintenanceMode, setMaintenanceMode] = useState(false)

  const { data: systemStatus, isLoading } = useQuery('system-status', () =>
    api.get('/admin/system/status').then((res) => res.data)
  )

  const { data: assets } = useQuery('admin-assets', () =>
    api.get('/api/v1/assets/').then((res) => res.data)
  )

  const maintenanceMutation = useMutation(
    ({ assetId, enabled }: { assetId: string; enabled: boolean }) =>
      api.post(`/admin/assets/${assetId}/maintenance?enabled=${enabled}`),
    {
      onSuccess: () => {
        queryClient.invalidateQueries('admin-assets')
        queryClient.invalidateQueries('system-status')
      },
    }
  )

  const vacuumMutation = useMutation(
    () => api.post('/admin/database/vacuum'),
    {
      onSuccess: () => {
        alert('Database vacuum initiated. This may take several minutes.')
      },
    }
  )

  const restartCollectorMutation = useMutation(
    (collectorId: string) => api.post(`/admin/collectors/${collectorId}/restart`),
    {
      onSuccess: () => {
        alert('Collector restart signal sent')
      },
    }
  )

  if (isLoading) {
    return <div className="text-opsgrid-text-secondary">Loading...</div>
  }

  return (
    <div className="space-y-6">
      <div className="bg-opsgrid-panel border border-opsgrid-border rounded-lg p-4">
        <h2 className="text-lg font-semibold flex items-center gap-2 mb-4">
          <Wrench size={20} />
          Manual Overrides (Engineer Controls)
        </h2>

        {/* System Status Overview */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
          <div className="bg-opsgrid-bg rounded-lg p-3">
            <p className="text-sm text-opsgrid-text-secondary">Active Alerts</p>
            <div className="flex items-center gap-2 mt-1">
              <AlertTriangle className="text-status-alarm" size={16} />
              <span className="text-xl font-bold">{systemStatus?.alerts?.critical || 0}</span>
            </div>
          </div>
          <div className="bg-opsgrid-bg rounded-lg p-3">
            <p className="text-sm text-opsgrid-text-secondary">Data Ingestion</p>
            <div className="flex items-center gap-2 mt-1">
              <CheckCircle className="text-status-running" size={16} />
              <span className="text-lg font-medium">{systemStatus?.data_pipeline?.messages_per_second || 0} msg/s</span>
            </div>
          </div>
          <div className="bg-opsgrid-bg rounded-lg p-3">
            <p className="text-sm text-opsgrid-text-secondary">Database Size</p>
            <div className="flex items-center gap-2 mt-1">
              <Database className="text-opsgrid-primary" size={16} />
              <span className="text-lg font-medium">{systemStatus?.storage?.database_size_gb || 0} GB</span>
            </div>
          </div>
          <div className="bg-opsgrid-bg rounded-lg p-3">
            <p className="text-sm text-opsgrid-text-secondary">Compression</p>
            <div className="flex items-center gap-2 mt-1">
              <span className="text-lg font-medium">
                {((systemStatus?.storage?.compression_ratio || 0) * 100).toFixed(0)}%
              </span>
            </div>
          </div>
        </div>

        {/* Maintenance Mode Controls */}
        <div className="border-t border-opsgrid-border pt-4 mb-6">
          <h3 className="font-semibold mb-3">Asset Maintenance Mode</h3>
          <p className="text-sm text-opsgrid-text-secondary mb-4">
            When maintenance mode is enabled, the game-theoretic engine cannot send automated commands to the asset.
          </p>
          
          <div className="flex items-center gap-4 mb-4">
            <select
              value={selectedAsset}
              onChange={(e) => setSelectedAsset(e.target.value)}
              className="bg-opsgrid-bg border border-opsgrid-border rounded px-3 py-2 text-opsgrid-text"
            >
              <option value="">Select Asset...</option>
              {assets?.map((asset: any) => (
                <option key={asset.id} value={asset.id}>
                  {asset.name} ({asset.current_packml_state})
                </option>
              ))}
            </select>
            
            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={maintenanceMode}
                onChange={(e) => setMaintenanceMode(e.target.checked)}
                className="w-4 h-4"
              />
              <span>Enable Maintenance Mode</span>
            </label>
            
            <button
              onClick={() => selectedAsset && maintenanceMutation.mutate({ assetId: selectedAsset, enabled: maintenanceMode })}
              disabled={!selectedAsset || maintenanceMutation.isLoading}
              className="px-4 py-2 bg-status-warning text-opsgrid-bg rounded hover:bg-status-warning/80 disabled:opacity-50"
            >
              {maintenanceMutation.isLoading ? 'Applying...' : 'Apply'}
            </button>
          </div>
        </div>

        {/* Collector Controls */}
        <div className="border-t border-opsgrid-border pt-4 mb-6">
          <h3 className="font-semibold mb-3">Collector Controls</h3>
          <div className="flex items-center gap-4">
            <button
              onClick={() => restartCollectorMutation.mutate('mqtt-collector')}
              disabled={restartCollectorMutation.isLoading}
              className="flex items-center gap-2 px-4 py-2 bg-opsgrid-bg border border-opsgrid-border rounded hover:bg-opsgrid-border"
            >
              <RotateCcw size={16} />
              Restart MQTT Collector
            </button>
            <button
              onClick={() => restartCollectorMutation.mutate('screen-scraper')}
              disabled={restartCollectorMutation.isLoading}
              className="flex items-center gap-2 px-4 py-2 bg-opsgrid-bg border border-opsgrid-border rounded hover:bg-opsgrid-border"
            >
              <RotateCcw size={16} />
              Restart Screen Scraper
            </button>
          </div>
        </div>

        {/* Database Maintenance */}
        <div className="border-t border-opsgrid-border pt-4">
          <h3 className="font-semibold mb-3">Database Maintenance</h3>
          <button
            onClick={() => vacuumMutation.mutate()}
            disabled={vacuumMutation.isLoading}
            className="flex items-center gap-2 px-4 py-2 bg-opsgrid-primary text-white rounded hover:bg-opsgrid-primary/80 disabled:opacity-50"
          >
            <Database size={16} />
            {vacuumMutation.isLoading ? 'Running Vacuum...' : 'Trigger Database Vacuum'}
          </button>
          <p className="text-sm text-opsgrid-text-secondary mt-2">
            Vacuum reclaims storage and optimizes query performance. This may take several minutes.
          </p>
        </div>
      </div>

      {/* Lights Out Status */}
      <div className="bg-opsgrid-panel border border-opsgrid-border rounded-lg p-4">
        <h2 className="text-lg font-semibold flex items-center gap-2 mb-4">
          <Power size={20} />
          Self-Healing (Lights Out) Status
        </h2>
        
        <div className="space-y-2">
          <div className="flex items-center justify-between p-3 bg-opsgrid-bg rounded-lg">
            <span>K3s Auto-Restart</span>
            <span className="flex items-center gap-2 text-status-running">
              <CheckCircle size={16} />
              Enabled
            </span>
          </div>
          <div className="flex items-center justify-between p-3 bg-opsgrid-bg rounded-lg">
            <span>Hardware Watchdog</span>
            <span className="flex items-center gap-2 text-status-running">
              <CheckCircle size={16} />
              Armed
            </span>
          </div>
          <div className="flex items-center justify-between p-3 bg-opsgrid-bg rounded-lg">
            <span>Database HA (Patroni)</span>
            <span className="flex items-center gap-2 text-status-running">
              <CheckCircle size={16} />
              Active
            </span>
          </div>
          <div className="flex items-center justify-between p-3 bg-opsgrid-bg rounded-lg">
            <span>Data Shedding</span>
            <span className="flex items-center gap-2 text-packml-held">
              Standby
            </span>
          </div>
        </div>
      </div>
    </div>
  )
}

export default AdminPanel

import { FC } from 'react'
import { useQuery } from 'react-query'
import { BarChart3, TrendingUp, Clock } from 'lucide-react'
import { dashboardApi } from '../api'

const OEE: FC = () => {
  const { data: fleetOEE, isLoading } = useQuery('fleet-oee', () =>
    dashboardApi.getFleetOEE()
  )

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="text-opsgrid-text-secondary">Loading...</div>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-semibold flex items-center gap-2">
          <BarChart3 size={24} />
          Overall Equipment Effectiveness (OEE)
        </h2>
        <div className="text-sm text-opsgrid-text-secondary">
          {fleetOEE?.time_range || 'Last 24 hours'}
        </div>
      </div>

      {/* Fleet Summary */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div className="bg-opsgrid-panel border border-opsgrid-border rounded-lg p-6">
          <div className="flex items-center gap-3 mb-2">
            <Clock className="text-opsgrid-primary" size={24} />
            <p className="text-opsgrid-text-secondary">Availability</p>
          </div>
          <p className="text-3xl font-bold">
            {((fleetOEE?.fleetAverageAvailability || 0) * 100).toFixed(1)}%
          </p>
          <p className="text-sm text-opsgrid-text-secondary mt-1">
            Time equipment was available to run
          </p>
        </div>

        <div className="bg-opsgrid-panel border border-opsgrid-border rounded-lg p-6">
          <div className="flex items-center gap-3 mb-2">
            <TrendingUp className="text-packml-execute" size={24} />
            <p className="text-opsgrid-text-secondary">Performance</p>
          </div>
          <p className="text-3xl font-bold">
            {(fleetOEE?.fleetAveragePerformance * 100 || 100).toFixed(1)}%
          </p>
          <p className="text-sm text-opsgrid-text-secondary mt-1">
            Speed vs ideal cycle time
          </p>
        </div>

        <div className="bg-opsgrid-panel border border-opsgrid-border rounded-lg p-6">
          <div className="flex items-center gap-3 mb-2">
            <BarChart3 className="text-status-running" size={24} />
            <p className="text-opsgrid-text-secondary">Overall OEE</p>
          </div>
          <p className="text-3xl font-bold">
            {((fleetOEE?.fleetAverageOee || 0) * 100).toFixed(1)}%
          </p>
          <p className="text-sm text-opsgrid-text-secondary mt-1">
            Availability × Performance × Quality
          </p>
        </div>
      </div>

      {/* Asset OEE Table */}
      <div className="bg-opsgrid-panel border border-opsgrid-border rounded-lg">
        <div className="p-4 border-b border-opsgrid-border">
          <h3 className="text-lg font-semibold">
            Asset OEE Breakdown ({fleetOEE?.assetCount || 0} assets)
          </h3>
        </div>
        
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr className="bg-opsgrid-bg">
                <th className="text-left p-4 text-opsgrid-text-secondary font-medium">Asset</th>
                <th className="text-center p-4 text-opsgrid-text-secondary font-medium">Availability</th>
                <th className="text-center p-4 text-opsgrid-text-secondary font-medium">OEE</th>
                <th className="text-right p-4 text-opsgrid-text-secondary font-medium">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-opsgrid-border">
              {fleetOEE?.assets?.map((asset: any) => (
                <tr key={asset.assetId} className="hover:bg-opsgrid-bg/50">
                  <td className="p-4">
                    <p className="font-medium">{asset.assetName}</p>
                    <p className="text-sm text-opsgrid-text-secondary">{asset.assetId}</p>
                  </td>
                  <td className="p-4 text-center">
                    <div className="flex items-center justify-center gap-2">
                      <div className="w-24 h-2 bg-opsgrid-bg rounded-full overflow-hidden">
                        <div
                          className="h-full bg-opsgrid-primary"
                          style={{ width: `${asset.availability * 100}%` }}
                        />
                      </div>
                      <span className="text-sm">{(asset.availability * 100).toFixed(1)}%</span>
                    </div>
                  </td>
                  <td className="p-4 text-center">
                    <span
                      className={`font-semibold ${
                        asset.oee > 0.8
                          ? 'text-status-running'
                          : asset.oee > 0.5
                          ? 'text-packml-held'
                          : 'text-status-alarm'
                      }`}
                    >
                      {(asset.oee * 100).toFixed(1)}%
                    </span>
                  </td>
                  <td className="p-4 text-right">
                    <span
                      className={`inline-block w-3 h-3 rounded-full ${
                        asset.oee > 0.8
                          ? 'bg-status-running'
                          : asset.oee > 0.5
                          ? 'bg-packml-held'
                          : 'bg-status-alarm'
                      }`}
                    />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        
        {fleetOEE?.assets?.length === 0 && (
          <div className="p-8 text-center text-opsgrid-text-secondary">
            No OEE data available
          </div>
        )}
      </div>
    </div>
  )
}

export default OEE

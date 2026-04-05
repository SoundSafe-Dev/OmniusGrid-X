import { FC } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from 'react-query'
import { Box, ChevronRight, Activity } from 'lucide-react'
import { api } from '../api/client'

const Assets: FC = () => {
  const { data: assets, isLoading } = useQuery('assets', () =>
    api.get('/api/v1/assets/').then((res) => res.data)
  )

  const getStatusColor = (state: string) => {
    switch (state) {
      case 'Execute':
        return 'bg-packml-execute'
      case 'Idle':
        return 'bg-packml-idle'
      case 'Held':
      case 'Suspended':
        return 'bg-packml-held'
      case 'Aborted':
        return 'bg-packml-aborted'
      case 'Stopped':
        return 'bg-packml-stopped'
      default:
        return 'bg-opsgrid-text-secondary'
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
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-semibold">Assets</h2>
        <div className="text-sm text-opsgrid-text-secondary">
          {assets?.length || 0} total
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {assets?.map((asset: any) => (
          <Link
            key={asset.id}
            to={`/assets/${asset.id}`}
            className="bg-opsgrid-panel border border-opsgrid-border rounded-lg p-4 hover:border-opsgrid-primary transition-colors"
          >
            <div className="flex items-start justify-between">
              <div className="flex items-center gap-3">
                <Box className="text-opsgrid-primary" size={24} />
                <div>
                  <h3 className="font-semibold">{asset.name}</h3>
                  <p className="text-sm text-opsgrid-text-secondary">
                    {asset.vendor} {asset.model}
                  </p>
                </div>
              </div>
              <div className="flex items-center gap-2">
                <span
                  className={`w-3 h-3 rounded-full ${getStatusColor(
                    asset.current_packml_state
                  )} ${asset.current_packml_state === 'Execute' ? 'animate-pulse' : ''}`}
                />
              </div>
            </div>

            <div className="mt-4 pt-4 border-t border-opsgrid-border">
              <div className="flex items-center justify-between text-sm">
                <span className="text-opsgrid-text-secondary">State</span>
                <span className="font-medium">{asset.current_packml_state}</span>
              </div>
              {asset.last_seen && (
                <div className="flex items-center justify-between text-sm mt-2">
                  <span className="text-opsgrid-text-secondary">Last Seen</span>
                  <span>{new Date(asset.last_seen).toLocaleString()}</span>
                </div>
              )}
            </div>

            <div className="mt-4 flex items-center justify-end text-opsgrid-primary">
              <span className="text-sm">View Details</span>
              <ChevronRight size={16} />
            </div>
          </Link>
        ))}
      </div>
    </div>
  )
}

export default Assets

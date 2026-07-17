import { FC, useState } from 'react'
import { Link } from 'react-router-dom'
import { Box, ChevronRight } from 'lucide-react'
import { useAssets } from '../hooks'
import { Tooltip, TooltipTrigger, TooltipContent } from '../components/ui'

const Assets: FC = () => {
  // FS-127: page through the FS-82 envelope. Page size comes from the limit the
  // backend echoes back; skip is part of the queryKey via the hook's params.
  const [skip, setSkip] = useState(0)
  const { data: assetsData, isLoading } = useAssets({ skip })
  const assets = assetsData?.items || []
  const total = assetsData?.total ?? 0
  const limit = assetsData?.limit || assets.length || 1
  const rangeStart = total === 0 ? 0 : (assetsData?.skip ?? skip) + 1
  const rangeEnd = (assetsData?.skip ?? skip) + assets.length

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

  const getStateDescription = (state: string) => {
    switch (state) {
      case 'Execute': return 'Asset is actively producing parts';
      case 'Idle': return 'Asset is available but not producing';
      case 'Held': return 'Asset paused, awaiting operator intervention';
      case 'Suspended': return 'Asset suspended by external command';
      case 'Aborted': return 'Asset stopped due to error or emergency';
      case 'Stopped': return 'Asset in planned stopped state';
      default: return 'Asset state';
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
        <Tooltip>
          <TooltipTrigger asChild>
            <h2 className="text-xl font-semibold">Assets</h2>
          </TooltipTrigger>
          <TooltipContent>Manage and monitor manufacturing equipment</TooltipContent>
        </Tooltip>
        <Tooltip>
          <TooltipTrigger asChild>
            <div className="text-sm text-opsgrid-text-secondary">
              {total} total
            </div>
          </TooltipTrigger>
          <TooltipContent>Total number of registered assets in the system</TooltipContent>
        </Tooltip>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {assets?.map((asset: any) => (
          <Tooltip key={asset.id}>
            <TooltipTrigger asChild>
              <Link
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
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <div className="flex items-center gap-2">
                        <span
                          className={`w-3 h-3 rounded-full ${getStatusColor(
                            asset.current_packml_state
                          )} ${asset.current_packml_state === 'Execute' ? 'animate-pulse' : ''}`}
                        />
                      </div>
                    </TooltipTrigger>
                    <TooltipContent>{getStateDescription(asset.current_packml_state)}</TooltipContent>
                  </Tooltip>
                </div>

                <div className="mt-4 pt-4 border-t border-opsgrid-border">
                  <div className="flex items-center justify-between text-sm">
                    <Tooltip>
                      <TooltipTrigger asChild>
                        <span className="text-opsgrid-text-secondary">State</span>
                      </TooltipTrigger>
                      <TooltipContent>Current PackML state of the asset</TooltipContent>
                    </Tooltip>
                    <Tooltip>
                      <TooltipTrigger asChild>
                        <span className="font-medium">{asset.current_packml_state}</span>
                      </TooltipTrigger>
                      <TooltipContent>{getStateDescription(asset.current_packml_state)}</TooltipContent>
                    </Tooltip>
                  </div>
                  {asset.last_seen && (
                    <div className="flex items-center justify-between text-sm mt-2">
                      <Tooltip>
                        <TooltipTrigger asChild>
                          <span className="text-opsgrid-text-secondary">Last Seen</span>
                        </TooltipTrigger>
                        <TooltipContent>Last time asset reported data to the system</TooltipContent>
                      </Tooltip>
                      <Tooltip>
                        <TooltipTrigger asChild>
                          <span>{new Date(asset.last_seen).toLocaleString()}</span>
                        </TooltipTrigger>
                        <TooltipContent>Timestamp of last data transmission</TooltipContent>
                      </Tooltip>
                    </div>
                  )}
                </div>

                <div className="mt-4 flex items-center justify-end text-opsgrid-primary">
                  <span className="text-sm">View Details</span>
                  <ChevronRight size={16} />
                </div>
              </Link>
            </TooltipTrigger>
            <TooltipContent>View asset details and telemetry</TooltipContent>
          </Tooltip>
        ))}
      </div>

      {/* Pagination (FS-127) */}
      {total > 0 && (
        <div className="flex items-center justify-between">
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
              disabled={!assetsData?.hasMore}
              className="px-3 py-1 text-sm rounded border border-opsgrid-border text-opsgrid-text-secondary hover:border-opsgrid-primary disabled:opacity-40 disabled:cursor-not-allowed disabled:hover:border-opsgrid-border"
            >
              Next
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

export default Assets

import { FC, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { Box, ChevronRight, X } from 'lucide-react'
import { useQuery } from '@tanstack/react-query'
import { useAssets } from '../hooks'
import { assetsApi, workcellsApi } from '../api'
import { Tooltip, TooltipTrigger, TooltipContent } from '../components/ui'

const Assets: FC = () => {
  // FS-127: page through the FS-82 envelope. Page size comes from the limit the
  // backend echoes back; skip is part of the queryKey via the hook's params.
  const [skip, setSkip] = useState(0)

  // Filter bar (P6, page-enhancement review). workcell/type/active existed as query
  // params on the backend for as long as the route has; the page sent none of them,
  // so finding one machine meant paging the whole estate. `search` is the one new
  // param (name ILIKE, added with this bar); it is debounced so the request follows
  // the operator, not every keystroke.
  const [searchInput, setSearchInput] = useState('')
  const [search, setSearch] = useState('')
  const [workcellId, setWorkcellId] = useState('')
  const [assetTypeId, setAssetTypeId] = useState('')
  const [activeOnly, setActiveOnly] = useState('') // '' | 'active' | 'inactive'

  useEffect(() => {
    const handle = setTimeout(() => {
      setSearch(searchInput)
      setSkip(0)
    }, 300)
    return () => clearTimeout(handle)
  }, [searchInput])

  const params = useMemo(
    () => ({
      skip,
      search: search || undefined,
      workcellId: workcellId || undefined,
      assetTypeId: assetTypeId || undefined,
      isActive: activeOnly === '' ? undefined : activeOnly === 'active',
    }),
    [skip, search, workcellId, assetTypeId, activeOnly],
  )
  const { data: assetsData, isLoading, isError } = useAssets(params)

  const { data: workcells } = useQuery({
    queryKey: ['workcells-for-filter'],
    queryFn: () => workcellsApi.list(),
  })
  const { data: assetTypes } = useQuery({
    queryKey: ['asset-types-for-filter'],
    queryFn: () => assetsApi.getTypes(),
  })

  const anyFilterActive =
    search !== '' || workcellId !== '' || assetTypeId !== '' || activeOnly !== ''
  const applyFilter = (setter: (v: string) => void) => (value: string) => {
    setter(value)
    setSkip(0)
  }
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

  // Without this, a failed fetch rendered the header over an empty grid — a
  // blank screen with no indication anything went wrong.
  if (isError) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="text-center">
          <p className="text-status-alarm">Failed to load assets.</p>
          <p className="text-sm text-opsgrid-text-secondary mt-1">
            Check your connection and try again.
          </p>
        </div>
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

      <div className="flex flex-wrap items-center gap-2">
        <input
          aria-label="Search assets by name"
          value={searchInput}
          onChange={(e) => setSearchInput(e.target.value)}
          placeholder="Search by name…"
          className="bg-opsgrid-bg border border-opsgrid-border rounded px-3 py-1.5 text-sm w-56 focus:border-opsgrid-primary focus:outline-none"
        />
        <select
          aria-label="Workcell"
          value={workcellId}
          onChange={(e) => applyFilter(setWorkcellId)(e.target.value)}
          className="bg-opsgrid-bg border border-opsgrid-border rounded px-2 py-1.5 text-sm focus:border-opsgrid-primary focus:outline-none"
        >
          <option value="">All workcells</option>
          {(workcells ?? []).map((workcell: any) => (
            <option key={workcell.id} value={workcell.id}>{workcell.name}</option>
          ))}
        </select>
        <select
          aria-label="Asset type"
          value={assetTypeId}
          onChange={(e) => applyFilter(setAssetTypeId)(e.target.value)}
          className="bg-opsgrid-bg border border-opsgrid-border rounded px-2 py-1.5 text-sm focus:border-opsgrid-primary focus:outline-none"
        >
          <option value="">All types</option>
          {(assetTypes ?? []).map((assetType: any) => (
            <option key={assetType.id} value={assetType.id}>{assetType.name}</option>
          ))}
        </select>
        <select
          aria-label="Active"
          value={activeOnly}
          onChange={(e) => applyFilter(setActiveOnly)(e.target.value)}
          className="bg-opsgrid-bg border border-opsgrid-border rounded px-2 py-1.5 text-sm focus:border-opsgrid-primary focus:outline-none"
        >
          <option value="">Active + inactive</option>
          <option value="active">Active only</option>
          <option value="inactive">Inactive only</option>
        </select>
        {anyFilterActive && (
          <button
            onClick={() => {
              setSearchInput('')
              setSearch('')
              setWorkcellId('')
              setAssetTypeId('')
              setActiveOnly('')
              setSkip(0)
            }}
            className="flex items-center gap-1 text-sm text-opsgrid-text-secondary hover:text-opsgrid-primary"
          >
            <X size={14} /> Reset
          </button>
        )}
      </div>

      {assets.length === 0 && (
        <div className="flex items-center justify-center h-48 border border-dashed border-opsgrid-border rounded-lg">
          <div className="text-center">
            <p className="text-opsgrid-text-secondary">
              {anyFilterActive ? 'No assets match the current filters.' : 'No assets registered yet.'}
            </p>
            <p className="text-sm text-opsgrid-text-secondary mt-1">
              {anyFilterActive
                ? 'Loosen a filter, or reset them all.'
                : 'Assets appear here once an edge agent enrolls and reports.'}
            </p>
          </div>
        </div>
      )}

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

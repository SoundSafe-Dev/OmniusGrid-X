import { FC, useEffect, useState } from 'react'
import { Database, Plus } from 'lucide-react'
import { Button } from '../ui/Button'
import { platformCorrelationApi, PlatformSourceType } from '../../api/platformCorrelation'

// Compact affordance to attach live platform data (sensor/asset telemetry, yard,
// transportation) to the current analysis session as a correlation source.
// Self-contained so it can be dropped into DataSourcesPanel with a one-line mount.
interface Props {
  sessionId: string
  onAttached?: () => void
}

export const PlatformDataSourcePicker: FC<Props> = ({ sessionId, onAttached }) => {
  const [types, setTypes] = useState<PlatformSourceType[]>([])
  const [sourceType, setSourceType] = useState('asset_telemetry')
  const [assetId, setAssetId] = useState('')
  const [busy, setBusy] = useState(false)
  const [status, setStatus] = useState<string | null>(null)
  // FS-549. The catch was `.catch(() => setTypes([]))` — a failed request left the list
  // empty and the component rendered an empty `<select>` and an enabled Add button, which
  // reads as "this platform has no data sources to offer" rather than "we could not ask".
  //
  // The user then picks nothing, presses Add, and gets a second failure from the attach
  // call — so the first failure is discovered through the second, one interaction later,
  // with nothing connecting them.
  const [typesError, setTypesError] = useState(false)
  const [loadingTypes, setLoadingTypes] = useState(true)

  useEffect(() => {
    let cancelled = false
    platformCorrelationApi
      .listSourceTypes()
      .then((loaded) => {
        if (cancelled) return
        setTypes(loaded)
        setTypesError(false)
      })
      .catch(() => {
        if (cancelled) return
        setTypes([])
        setTypesError(true)
      })
      .finally(() => {
        if (!cancelled) setLoadingTypes(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  const attach = async () => {
    if (!sessionId) return
    setBusy(true)
    setStatus(null)
    try {
      const params = sourceType === 'asset_telemetry' && assetId ? { asset_id: assetId } : {}
      const res = await platformCorrelationApi.attach(sessionId, sourceType, params)
      setStatus(`Added ${res.file_name} (${res.row_count} rows)`)
      setAssetId('')
      onAttached?.()
    } catch (e: any) {
      setStatus(e?.response?.data?.detail || 'Failed to attach platform data')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="px-2 pb-2">
      <div className="p-2 bg-opsgrid-bg rounded border border-opsgrid-border">
        <div className="flex items-center gap-1 text-xs font-medium text-opsgrid-text mb-2">
          <Database className="w-3.5 h-3.5" /> Add platform data
        </div>
        {typesError && (
          <p role="alert" className="text-[11px] mb-1 text-status-alarm">
            Could not load platform data sources. The list below is empty because the
            request failed, not because none exist.
          </p>
        )}
        <div className="flex gap-2">
          <select
            aria-label="Platform data source"
            disabled={loadingTypes || typesError}
            className="flex-1 text-xs px-2 py-1 bg-opsgrid-panel border border-opsgrid-border rounded text-opsgrid-text"
            value={sourceType}
            onChange={(e) => setSourceType(e.target.value)}
          >
            {types.map((t) => (
              <option key={t.source_type} value={t.source_type}>{t.label}</option>
            ))}
          </select>
          {sourceType === 'asset_telemetry' && (
            <input
              aria-label="Asset ID"
              placeholder="asset id"
              className="w-28 text-xs px-2 py-1 bg-opsgrid-panel border border-opsgrid-border rounded text-opsgrid-text"
              value={assetId}
              onChange={(e) => setAssetId(e.target.value)}
            />
          )}
          {/* Disabled when the source list could not be loaded: an enabled Add button
              over an empty select invites the user to discover the first failure via a
              second one, an interaction later. */}
          <Button
            size="sm"
            onClick={attach}
            loading={busy}
            disabled={typesError}
            aria-label="Attach platform data"
          >
            <Plus className="w-3 h-3" />
          </Button>
        </div>
        {status && <p className="text-[11px] mt-1 text-opsgrid-text-secondary">{status}</p>}
      </div>
    </div>
  )
}

export default PlatformDataSourcePicker

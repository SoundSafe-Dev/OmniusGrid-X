import { FC } from 'react'
import { Activity } from 'lucide-react'
import { Asset } from '../../types'
import { MachineryMetricPanel } from './MachineryMetricPanel'
import { AudioSensorPanel } from './AudioSensorPanel'

// Type-aware sensor pane switch (task B10/B11): AssetDetail mounts this once and
// the pane rendered depends on the asset's sensor_class (migration 024).
// Audio (B13) and video (B15) panels plug into the switch as they land.

interface Props {
  asset: Asset
  telemetry: Record<string, { value: number; unit?: string }> | null
}

const resolveClass = (asset: Asset): string =>
  asset.sensorClass ?? (asset as any).sensor_class ?? 'generic'

export const SensorPanels: FC<Props> = ({ asset, telemetry }) => {
  const sensorClass = resolveClass(asset)
  if (!telemetry && sensorClass !== 'video') return null

  let pane: JSX.Element | null = null
  let title = ''
  switch (sensorClass) {
    case 'machinery':
      title = 'Condition Monitoring'
      pane = <MachineryMetricPanel telemetry={telemetry ?? {}} />
      break
    case 'audio':
      title = 'Acoustic Monitoring'
      pane = <AudioSensorPanel telemetry={telemetry ?? {}} />
      break
    // case 'video': CameraFeedPanel (task B15)
    default:
      return null
  }

  return (
    <div className="bg-opsgrid-panel border border-opsgrid-border rounded-lg p-6" data-testid="sensor-panel">
      <h2 className="text-lg font-semibold mb-4 flex items-center gap-2">
        <Activity size={20} />
        {title}
      </h2>
      {pane}
    </div>
  )
}

export default SensorPanels

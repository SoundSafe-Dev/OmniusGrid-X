import { FC } from 'react'
import { Gauge } from 'lucide-react'

// Machinery pane (task B11): gauge bars with alarm bands for condition metrics.
// Pure render over the latest-telemetry record AssetDetail already fetches.

export interface MetricBand {
  metric: string
  label: string
  max: number
  warn: number // yellow above this
  alarm: number // red above this
  unit?: string
}

// Default condition-monitoring bands; vibration zones loosely follow ISO 10816.
export const DEFAULT_BANDS: MetricBand[] = [
  { metric: 'vibration_rms', label: 'Vibration', max: 12, warn: 2.8, alarm: 7.1, unit: 'mm/s' },
  { metric: 'vibration', label: 'Vibration', max: 3, warn: 1.0, alarm: 2.0, unit: 'g' },
  { metric: 'temperature', label: 'Temperature', max: 120, warn: 70, alarm: 90, unit: '°C' },
  { metric: 'tool_temperature', label: 'Tool Temp', max: 120, warn: 60, alarm: 85, unit: '°C' },
  { metric: 'load_percent', label: 'Load', max: 100, warn: 80, alarm: 95, unit: '%' },
  { metric: 'spindle_load', label: 'Spindle Load', max: 100, warn: 80, alarm: 95, unit: '%' },
  { metric: 'load', label: 'Load', max: 100, warn: 80, alarm: 95, unit: '%' },
  { metric: 'power_consumption', label: 'Power', max: 10, warn: 6, alarm: 8.5, unit: 'kW' },
]

export function zoneFor(value: number, band: MetricBand): 'ok' | 'warn' | 'alarm' {
  if (value >= band.alarm) return 'alarm'
  if (value >= band.warn) return 'warn'
  return 'ok'
}

const zoneColor = { ok: 'bg-status-running', warn: 'bg-status-warning', alarm: 'bg-status-alarm' }
const zoneText = { ok: 'text-status-running', warn: 'text-status-warning', alarm: 'text-status-alarm' }

interface Props {
  telemetry: Record<string, { value: number; unit?: string }>
  bands?: MetricBand[]
}

export const MachineryMetricPanel: FC<Props> = ({ telemetry, bands = DEFAULT_BANDS }) => {
  const rows = bands
    .filter((b) => telemetry[b.metric] !== undefined)
    .map((b) => ({ band: b, value: Number(telemetry[b.metric].value) }))

  if (rows.length === 0) {
    return (
      <p className="text-sm text-opsgrid-text-secondary">
        No condition-monitoring metrics reported by this asset.
      </p>
    )
  }

  return (
    <div className="space-y-4">
      {rows.map(({ band, value }) => {
        const zone = zoneFor(value, band)
        const pct = Math.min(100, Math.max(0, (value / band.max) * 100))
        return (
          <div key={band.metric} data-testid={`gauge-${band.metric}`}>
            <div className="flex justify-between text-sm mb-1">
              <span className="flex items-center gap-1 text-opsgrid-text">
                <Gauge className="w-3.5 h-3.5" /> {band.label}
              </span>
              <span className={`font-semibold ${zoneText[zone]}`} data-testid={`zone-${band.metric}`}>
                {value.toFixed(1)}{band.unit ?? telemetry[band.metric].unit ?? ''} · {zone.toUpperCase()}
              </span>
            </div>
            <div className="relative h-3 rounded bg-opsgrid-bg border border-opsgrid-border overflow-hidden">
              {/* alarm-band background markers */}
              <div className="absolute inset-y-0 bg-status-warning/20"
                style={{ left: `${(band.warn / band.max) * 100}%`, right: `${100 - (band.alarm / band.max) * 100}%` }} />
              <div className="absolute inset-y-0 right-0 bg-status-alarm/20"
                style={{ left: `${(band.alarm / band.max) * 100}%` }} />
              {/* value bar */}
              <div className={`absolute inset-y-0 left-0 ${zoneColor[zone]} transition-all`} style={{ width: `${pct}%` }} />
            </div>
          </div>
        )
      })}
    </div>
  )
}

export default MachineryMetricPanel

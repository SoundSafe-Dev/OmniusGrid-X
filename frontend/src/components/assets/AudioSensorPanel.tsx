import { FC } from 'react'
import { AudioLines } from 'lucide-react'

// Audio sensor pane (task B13): level meter + band-energy spectrum rendered from
// the audio feature telemetry the edge audio collector emits (audio_rms,
// audio_peak_hz, audio_band_low/mid/high). Pure over the latest-telemetry record.

interface Props {
  telemetry: Record<string, { value: number; unit?: string }>
}

const BANDS: Array<{ metric: string; label: string; hint: string }> = [
  { metric: 'audio_band_low', label: 'Low < 300 Hz', hint: 'rumble / imbalance' },
  { metric: 'audio_band_mid', label: 'Mid 0.3–2 kHz', hint: 'normal operation' },
  { metric: 'audio_band_high', label: 'High > 2 kHz', hint: 'bearing wear / friction' },
]

export function levelZone(rms: number): 'quiet' | 'normal' | 'loud' {
  if (rms >= 0.6) return 'loud'
  if (rms >= 0.05) return 'normal'
  return 'quiet'
}

const zoneColor = { quiet: 'bg-opsgrid-border', normal: 'bg-status-running', loud: 'bg-status-alarm' }

export const AudioSensorPanel: FC<Props> = ({ telemetry }) => {
  const rms = telemetry.audio_rms?.value
  if (rms === undefined) {
    return (
      <p className="text-sm text-opsgrid-text-secondary">
        No audio feature telemetry reported yet (expects audio_rms / audio_band_* metrics).
      </p>
    )
  }

  const zone = levelZone(rms)
  const peak = telemetry.audio_peak_hz?.value

  return (
    <div className="space-y-5" data-testid="audio-panel">
      {/* Level meter */}
      <div>
        <div className="flex justify-between text-sm mb-1">
          <span className="flex items-center gap-1 text-opsgrid-text">
            <AudioLines className="w-3.5 h-3.5" /> Level (RMS)
          </span>
          <span className="font-semibold text-opsgrid-text" data-testid="audio-level">
            {rms.toFixed(3)} · {zone.toUpperCase()}
          </span>
        </div>
        <div className="h-3 rounded bg-opsgrid-bg border border-opsgrid-border overflow-hidden">
          <div
            className={`h-full ${zoneColor[zone]} transition-all`}
            style={{ width: `${Math.min(100, rms * 100)}%` }}
          />
        </div>
      </div>

      {/* Dominant frequency */}
      {peak !== undefined && (
        <div className="text-sm text-opsgrid-text">
          Dominant frequency:{' '}
          <span className="font-semibold" data-testid="audio-peak">{Math.round(peak)} Hz</span>
        </div>
      )}

      {/* Band-energy spectrum */}
      <div>
        <p className="text-sm text-opsgrid-text mb-2">Band energy distribution</p>
        <div className="space-y-2">
          {BANDS.filter((b) => telemetry[b.metric] !== undefined).map((b) => {
            const frac = Math.min(1, Math.max(0, telemetry[b.metric].value))
            return (
              <div key={b.metric} data-testid={`band-${b.metric}`}>
                <div className="flex justify-between text-xs text-opsgrid-text-secondary mb-0.5">
                  <span>{b.label} <span className="opacity-70">({b.hint})</span></span>
                  <span>{(frac * 100).toFixed(0)}%</span>
                </div>
                <div className="h-2 rounded bg-opsgrid-bg border border-opsgrid-border overflow-hidden">
                  <div className="h-full bg-opsgrid-primary" style={{ width: `${frac * 100}%` }} />
                </div>
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}

export default AudioSensorPanel

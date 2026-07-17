import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { AudioSensorPanel, levelZone } from './AudioSensorPanel'
import { SensorPanels } from './SensorPanels'

const AUDIO_TELEMETRY = {
  audio_rms: { value: 0.22 },
  audio_peak_hz: { value: 912 },
  audio_band_low: { value: 0.31 },
  audio_band_mid: { value: 0.55 },
  audio_band_high: { value: 0.14 },
}

describe('levelZone', () => {
  it('classifies quiet/normal/loud', () => {
    expect(levelZone(0.01)).toBe('quiet')
    expect(levelZone(0.2)).toBe('normal')
    expect(levelZone(0.8)).toBe('loud')
  })
})

describe('AudioSensorPanel', () => {
  it('renders level, peak frequency, and band bars', () => {
    render(<AudioSensorPanel telemetry={AUDIO_TELEMETRY} />)
    expect(screen.getByTestId('audio-level').textContent).toContain('NORMAL')
    expect(screen.getByTestId('audio-peak').textContent).toBe('912 Hz')
    expect(screen.getByTestId('band-audio_band_low')).toBeInTheDocument()
    expect(screen.getByTestId('band-audio_band_high').textContent).toContain('14%')
  })

  it('shows an empty state without audio metrics', () => {
    render(<AudioSensorPanel telemetry={{ temperature: { value: 20 } }} />)
    expect(screen.getByText(/No audio feature telemetry/)).toBeInTheDocument()
  })
})

describe('SensorPanels audio case', () => {
  it('renders the acoustic pane for audio assets', () => {
    const asset: any = {
      id: 'asset-6', name: 'Mic', assetTypeId: 'audio_sensor', sensorClass: 'audio',
      currentPackmlState: 'Execute', isActive: true, isInMaintenance: false,
      createdAt: '', updatedAt: '',
    }
    render(<SensorPanels asset={asset} telemetry={AUDIO_TELEMETRY} />)
    expect(screen.getByText('Acoustic Monitoring')).toBeInTheDocument()
    expect(screen.getByTestId('audio-panel')).toBeInTheDocument()
  })
})

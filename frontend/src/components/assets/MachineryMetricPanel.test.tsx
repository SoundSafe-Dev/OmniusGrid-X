import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { DEFAULT_BANDS, MachineryMetricPanel, zoneFor } from './MachineryMetricPanel'
import { SensorPanels } from './SensorPanels'

describe('zoneFor', () => {
  const band = DEFAULT_BANDS.find((b) => b.metric === 'vibration_rms')!
  it('classifies ok/warn/alarm zones', () => {
    expect(zoneFor(1.0, band)).toBe('ok')
    expect(zoneFor(3.5, band)).toBe('warn')
    expect(zoneFor(8.0, band)).toBe('alarm')
  })
})

describe('MachineryMetricPanel', () => {
  it('renders gauges only for metrics present, with zone labels', () => {
    render(
      <MachineryMetricPanel
        telemetry={{
          vibration_rms: { value: 8.2, unit: 'mm/s' },
          temperature: { value: 55, unit: '°C' },
        }}
      />
    )
    expect(screen.getByTestId('gauge-vibration_rms')).toBeInTheDocument()
    expect(screen.getByTestId('zone-vibration_rms').textContent).toContain('ALARM')
    expect(screen.getByTestId('zone-temperature').textContent).toContain('OK')
    expect(screen.queryByTestId('gauge-load_percent')).toBeNull()
  })

  it('shows an empty state when no condition metrics exist', () => {
    render(<MachineryMetricPanel telemetry={{ progress: { value: 40 } }} />)
    expect(screen.getByText(/No condition-monitoring metrics/)).toBeInTheDocument()
  })
})

describe('SensorPanels switch', () => {
  const baseAsset: any = {
    id: 'a8', name: 'Vib', assetTypeId: 'vibration_sensor',
    currentPackmlState: 'Execute', isActive: true, isInMaintenance: false,
    createdAt: '', updatedAt: '',
  }

  it('renders the machinery pane for machinery assets', () => {
    render(
      <SensorPanels
        asset={{ ...baseAsset, sensorClass: 'machinery' }}
        telemetry={{ vibration_rms: { value: 2.0, unit: 'mm/s' } }}
      />
    )
    expect(screen.getByTestId('sensor-panel')).toBeInTheDocument()
    expect(screen.getByText('Condition Monitoring')).toBeInTheDocument()
  })

  it('renders nothing for generic assets', () => {
    const { container } = render(
      <SensorPanels asset={baseAsset} telemetry={{ temperature: { value: 20 } }} />
    )
    expect(container.firstChild).toBeNull()
  })
})

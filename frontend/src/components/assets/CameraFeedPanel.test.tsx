import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { CameraFeedPanel, streamUrlOf } from './CameraFeedPanel'
import { SensorPanels } from './SensorPanels'

const cameraAsset = (mediaConfig?: Record<string, any>): any => ({
  id: 'asset-7', name: 'Dock Camera', assetTypeId: 'video_camera',
  sensorClass: 'video', mediaConfig,
  currentPackmlState: 'Execute', isActive: true, isInMaintenance: false,
  createdAt: '', updatedAt: '',
})

const FRAME_TELEMETRY = {
  frame_brightness: { value: 121.4 },
  motion_score: { value: 0.32 },
  frames_analyzed: { value: 1440 },
}

describe('streamUrlOf', () => {
  it('reads mediaConfig.stream_url and handles absence', () => {
    expect(streamUrlOf(cameraAsset({ stream_url: 'http://cam/mjpeg' }))).toBe('http://cam/mjpeg')
    expect(streamUrlOf(cameraAsset())).toBeNull()
  })
})

describe('CameraFeedPanel', () => {
  it('renders the stream with a metric overlay', () => {
    render(<CameraFeedPanel asset={cameraAsset({ stream_url: 'http://cam/mjpeg' })} telemetry={FRAME_TELEMETRY} />)
    expect(screen.getByTestId('camera-stream')).toHaveAttribute('src', 'http://cam/mjpeg')
    expect(screen.getByTestId('overlay-brightness').textContent).toContain('121')
    expect(screen.getByTestId('overlay-motion').textContent).toContain('MOTION') // 0.32 >= threshold
    expect(screen.getByTestId('overlay-frames').textContent).toContain('1440')
  })

  it('falls back to a placeholder when the stream errors', () => {
    render(<CameraFeedPanel asset={cameraAsset({ stream_url: 'http://cam/mjpeg' })} telemetry={{}} />)
    fireEvent.error(screen.getByTestId('camera-stream'))
    expect(screen.getByTestId('camera-placeholder')).toBeInTheDocument()
    expect(screen.getByText(/Stream unreachable/)).toBeInTheDocument()
  })

  it('shows demo mode when no stream is configured', () => {
    render(<CameraFeedPanel asset={cameraAsset()} telemetry={{ motion_score: { value: 0.02 } }} />)
    expect(screen.getByText(/No stream configured/)).toBeInTheDocument()
    expect(screen.getByTestId('overlay-motion').textContent).toContain('still')
  })
})

describe('SensorPanels video case', () => {
  it('renders the camera pane for video assets even without telemetry', () => {
    render(<SensorPanels asset={cameraAsset()} telemetry={null} />)
    expect(screen.getByText('Camera Feed')).toBeInTheDocument()
    expect(screen.getByTestId('camera-panel')).toBeInTheDocument()
  })
})

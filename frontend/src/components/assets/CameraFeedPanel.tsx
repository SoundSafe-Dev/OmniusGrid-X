import { FC, useState } from 'react'
import { Camera, VideoOff } from 'lucide-react'
import { Asset } from '../../types'

// Camera pane (task B15): live feed from the asset's media_config.stream_url
// (MJPEG renders natively in an <img>) with a frame-metric overlay from the
// video collector's telemetry (B14). Falls back to a demo placeholder when the
// stream is absent/unreachable, so demos work offline.

export const MOTION_THRESHOLD = 0.15

interface Props {
  asset: Asset
  telemetry: Record<string, { value: number; unit?: string }>
}

export function streamUrlOf(asset: Asset): string | null {
  const media = asset.mediaConfig ?? (asset as any).media_config ?? {}
  return media.stream_url ?? null
}

export const CameraFeedPanel: FC<Props> = ({ asset, telemetry }) => {
  const [streamFailed, setStreamFailed] = useState(false)
  const url = streamUrlOf(asset)
  const showStream = !!url && !streamFailed

  const brightness = telemetry.frame_brightness?.value
  const motion = telemetry.motion_score?.value
  const frames = telemetry.frames_analyzed?.value
  const motionActive = motion !== undefined && motion >= MOTION_THRESHOLD

  return (
    <div data-testid="camera-panel">
      <div className="relative rounded-lg overflow-hidden border border-opsgrid-border bg-black aspect-video">
        {showStream ? (
          <img
            src={url!}
            alt={`Live feed: ${asset.name}`}
            className="w-full h-full object-contain"
            onError={() => setStreamFailed(true)}
            data-testid="camera-stream"
          />
        ) : (
          <div
            className="w-full h-full flex flex-col items-center justify-center text-opsgrid-text-secondary gap-2 py-16"
            data-testid="camera-placeholder"
          >
            <VideoOff className="w-8 h-8" />
            <span className="text-sm">
              {url ? 'Stream unreachable — showing metrics only' : 'No stream configured (demo mode)'}
            </span>
          </div>
        )}

        {/* metric overlay */}
        <div className="absolute bottom-0 inset-x-0 bg-black/60 px-3 py-1.5 flex items-center gap-4 text-xs text-white">
          <span className="flex items-center gap-1"><Camera className="w-3 h-3" /> {asset.name}</span>
          {brightness !== undefined && <span data-testid="overlay-brightness">☀ {Math.round(brightness)}</span>}
          {motion !== undefined && (
            <span
              data-testid="overlay-motion"
              className={motionActive ? 'text-red-400 font-semibold animate-pulse' : ''}
            >
              {motionActive ? '● MOTION' : '○ still'} ({(motion * 100).toFixed(0)}%)
            </span>
          )}
          {frames !== undefined && <span data-testid="overlay-frames">{frames} frames</span>}
        </div>
      </div>
    </div>
  )
}

export default CameraFeedPanel

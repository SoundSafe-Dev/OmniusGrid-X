# Audio & video sensor capture — real-mode deployment (FS-63)

The edge agent's `audio` and `video` collectors default to **simulate** so
demos work with zero hardware. This guide is the cutover to real capture.

## What flows where

Both collectors emit **feature telemetry** through the normal
ingest → Redpanda → Telemetry path — never raw media:

| Collector | Metrics emitted | Frontend pane |
|---|---|---|
| `audio` | `audio_rms`, `audio_peak_hz`, `audio_band_low/mid/high` | AudioSensorPanel (level meter + band view) |
| `video` | `frame_brightness`, `frame_contrast`, `motion_score`, `frames_analyzed` | CameraFeedPanel (metrics overlay) |

Live video itself is **not** proxied by the platform: the CameraFeedPanel
connects the browser straight to the asset's `media_config.stream_url`.
Set that on the asset (`PUT /api/v1/assets/{id}` → `media_config:
{"stream_url": "http://cam.local/mjpeg"}`) and give the asset
`sensor_class: video` so AssetDetail renders the camera pane.

Readings from simulate mode are stamped `simulated: true` in telemetry
metadata, so dashboards can tell demo data from real.

## Audio (`collector_type: audio`)

```yaml
- asset_id: "compressor-room-mic-001"
  collector_type: "audio"
  enabled: true
  config:
    source: "device"      # "simulate" = synthetic tone (default)
    sample_rate: 16000
    frame_seconds: 1.0    # capture window per reading
    poll_interval: 10     # seconds between readings
```

Host requirements for `source: device`:
- `pip install sounddevice` (pulls PortAudio; on Debian/Ubuntu also
  `apt install libportaudio2`).
- Microphone permission: on Linux add the agent user to the `audio` group;
  on macOS grant mic access to the python binary the agent runs under.
- The collector degrades gracefully — if `sounddevice` or the device is
  unavailable it logs and keeps emitting nothing rather than crashing the
  agent.

## Video (`collector_type: video`)

```yaml
- asset_id: "dock-camera-001"
  collector_type: "video"
  enabled: true
  config:
    source: "stream"      # "simulate" = synthetic frames (default)
    stream_url: "rtsp://192.168.1.210:554/stream1"
    poll_interval: 10
```

- `stream_url` accepts anything OpenCV's `VideoCapture` does: RTSP, MJPEG
  HTTP URLs, or a local device index passed as a string (`"0"`).
- Requires `opencv-python` (already in the agent's requirements).
- Analysis is one frame per `poll_interval` — the collector does not decode
  the stream continuously.

## Cutover checklist

1. Add/enable the collector entry in the agent's collectors YAML
   (`OPSGRID_COLLECTORS_CONFIG`, see `edge-agent/config/poc_collectors.yml`
   items 10–11 for templates) with `source: device` / `source: stream`.
2. Set the asset's `sensor_class` (`audio` / `video`) and, for cameras,
   `media_config.stream_url` — this is what switches the AssetDetail pane.
3. Restart the agent (`systemctl restart opsgrid-agent`); confirm
   `collector_started` in the agent log and the new metrics in
   `GET /api/v1/telemetry/{asset_id}/metrics`.
4. Verify the telemetry is NOT stamped `simulated: true`.

`EDGE_REQUIRE_EXPLICIT_SOURCES=true` (recommended in production since
Sprint D) makes the agent refuse to start collectors whose `source` was
omitted — a config that silently fell back to synthetic data now fails loudly.

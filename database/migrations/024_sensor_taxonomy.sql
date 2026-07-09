-- 024_sensor_taxonomy.sql
-- Sensor taxonomy for assets (Phase B, task 10).
-- Adds a sensor_class (machinery | audio | video | environmental | generic) to
-- asset types and assets (per-asset override), plus media_config on assets for
-- audio/video sources (stream_url, sample_rate, ...). Seeds demo sensor asset
-- types so the type-aware AssetDetail panes are demoable out of the box.

ALTER TABLE asset_types ADD COLUMN IF NOT EXISTS sensor_class VARCHAR(50) DEFAULT 'generic';
ALTER TABLE assets ADD COLUMN IF NOT EXISTS sensor_class VARCHAR(50);
ALTER TABLE assets ADD COLUMN IF NOT EXISTS media_config JSONB DEFAULT '{}';

CREATE INDEX IF NOT EXISTS idx_assets_sensor_class ON assets (sensor_class);

-- Backfill sensor_class for known machinery categories.
UPDATE asset_types SET sensor_class = 'machinery'
WHERE sensor_class = 'generic'
  AND category IN ('additive_manufacturing', 'subtractive_manufacturing', 'material_handling');

-- Seed demo sensor asset types (idempotent by name).
INSERT INTO asset_types (id, name, category, sensor_class, packml_config, telemetry_schema, action_space)
SELECT gen_random_uuid(), v.name, v.category, v.sensor_class, '{}'::jsonb, v.telemetry_schema::jsonb, '{}'::jsonb
FROM (VALUES
  ('audio_sensor', 'acoustic_monitoring', 'audio',
   '{"metrics": ["audio_rms", "audio_peak_hz", "audio_band_low", "audio_band_mid", "audio_band_high"]}'),
  ('video_camera', 'visual_monitoring', 'video',
   '{"metrics": ["frame_brightness", "motion_score", "frames_analyzed"]}'),
  ('vibration_sensor', 'condition_monitoring', 'machinery',
   '{"metrics": ["vibration_rms", "temperature", "load_percent"]}')
) AS v(name, category, sensor_class, telemetry_schema)
WHERE NOT EXISTS (SELECT 1 FROM asset_types t WHERE t.name = v.name);

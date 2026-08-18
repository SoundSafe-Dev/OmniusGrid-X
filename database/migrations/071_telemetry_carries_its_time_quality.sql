-- 071 — telemetry says what its timestamp is worth (FS-760, DDIL S8)
--
-- The edge agent samples the server clock and maintains an EWMA of the offset. It has done
-- so since task 21. `ClockSkewEstimator.correct()` had no callers anywhere in the agent, so
-- the offset was used to judge request freshness and command staleness and was NEVER applied
-- to a telemetry timestamp — every row in this table carries the raw clock of a device that
-- frequently has no NTP.
--
-- Correcting it is half the fix. The other half is that the correction cannot always be
-- trusted, and silently applying it would be worse than not applying it at all:
--
--   synced     a clock sample within the freshness window; the offset is current
--   holdover   calibrated once, but the last sample is stale. The offset is being carried
--              forward and the device has been drifting since, by an unknowable amount
--   unsynced   never calibrated. The correction is zero. This is the honest answer for an
--              air-gapped deployment, which never reaches a server to sample
--   unknown     the agent did not say. Every agent predating this release, which is the
--              whole fleet on the day it ships
--
-- `unknown` is the DEFAULT deliberately. Backfilling old rows to `unsynced` would assert
-- something about clocks nobody measured; `unknown` says only what is true, which is that
-- the row predates the field.
--
-- This is what moves OG-AU-006 (NIST SP 800-171 03.03.07, synchronised timestamps) off
-- `absent` for the air-gapped profile. Not to `implemented` — there is still no
-- authoritative time source and an air-gapped device still cannot sync. What changes is that
-- its data no longer claims a precision it does not have, and an assessor can query for it.

ALTER TABLE telemetry
    ADD COLUMN IF NOT EXISTS time_quality VARCHAR(16) NOT NULL DEFAULT 'unknown';

COMMENT ON COLUMN telemetry.time_quality IS
    'What this row''s timestamp is worth: synced | holdover | unsynced | unknown. '
    'Set from the edge agent''s clock-skew estimator at send time (FS-760).';

-- Partial index, not a full one. The overwhelming majority of rows on a healthy fleet are
-- `synced`, and the queries that matter ask the opposite question — "which readings cannot
-- be trusted for ordering" — so indexing only the degraded states keeps this small enough
-- to be free on a hypertable that grows continuously.
CREATE INDEX IF NOT EXISTS idx_telemetry_degraded_time
    ON telemetry (time_quality, time DESC)
    WHERE time_quality <> 'synced';

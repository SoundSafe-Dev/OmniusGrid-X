-- 042_fleet_ui_columns.sql
--
-- The fleet/TMS/YMS frontend (driver roster, carrier scorecard, shipment
-- board, yard inventory, dock schedule) has long declared attributes the
-- backing tables never had columns for — driver endorsements/license expiry
-- and computed HOS remaining, carrier compliance/on-time/authority/SCAC,
-- shipment PO/freight/pallet, and yard-trailer plate/detention exposure — so
-- those fields rendered blank and could not be seeded for the demo. This adds
-- the columns to match the ORM models (app/db/models.py) + the
-- /transportation/{drivers,shipments} and /yard/{trailers,dock/appointments}
-- responses.
--
-- Idempotent + adoption-safe: ADD COLUMN IF NOT EXISTS is a no-op on
-- create_all-built (SQLite dev) or already-migrated databases.

-- Driver
ALTER TABLE drivers ADD COLUMN IF NOT EXISTS endorsements JSONB;
ALTER TABLE drivers ADD COLUMN IF NOT EXISTS license_expiry TIMESTAMPTZ;
ALTER TABLE drivers ADD COLUMN IF NOT EXISTS hos_drive_hours_remaining DOUBLE PRECISION;
ALTER TABLE drivers ADD COLUMN IF NOT EXISTS hos_duty_hours_remaining DOUBLE PRECISION;

-- Carrier
ALTER TABLE carriers ADD COLUMN IF NOT EXISTS compliance_score DOUBLE PRECISION;
ALTER TABLE carriers ADD COLUMN IF NOT EXISTS on_time_performance DOUBLE PRECISION;
ALTER TABLE carriers ADD COLUMN IF NOT EXISTS operating_authority VARCHAR(50);
ALTER TABLE carriers ADD COLUMN IF NOT EXISTS scac VARCHAR(8);

-- Shipment
ALTER TABLE shipments ADD COLUMN IF NOT EXISTS po_number VARCHAR(100);
ALTER TABLE shipments ADD COLUMN IF NOT EXISTS freight_charge DOUBLE PRECISION;
ALTER TABLE shipments ADD COLUMN IF NOT EXISTS pallet_count INTEGER;

-- YardTrailer
ALTER TABLE yard_trailers ADD COLUMN IF NOT EXISTS license_plate VARCHAR(32);
ALTER TABLE yard_trailers ADD COLUMN IF NOT EXISTS detention_cost DOUBLE PRECISION;
ALTER TABLE yard_trailers ADD COLUMN IF NOT EXISTS detention_risk VARCHAR(20);

-- 041_vehicle_fleet_columns.sql
--
-- The frontend Vehicle type (and the vehicle-detail modal) has long declared
-- fleet-asset attributes — vehicle type, fuel type, license plate, DOT number,
-- gross vehicle weight, engine hours, registration/inspection dates — but the
-- `vehicles` table never had columns for them, so those fields rendered blank
-- and could not be seeded for the demo. This adds the columns to match the ORM
-- model (app/db/logistics_models.py) + the /transportation/vehicles response.
--
-- Idempotent + adoption-safe: ADD COLUMN IF NOT EXISTS is a no-op on
-- create_all-built (SQLite dev) or already-migrated databases.

ALTER TABLE vehicles ADD COLUMN IF NOT EXISTS vehicle_type VARCHAR(50);
ALTER TABLE vehicles ADD COLUMN IF NOT EXISTS fuel_type VARCHAR(50);
ALTER TABLE vehicles ADD COLUMN IF NOT EXISTS license_plate VARCHAR(32);
ALTER TABLE vehicles ADD COLUMN IF NOT EXISTS dot_number VARCHAR(32);
ALTER TABLE vehicles ADD COLUMN IF NOT EXISTS gross_vehicle_weight_kg DOUBLE PRECISION;
ALTER TABLE vehicles ADD COLUMN IF NOT EXISTS engine_hours DOUBLE PRECISION;
ALTER TABLE vehicles ADD COLUMN IF NOT EXISTS registration_expiry TIMESTAMPTZ;
ALTER TABLE vehicles ADD COLUMN IF NOT EXISTS inspection_due TIMESTAMPTZ;

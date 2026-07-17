-- 025_fleet_logistics.sql
-- Vehicles, geofencing, and maintenance tables (Phase D, tasks 20-21) so the
-- Transportation page panels that were frontend-mock-only get a real backend.

CREATE TABLE IF NOT EXISTS vehicles (
    id                  VARCHAR(36) PRIMARY KEY,
    organization_id     VARCHAR(36),
    carrier_id          VARCHAR(36),
    vehicle_number      VARCHAR(100) NOT NULL,
    vin                 VARCHAR(64),
    make                VARCHAR(100),
    model               VARCHAR(100),
    year                INTEGER,
    status              VARCHAR(50) DEFAULT 'idle',
    fuel_level_percent  DOUBLE PRECISION,
    odometer_miles      DOUBLE PRECISION,
    geotab_device_id    VARCHAR(100),
    current_driver_id   VARCHAR(36),
    last_location       JSONB DEFAULT '{}',
    is_active           BOOLEAN DEFAULT TRUE,
    created_at          TIMESTAMPTZ DEFAULT now(),
    updated_at          TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_vehicles_org ON vehicles (organization_id);
CREATE INDEX IF NOT EXISTS idx_vehicles_carrier ON vehicles (carrier_id);

CREATE TABLE IF NOT EXISTS geofence_zones (
    id               VARCHAR(36) PRIMARY KEY,
    organization_id  VARCHAR(36),
    name             VARCHAR(255) NOT NULL,
    zone_type        VARCHAR(50) DEFAULT 'circle',
    center_lat       DOUBLE PRECISION,
    center_lng       DOUBLE PRECISION,
    radius_meters    DOUBLE PRECISION,
    polygon          JSONB,
    trigger_on       VARCHAR(20) DEFAULT 'both',
    severity         VARCHAR(20) DEFAULT 'warning',
    is_active        BOOLEAN DEFAULT TRUE,
    created_at       TIMESTAMPTZ DEFAULT now(),
    updated_at       TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_geofence_zones_org ON geofence_zones (organization_id);

CREATE TABLE IF NOT EXISTS geofence_alerts (
    id               VARCHAR(36) PRIMARY KEY,
    organization_id  VARCHAR(36),
    zone_id          VARCHAR(36) NOT NULL,
    vehicle_id       VARCHAR(36),
    event_type       VARCHAR(20) NOT NULL,
    severity         VARCHAR(20) DEFAULT 'warning',
    location         JSONB DEFAULT '{}',
    acknowledged     BOOLEAN DEFAULT FALSE,
    acknowledged_by  VARCHAR(36),
    acknowledged_at  TIMESTAMPTZ,
    created_at       TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_geofence_alerts_zone ON geofence_alerts (zone_id);
CREATE INDEX IF NOT EXISTS idx_geofence_alerts_created ON geofence_alerts (created_at);

CREATE TABLE IF NOT EXISTS maintenance_schedules (
    id                  VARCHAR(36) PRIMARY KEY,
    organization_id     VARCHAR(36),
    vehicle_id          VARCHAR(36) NOT NULL,
    maintenance_type    VARCHAR(100) NOT NULL,
    description         TEXT,
    due_date            TIMESTAMPTZ,
    due_odometer_miles  DOUBLE PRECISION,
    status              VARCHAR(50) DEFAULT 'scheduled',
    estimated_cost      DOUBLE PRECISION,
    completed_at        TIMESTAMPTZ,
    created_at          TIMESTAMPTZ DEFAULT now(),
    updated_at          TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_maintenance_vehicle ON maintenance_schedules (vehicle_id);

CREATE TABLE IF NOT EXISTS repair_orders (
    id               VARCHAR(36) PRIMARY KEY,
    organization_id  VARCHAR(36),
    vehicle_id       VARCHAR(36) NOT NULL,
    schedule_id      VARCHAR(36),
    title            VARCHAR(255) NOT NULL,
    description      TEXT,
    status           VARCHAR(50) DEFAULT 'open',
    priority         VARCHAR(20) DEFAULT 'medium',
    vendor           VARCHAR(255),
    cost             DOUBLE PRECISION,
    category         VARCHAR(100),
    opened_at        TIMESTAMPTZ DEFAULT now(),
    completed_at     TIMESTAMPTZ,
    created_at       TIMESTAMPTZ DEFAULT now(),
    updated_at       TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_repair_orders_vehicle ON repair_orders (vehicle_id);

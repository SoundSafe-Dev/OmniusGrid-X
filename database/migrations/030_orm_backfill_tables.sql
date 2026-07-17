-- 030_orm_backfill_tables.sql (FS-24, regenerated FS-56)
-- Backfills the 21 tables that previously existed ONLY via SQLAlchemy
-- create_all() (yard, transportation, geotab, analysis-session, intake), so the
-- SQL migration path builds a complete schema without depending on the API
-- process having run init_db() first.
--
-- Generated from the ORM metadata (postgresql dialect) by
-- backend/scripts/gen_030.py. FS-56 regeneration: UUIDString now renders
-- native UUID on Postgres, fixing the 28 varchar->uuid cross-type FKs that
-- made the original file unappliable on a migrations-built database (it
-- failed at the first FK to organizations). Intra-set FKs are emitted as
-- trailing guarded ALTERs to break the dock_doors<->shipments<->yard_trailers
-- cycle. All statements are IF NOT EXISTS / guarded, so this is safe to run
-- on a database already built via init_db().
--
-- NOTE: a pre-FS-56 database built via create_all (VARCHAR ids) must run
-- 032_uuid_consolidation.sql (applied after this) to converge.

CREATE TABLE IF NOT EXISTS yard_trailers (
	id UUID NOT NULL, 
	organization_id UUID NOT NULL, 
	trailer_number VARCHAR(50) NOT NULL, 
	carrier_id UUID, 
	trailer_type VARCHAR(50), 
	status VARCHAR(50), 
	yard_location VARCHAR(100), 
	seal_number VARCHAR(50), 
	seal_status VARCHAR(20), 
	weight_lbs NUMERIC, 
	check_in_at TIMESTAMP WITH TIME ZONE, 
	check_out_at TIMESTAMP WITH TIME ZONE, 
	dock_door_id UUID, 
	driver_id UUID, 
	shipment_id UUID, 
	temperature_setpoint NUMERIC, 
	temperature_actual NUMERIC, 
	meta_data JSON, 
	created_at TIMESTAMP WITH TIME ZONE, 
	updated_at TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (id), 
	FOREIGN KEY(organization_id) REFERENCES organizations (id)
);

CREATE TABLE IF NOT EXISTS dock_doors (
	id UUID NOT NULL, 
	organization_id UUID NOT NULL, 
	door_number VARCHAR(50) NOT NULL, 
	door_type VARCHAR(50), 
	status VARCHAR(50), 
	equipment_capabilities JSON, 
	current_trailer_id UUID, 
	last_occupied_at TIMESTAMP WITH TIME ZONE, 
	is_active BOOLEAN, 
	created_at TIMESTAMP WITH TIME ZONE, 
	updated_at TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (id), 
	FOREIGN KEY(organization_id) REFERENCES organizations (id)
);

CREATE TABLE IF NOT EXISTS carriers (
	id UUID NOT NULL, 
	organization_id UUID NOT NULL, 
	carrier_name VARCHAR(255) NOT NULL, 
	dot_number VARCHAR(50), 
	mc_number VARCHAR(50), 
	ctpat_certified BOOLEAN, 
	ctpat_expires_at TIMESTAMP WITH TIME ZONE, 
	insurance_on_file BOOLEAN, 
	insurance_expires_at TIMESTAMP WITH TIME ZONE, 
	safety_rating VARCHAR(20), 
	csa_score NUMERIC, 
	contract_rate JSON, 
	is_active BOOLEAN, 
	contact_info JSON, 
	created_at TIMESTAMP WITH TIME ZONE, 
	updated_at TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (id), 
	FOREIGN KEY(organization_id) REFERENCES organizations (id)
);

CREATE TABLE IF NOT EXISTS shipments (
	id UUID NOT NULL, 
	organization_id UUID NOT NULL, 
	carrier_id UUID, 
	driver_id UUID, 
	trailer_id UUID, 
	shipment_number VARCHAR(100) NOT NULL, 
	pro_number VARCHAR(100), 
	bol_number VARCHAR(100), 
	shipment_type VARCHAR(50), 
	status VARCHAR(50), 
	origin JSON, 
	destination JSON, 
	scheduled_pickup TIMESTAMP WITH TIME ZONE, 
	actual_pickup TIMESTAMP WITH TIME ZONE, 
	scheduled_delivery TIMESTAMP WITH TIME ZONE, 
	actual_delivery TIMESTAMP WITH TIME ZONE, 
	priority VARCHAR(20), 
	total_weight_lbs NUMERIC, 
	total_pieces INTEGER, 
	hazmat BOOLEAN, 
	temperature_required BOOLEAN, 
	temperature_min NUMERIC, 
	temperature_max NUMERIC, 
	route_id UUID, 
	meta_data JSON, 
	created_at TIMESTAMP WITH TIME ZONE, 
	updated_at TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (id), 
	FOREIGN KEY(organization_id) REFERENCES organizations (id)
);

CREATE TABLE IF NOT EXISTS routes (
	id UUID NOT NULL, 
	organization_id UUID NOT NULL, 
	route_name VARCHAR(255), 
	origin JSON NOT NULL, 
	destination JSON NOT NULL, 
	waypoints JSON, 
	total_distance_miles NUMERIC, 
	estimated_duration_hours NUMERIC, 
	fuel_cost_estimate NUMERIC, 
	toll_cost_estimate NUMERIC, 
	optimization_criteria VARCHAR(50), 
	is_active BOOLEAN, 
	created_at TIMESTAMP WITH TIME ZONE, 
	updated_at TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (id), 
	FOREIGN KEY(organization_id) REFERENCES organizations (id)
);

CREATE TABLE IF NOT EXISTS analysis_sessions (
	id UUID NOT NULL, 
	user_id UUID NOT NULL, 
	organization_id UUID NOT NULL, 
	title VARCHAR(500) NOT NULL, 
	description TEXT, 
	status VARCHAR(50), 
	created_at TIMESTAMP WITH TIME ZONE, 
	updated_at TIMESTAMP WITH TIME ZONE, 
	last_accessed_at TIMESTAMP WITH TIME ZONE, 
	context_snapshot JSON, 
	goals_snapshot JSON, 
	meta_data JSON, 
	PRIMARY KEY (id), 
	FOREIGN KEY(user_id) REFERENCES users (id), 
	FOREIGN KEY(organization_id) REFERENCES organizations (id)
);

CREATE TABLE IF NOT EXISTS intake_items (
	id UUID NOT NULL, 
	user_id UUID NOT NULL, 
	organization_id UUID NOT NULL, 
	title VARCHAR(255) NOT NULL, 
	description TEXT, 
	data_type VARCHAR(50), 
	category VARCHAR(100), 
	file_name VARCHAR(255), 
	file_content TEXT, 
	processed_data JSON, 
	status VARCHAR(50), 
	analysis_result JSON, 
	created_at TIMESTAMP WITH TIME ZONE, 
	analyzed_at TIMESTAMP WITH TIME ZONE, 
	meta_data JSON, 
	PRIMARY KEY (id), 
	FOREIGN KEY(user_id) REFERENCES users (id), 
	FOREIGN KEY(organization_id) REFERENCES organizations (id)
);

CREATE TABLE IF NOT EXISTS geotab_diagnostics (
	id UUID NOT NULL, 
	device_id VARCHAR(100) NOT NULL, 
	vehicle_id VARCHAR(100), 
	organization_id UUID, 
	dtc_code VARCHAR(20) NOT NULL, 
	severity VARCHAR(20), 
	description TEXT, 
	status VARCHAR(50), 
	first_seen_at TIMESTAMP WITH TIME ZONE, 
	last_seen_at TIMESTAMP WITH TIME ZONE, 
	cleared_at TIMESTAMP WITH TIME ZONE, 
	battery_voltage NUMERIC(5, 2), 
	fuel_level NUMERIC(5, 2), 
	odometer BIGINT, 
	engine_hours NUMERIC(10, 2), 
	meta_data JSON, 
	created_at TIMESTAMP WITH TIME ZONE, 
	updated_at TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (id), 
	FOREIGN KEY(organization_id) REFERENCES organizations (id)
);

CREATE INDEX IF NOT EXISTS ix_geotab_diagnostics_device_id ON geotab_diagnostics (device_id);

CREATE TABLE IF NOT EXISTS yard_checkpoints (
	id UUID NOT NULL, 
	organization_id UUID NOT NULL, 
	trailer_id UUID, 
	checkpoint_type VARCHAR(50) NOT NULL, 
	checkpoint_name VARCHAR(100), 
	passed_at TIMESTAMP WITH TIME ZONE, 
	weight_lbs NUMERIC, 
	inspection_status VARCHAR(50), 
	inspector_id VARCHAR(36), 
	meta_data JSON, 
	created_at TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (id), 
	FOREIGN KEY(organization_id) REFERENCES organizations (id)
);

CREATE TABLE IF NOT EXISTS drivers (
	id UUID NOT NULL, 
	organization_id UUID NOT NULL, 
	carrier_id UUID, 
	first_name VARCHAR(100) NOT NULL, 
	last_name VARCHAR(100) NOT NULL, 
	license_number VARCHAR(100), 
	license_state VARCHAR(50), 
	cdl_class VARCHAR(20), 
	hazmat_endorsed BOOLEAN, 
	medical_cert_expires TIMESTAMP WITH TIME ZONE, 
	dq_file_complete BOOLEAN, 
	current_hos_status VARCHAR(50), 
	hos_drive_hours_today NUMERIC, 
	hos_on_duty_hours_today NUMERIC, 
	hos_cycle_hours NUMERIC, 
	eld_device_id VARCHAR(100), 
	phone VARCHAR(50), 
	email VARCHAR(255), 
	is_active BOOLEAN, 
	created_at TIMESTAMP WITH TIME ZONE, 
	updated_at TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (id), 
	FOREIGN KEY(organization_id) REFERENCES organizations (id)
);

CREATE TABLE IF NOT EXISTS load_plans (
	id UUID NOT NULL, 
	organization_id UUID NOT NULL, 
	shipment_id UUID, 
	trailer_id UUID, 
	planned_by VARCHAR(36), 
	planned_at TIMESTAMP WITH TIME ZONE, 
	load_sequence JSON, 
	weight_distribution JSON, 
	space_utilization_percent NUMERIC, 
	temperature_zones JSON, 
	special_instructions TEXT, 
	is_executed BOOLEAN, 
	executed_at TIMESTAMP WITH TIME ZONE, 
	meta_data JSON, 
	created_at TIMESTAMP WITH TIME ZONE, 
	updated_at TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (id), 
	FOREIGN KEY(organization_id) REFERENCES organizations (id)
);

CREATE TABLE IF NOT EXISTS freight_charges (
	id UUID NOT NULL, 
	organization_id UUID NOT NULL, 
	shipment_id UUID, 
	carrier_id UUID, 
	charge_type VARCHAR(50) NOT NULL, 
	charge_description VARCHAR(255), 
	rate_basis VARCHAR(50), 
	quantity NUMERIC, 
	rate NUMERIC, 
	amount NUMERIC NOT NULL, 
	currency VARCHAR(10), 
	is_billed BOOLEAN, 
	billed_at TIMESTAMP WITH TIME ZONE, 
	invoice_number VARCHAR(100), 
	approved_by VARCHAR(36), 
	approved_at TIMESTAMP WITH TIME ZONE, 
	meta_data JSON, 
	created_at TIMESTAMP WITH TIME ZONE, 
	updated_at TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (id), 
	FOREIGN KEY(organization_id) REFERENCES organizations (id)
);

CREATE TABLE IF NOT EXISTS truck_asset_correlations (
	id UUID NOT NULL, 
	organization_id UUID NOT NULL, 
	shipment_id UUID, 
	trailer_id UUID, 
	asset_id UUID NOT NULL, 
	operation_id UUID, 
	truck_arrived_at TIMESTAMP WITH TIME ZONE, 
	asset_ready_at TIMESTAMP WITH TIME ZONE, 
	asset_completion_forecast TIMESTAMP WITH TIME ZONE, 
	readiness_gap_minutes NUMERIC, 
	load_start_at TIMESTAMP WITH TIME ZONE, 
	load_complete_at TIMESTAMP WITH TIME ZONE, 
	detention_incurred BOOLEAN, 
	detention_charge NUMERIC, 
	efficiency_score NUMERIC, 
	meta_data JSON, 
	created_at TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (id), 
	FOREIGN KEY(organization_id) REFERENCES organizations (id), 
	FOREIGN KEY(asset_id) REFERENCES assets (id), 
	FOREIGN KEY(operation_id) REFERENCES operations (id)
);

CREATE TABLE IF NOT EXISTS load_quality_logs (
	id UUID NOT NULL, 
	organization_id UUID NOT NULL, 
	shipment_id UUID, 
	trailer_id UUID, 
	asset_id UUID NOT NULL, 
	operation_id UUID, 
	defect_type VARCHAR(100), 
	severity VARCHAR(20), 
	quantity_affected NUMERIC, 
	root_cause_asset UUID NOT NULL, 
	root_cause_operation UUID, 
	manufacturing_correlation_score NUMERIC, 
	carrier_liable BOOLEAN, 
	claim_filed BOOLEAN, 
	claim_amount NUMERIC, 
	resolved_at TIMESTAMP WITH TIME ZONE, 
	meta_data JSON, 
	created_at TIMESTAMP WITH TIME ZONE, 
	updated_at TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (id), 
	FOREIGN KEY(organization_id) REFERENCES organizations (id), 
	FOREIGN KEY(asset_id) REFERENCES assets (id), 
	FOREIGN KEY(operation_id) REFERENCES operations (id), 
	FOREIGN KEY(root_cause_asset) REFERENCES assets (id), 
	FOREIGN KEY(root_cause_operation) REFERENCES operations (id)
);

CREATE TABLE IF NOT EXISTS session_data_sources (
	id UUID NOT NULL, 
	session_id UUID NOT NULL, 
	source_type VARCHAR(50) NOT NULL, 
	source_id VARCHAR(36), 
	file_name VARCHAR(255), 
	data_type VARCHAR(50), 
	processed_data JSON, 
	added_at TIMESTAMP WITH TIME ZONE, 
	meta_data JSON, 
	PRIMARY KEY (id)
);

CREATE TABLE IF NOT EXISTS session_messages (
	id UUID NOT NULL, 
	session_id UUID NOT NULL, 
	role VARCHAR(20) NOT NULL, 
	content TEXT NOT NULL, 
	analysis JSON, 
	risk_score NUMERIC, 
	domains JSON, 
	actions JSON, 
	timestamp TIMESTAMP WITH TIME ZONE, 
	context_used JSON, 
	meta_data JSON, 
	PRIMARY KEY (id)
);

CREATE TABLE IF NOT EXISTS yard_moves (
	id UUID NOT NULL, 
	organization_id UUID NOT NULL, 
	trailer_id UUID, 
	from_location VARCHAR(100) NOT NULL, 
	to_location VARCHAR(100) NOT NULL, 
	move_type VARCHAR(50), 
	jockey_driver_id UUID, 
	started_at TIMESTAMP WITH TIME ZONE, 
	completed_at TIMESTAMP WITH TIME ZONE, 
	duration_seconds NUMERIC, 
	meta_data JSON, 
	created_at TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (id), 
	FOREIGN KEY(organization_id) REFERENCES organizations (id)
);

CREATE TABLE IF NOT EXISTS driver_wait_times (
	id UUID NOT NULL, 
	organization_id UUID NOT NULL, 
	driver_id UUID, 
	trailer_id UUID, 
	check_in_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	docked_at TIMESTAMP WITH TIME ZONE, 
	unloaded_at TIMESTAMP WITH TIME ZONE, 
	check_out_at TIMESTAMP WITH TIME ZONE, 
	total_wait_minutes NUMERIC, 
	detention_minutes NUMERIC, 
	demurrage_minutes NUMERIC, 
	detention_rate NUMERIC, 
	demurrage_rate NUMERIC, 
	detention_charge NUMERIC, 
	demurrage_charge NUMERIC, 
	is_billed BOOLEAN, 
	meta_data JSON, 
	created_at TIMESTAMP WITH TIME ZONE, 
	updated_at TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (id), 
	FOREIGN KEY(organization_id) REFERENCES organizations (id)
);

CREATE TABLE IF NOT EXISTS dock_appointments (
	id UUID NOT NULL, 
	organization_id UUID NOT NULL, 
	dock_door_id UUID, 
	trailer_id UUID, 
	shipment_id UUID, 
	operation_id UUID, 
	appointment_type VARCHAR(50), 
	scheduled_start TIMESTAMP WITH TIME ZONE NOT NULL, 
	scheduled_end TIMESTAMP WITH TIME ZONE NOT NULL, 
	actual_start TIMESTAMP WITH TIME ZONE, 
	actual_end TIMESTAMP WITH TIME ZONE, 
	status VARCHAR(50), 
	carrier_id UUID, 
	driver_id UUID, 
	priority VARCHAR(20), 
	compliance_required BOOLEAN, 
	meta_data JSON, 
	created_at TIMESTAMP WITH TIME ZONE, 
	updated_at TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (id), 
	FOREIGN KEY(organization_id) REFERENCES organizations (id), 
	FOREIGN KEY(operation_id) REFERENCES operations (id)
);

CREATE TABLE IF NOT EXISTS geotab_trips (
	id UUID NOT NULL, 
	device_id VARCHAR(100) NOT NULL, 
	driver_id UUID, 
	vehicle_id VARCHAR(100), 
	organization_id UUID, 
	start_time TIMESTAMP WITH TIME ZONE NOT NULL, 
	end_time TIMESTAMP WITH TIME ZONE, 
	duration_seconds INTEGER, 
	start_location JSON, 
	end_location JSON, 
	distance_miles NUMERIC(10, 2), 
	start_odometer NUMERIC(10, 2), 
	end_odometer NUMERIC(10, 2), 
	idle_time_seconds INTEGER, 
	status VARCHAR(50), 
	meta_data JSON, 
	created_at TIMESTAMP WITH TIME ZONE, 
	updated_at TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (id), 
	FOREIGN KEY(organization_id) REFERENCES organizations (id)
);

CREATE INDEX IF NOT EXISTS ix_geotab_trips_device_start ON geotab_trips (device_id, start_time);

CREATE INDEX IF NOT EXISTS ix_geotab_trips_device_id ON geotab_trips (device_id);

CREATE TABLE IF NOT EXISTS geotab_exceptions (
	id UUID NOT NULL, 
	device_id VARCHAR(100) NOT NULL, 
	driver_id UUID, 
	organization_id UUID, 
	exception_type VARCHAR(50) NOT NULL, 
	severity VARCHAR(20), 
	timestamp TIMESTAMP WITH TIME ZONE NOT NULL, 
	location JSON, 
	details JSON, 
	acknowledged BOOLEAN, 
	acknowledged_by UUID, 
	acknowledged_at TIMESTAMP WITH TIME ZONE, 
	meta_data JSON, 
	created_at TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (id), 
	FOREIGN KEY(organization_id) REFERENCES organizations (id), 
	FOREIGN KEY(acknowledged_by) REFERENCES users (id)
);

CREATE INDEX IF NOT EXISTS ix_geotab_exceptions_timestamp ON geotab_exceptions (timestamp);

CREATE INDEX IF NOT EXISTS ix_geotab_exceptions_device_id ON geotab_exceptions (device_id);

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_yard_trailers_shipment_id') THEN
        ALTER TABLE yard_trailers ADD CONSTRAINT fk_yard_trailers_shipment_id
            FOREIGN KEY (shipment_id) REFERENCES shipments (id);
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_yard_trailers_dock_door_id') THEN
        ALTER TABLE yard_trailers ADD CONSTRAINT fk_yard_trailers_dock_door_id
            FOREIGN KEY (dock_door_id) REFERENCES dock_doors (id);
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_yard_trailers_carrier_id') THEN
        ALTER TABLE yard_trailers ADD CONSTRAINT fk_yard_trailers_carrier_id
            FOREIGN KEY (carrier_id) REFERENCES carriers (id);
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_yard_trailers_driver_id') THEN
        ALTER TABLE yard_trailers ADD CONSTRAINT fk_yard_trailers_driver_id
            FOREIGN KEY (driver_id) REFERENCES drivers (id);
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_dock_doors_current_trailer_id') THEN
        ALTER TABLE dock_doors ADD CONSTRAINT fk_dock_doors_current_trailer_id
            FOREIGN KEY (current_trailer_id) REFERENCES yard_trailers (id);
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_shipments_route_id') THEN
        ALTER TABLE shipments ADD CONSTRAINT fk_shipments_route_id
            FOREIGN KEY (route_id) REFERENCES routes (id);
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_shipments_driver_id') THEN
        ALTER TABLE shipments ADD CONSTRAINT fk_shipments_driver_id
            FOREIGN KEY (driver_id) REFERENCES drivers (id);
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_shipments_trailer_id') THEN
        ALTER TABLE shipments ADD CONSTRAINT fk_shipments_trailer_id
            FOREIGN KEY (trailer_id) REFERENCES yard_trailers (id);
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_shipments_carrier_id') THEN
        ALTER TABLE shipments ADD CONSTRAINT fk_shipments_carrier_id
            FOREIGN KEY (carrier_id) REFERENCES carriers (id);
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_yard_checkpoints_trailer_id') THEN
        ALTER TABLE yard_checkpoints ADD CONSTRAINT fk_yard_checkpoints_trailer_id
            FOREIGN KEY (trailer_id) REFERENCES yard_trailers (id);
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_drivers_carrier_id') THEN
        ALTER TABLE drivers ADD CONSTRAINT fk_drivers_carrier_id
            FOREIGN KEY (carrier_id) REFERENCES carriers (id);
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_load_plans_trailer_id') THEN
        ALTER TABLE load_plans ADD CONSTRAINT fk_load_plans_trailer_id
            FOREIGN KEY (trailer_id) REFERENCES yard_trailers (id);
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_load_plans_shipment_id') THEN
        ALTER TABLE load_plans ADD CONSTRAINT fk_load_plans_shipment_id
            FOREIGN KEY (shipment_id) REFERENCES shipments (id);
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_freight_charges_carrier_id') THEN
        ALTER TABLE freight_charges ADD CONSTRAINT fk_freight_charges_carrier_id
            FOREIGN KEY (carrier_id) REFERENCES carriers (id);
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_freight_charges_shipment_id') THEN
        ALTER TABLE freight_charges ADD CONSTRAINT fk_freight_charges_shipment_id
            FOREIGN KEY (shipment_id) REFERENCES shipments (id);
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_truck_asset_correlations_trailer_id') THEN
        ALTER TABLE truck_asset_correlations ADD CONSTRAINT fk_truck_asset_correlations_trailer_id
            FOREIGN KEY (trailer_id) REFERENCES yard_trailers (id);
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_truck_asset_correlations_shipment_id') THEN
        ALTER TABLE truck_asset_correlations ADD CONSTRAINT fk_truck_asset_correlations_shipment_id
            FOREIGN KEY (shipment_id) REFERENCES shipments (id);
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_load_quality_logs_trailer_id') THEN
        ALTER TABLE load_quality_logs ADD CONSTRAINT fk_load_quality_logs_trailer_id
            FOREIGN KEY (trailer_id) REFERENCES yard_trailers (id);
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_load_quality_logs_shipment_id') THEN
        ALTER TABLE load_quality_logs ADD CONSTRAINT fk_load_quality_logs_shipment_id
            FOREIGN KEY (shipment_id) REFERENCES shipments (id);
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_session_data_sources_session_id') THEN
        ALTER TABLE session_data_sources ADD CONSTRAINT fk_session_data_sources_session_id
            FOREIGN KEY (session_id) REFERENCES analysis_sessions (id);
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_session_messages_session_id') THEN
        ALTER TABLE session_messages ADD CONSTRAINT fk_session_messages_session_id
            FOREIGN KEY (session_id) REFERENCES analysis_sessions (id);
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_yard_moves_trailer_id') THEN
        ALTER TABLE yard_moves ADD CONSTRAINT fk_yard_moves_trailer_id
            FOREIGN KEY (trailer_id) REFERENCES yard_trailers (id);
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_yard_moves_jockey_driver_id') THEN
        ALTER TABLE yard_moves ADD CONSTRAINT fk_yard_moves_jockey_driver_id
            FOREIGN KEY (jockey_driver_id) REFERENCES drivers (id);
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_driver_wait_times_trailer_id') THEN
        ALTER TABLE driver_wait_times ADD CONSTRAINT fk_driver_wait_times_trailer_id
            FOREIGN KEY (trailer_id) REFERENCES yard_trailers (id);
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_driver_wait_times_driver_id') THEN
        ALTER TABLE driver_wait_times ADD CONSTRAINT fk_driver_wait_times_driver_id
            FOREIGN KEY (driver_id) REFERENCES drivers (id);
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_dock_appointments_driver_id') THEN
        ALTER TABLE dock_appointments ADD CONSTRAINT fk_dock_appointments_driver_id
            FOREIGN KEY (driver_id) REFERENCES drivers (id);
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_dock_appointments_trailer_id') THEN
        ALTER TABLE dock_appointments ADD CONSTRAINT fk_dock_appointments_trailer_id
            FOREIGN KEY (trailer_id) REFERENCES yard_trailers (id);
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_dock_appointments_carrier_id') THEN
        ALTER TABLE dock_appointments ADD CONSTRAINT fk_dock_appointments_carrier_id
            FOREIGN KEY (carrier_id) REFERENCES carriers (id);
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_dock_appointments_shipment_id') THEN
        ALTER TABLE dock_appointments ADD CONSTRAINT fk_dock_appointments_shipment_id
            FOREIGN KEY (shipment_id) REFERENCES shipments (id);
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_dock_appointments_dock_door_id') THEN
        ALTER TABLE dock_appointments ADD CONSTRAINT fk_dock_appointments_dock_door_id
            FOREIGN KEY (dock_door_id) REFERENCES dock_doors (id);
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_geotab_trips_driver_id') THEN
        ALTER TABLE geotab_trips ADD CONSTRAINT fk_geotab_trips_driver_id
            FOREIGN KEY (driver_id) REFERENCES drivers (id);
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_geotab_exceptions_driver_id') THEN
        ALTER TABLE geotab_exceptions ADD CONSTRAINT fk_geotab_exceptions_driver_id
            FOREIGN KEY (driver_id) REFERENCES drivers (id);
    END IF;
END $$;

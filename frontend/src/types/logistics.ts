// Yard Management System (YMS) Types

export interface YardTrailer {
  id: string;
  trailerId: string;
  licensePlate?: string;
  carrierId: string;
  carrierName: string;
  trailerType: 'dry_van' | 'reefer' | 'flatbed' | 'tanker' | 'container';
  status: 'in_transit' | 'yard' | 'docked' | 'loaded' | 'maintenance' | 'outbound';
  yardLocation?: string;
  assignedDoorId?: string;
  checkedInAt?: string;
  checkedOutAt?: string;
  expectedDuration?: number; // minutes
  detentionRisk: 'low' | 'medium' | 'high';
  detentionCost: number;
  /** `contents` and `poNumber` were HERE and are gone. `yard_trailers` records what the
   *  trailer IS — type, seal, weight, temperature setpoint — and nothing about what is inside
   *  it or which purchase order it belongs to. The inventory table printed `contents || '-'`
   *  in a column headed "Contents", so every row showed a dash under a heading promising
   *  something the schema has never held. */
  sealNumber?: string;
  /** `driverName` has no column either — `yard_trailers.driver_id` references `drivers`, and
   *  resolving a name there is the same join that now resolves the phone. Left declared
   *  because the panel renders it conditionally and the join is a one-line follow-up; the
   *  phone was the field an operator actually needs. */
  driverName?: string;
  /** Resolved through `yard_trailers.driver_id` -> `drivers.phone`. The number an operator
   *  calls about a trailer sitting on the yard, declared and rendered in two places and sent
   *  by nothing until now. */
  driverPhone?: string | null;
  /** `yard_trailers` has no position column; this is credited to the vocabulary by
   *  `vehicles.last_location`. Rule 34's blind spot, same as `Driver.lastLocation`. */
  createdAt: string;
  updatedAt: string;
}

export interface DockDoor {
  id: string;
  doorNumber: string;
  /** `dock_doors.door_type` — inbound | outbound | cross_dock. A real column that the API
   *  has always sent and this interface never declared. */
  doorType?: string | null;
  /** OPTIONAL, and unfed: `dock_doors` has no `workcell_id` column. Nothing reads it, so
   *  there is no render defect — but it was declared as REQUIRED, which is a promise the
   *  wire cannot keep. `workcellName` sat beside it and was rendered; it is deleted rather
   *  than resolved, because there is no workcell relationship here to resolve through. The
   *  card printed a blank line for an association this schema does not have.
   *
   *  NOTE: several fields below (`supportedEquipment`, `hasLoadingEquipment`,
   *  `maxWeightCapacity`, `currentAppointmentId`, `estimatedReleaseAt`) have the same
   *  problem — `dock_doors` carries only `equipment_capabilities` as JSON. They did not
   *  surface in the wire-vocabulary sweep because its vocabulary is GLOBAL: a name that
   *  exists as a column on any table passes, even when this entity has no such column.
   *  Recorded rather than fixed here; auditing one interface end to end is its own task. */
  workcellId?: string;
  status: 'available' | 'occupied' | 'reserved' | 'maintenance' | 'blocked';
  currentTrailerId?: string;
  trailerLicensePlate?: string;
  /** `dock_doors.equipment_capabilities` — a JSON OBJECT, not a list. This was declared as
   *  `supportedEquipment: string[]`, a name the wire does not use and a shape the column
   *  does not hold, so it was both unsourced and untypeable. Nothing rendered it. */
  equipmentCapabilities?: Record<string, unknown> | null;
  /** `dock_doors.last_occupied_at`. NOT an estimated release: it records when the door was
   *  last occupied, which is a fact about the past. `estimatedReleaseAt` was declared here
   *  and rendered as "Release: HH:MM" — a prediction nothing produces, so the line never
   *  appeared. Mapping `last_occupied_at` onto it would have been the `currentMileage`
   *  defect exactly: the right number under the wrong label. */
  lastOccupiedAt?: string | null;
  isActive?: boolean;
  createdAt: string;
  updatedAt: string;
}
// DELETED FROM DockDoor, all four unsourced and unrendered: `hasLoadingEquipment`,
// `maxWeightCapacity`, `currentAppointmentId` (appointments reference doors, not the
// reverse) and `estimatedReleaseAt`. `dock_doors` carries door_number, door_type, status,
// equipment_capabilities, current_trailer_id, last_occupied_at and is_active — nothing else.
// This is the per-interface audit rule 34 says the global sweep cannot do: its vocabulary
// credits a name that exists as a column on ANY table, so none of these were ever reported.

export interface DockAppointment {
  id: string;
  carrierId: string;
  carrierName: string;
  trailerId?: string;
  trailerLicensePlate?: string;
  doorId?: string;
  doorNumber?: string;
  workcellId: string;
  appointmentType: 'pickup' | 'delivery' | 'transfer';
  scheduledArrival: string;
  actualArrival?: string;
  scheduledDeparture: string;
  actualDeparture?: string;
  status: 'scheduled' | 'checked_in' | 'docked' | 'loading' | 'complete' | 'cancelled' | 'no_show';
  poNumber?: string;
  loadDescription?: string;
  priority: 'low' | 'normal' | 'high' | 'urgent';
  detentionStartAt?: string;
  driverName?: string;
  driverPhone?: string;
  notes?: string;
  createdAt: string;
  updatedAt: string;
}

export interface YardMove {
  id: string;
  trailerId: string;
  trailerLicensePlate: string;
  fromLocation: string;
  toLocation: string;
  moveType: 'check_in' | 'check_out' | 'dock' | 'undock' | 'reposition' | 'maintenance';
  performedBy: string;
  equipmentUsed?: string;
  startTime: string;
  endTime?: string;
  status: 'in_progress' | 'completed' | 'cancelled';
  notes?: string;
  createdAt: string;
}

export interface DriverWaitTime {
  id: string;
  driverId: string;
  driverName: string;
  carrierId: string;
  carrierName: string;
  trailerId?: string;
  appointmentId?: string;
  checkInTime: string;
  dockTime?: string;
  departureTime?: string;
  waitDurationMinutes?: number;
  dockDurationMinutes?: number;
  totalDurationMinutes?: number;
  isDetention: boolean;
  detentionCost?: number;
  reason?: string;
  createdAt: string;
}

// Transportation Management System (TMS) Types

export interface Carrier {
  id: string;
  name: string;
  scac?: string; // Standard Carrier Alpha Code
  mcNumber?: string; // Motor Carrier Number
  dotNumber?: string; // DOT number
  ctpatCertified: boolean;
  ctpatExpiry?: string;
  insuranceExpiry?: string;
  operatingAuthority: 'active' | 'inactive' | 'pending' | 'revoked';
  safetyRating?: 'satisfactory' | 'conditional' | 'unsatisfactory';
  /** DELETED: `contactEmail` and `contactPhone` were declared REQUIRED here and `carriers`
   *  has neither column. The table carries DOT/MC numbers, C-TPAT and insurance dates,
   *  safety rating, CSA score, SCAC and operating authority — and no way to reach anybody.
   *  The carrier card rendered a "Contact" heading above two empty lines for every row.
   *  Carrier contact details are collected nowhere in this product: a gap in the schema,
   *  not something the type can assert its way out of. */
  billingAddress?: Address;
  isActive: boolean;
  complianceScore: number;
  onTimePerformance: number; // percentage
  createdAt: string;
  updatedAt: string;
}

export interface Driver {
  id: string;
  carrierId: string;
  carrierName: string;
  firstName: string;
  lastName: string;
  licenseNumber: string;
  licenseExpiry: string;
  medicalCertExpiry?: string;
  cdlClass: 'A' | 'B' | 'C';
  endorsements: string[];
  hazmatCertified: boolean;
  currentHosStatus: 'off_duty' | 'sleeper' | 'driving' | 'on_duty';
  /** Null when unreported — `drivers.hos_cycle_hours` is nullable. */
  hosCycleHoursUsed: number | null;
  /** Null when the driver has reported no hours — the API derives this from
   *  `hos_drive_hours_today` and leaves it null when that is missing too. Treat null as
   *  UNASSESSABLE: `x === 0` is false for null, which cleared every fleet. */
  hosDriveHoursRemaining: number | null;
  /** Null when unreported — see `hosDriveHoursRemaining`. */
  hosDutyHoursRemaining: number | null;
  /** `drivers` HAS NO POSITION COLUMN, and the sweep did not report this one because the
   *  global vocabulary credits `lastLocation` from `vehicles.last_location`. Rule 34's blind
   *  spot; found by auditing this interface against its own table. A driver's position is
   *  their vehicle's, which the vehicle already carries, so this field is gone. */
  /** Reverse lookups, not columns: a vehicle names its driver (`vehicles.current_driver_id`)
   *  and a shipment names its driver (`shipments.driver_id`). Nothing produced either, so the
   *  "Current Vehicle" and "Current Shipment" rows never rendered; `/transportation/drivers`
   *  resolves both in one query each now. `currentShipmentId` is the driver's CURRENT load —
   *  shipments in a terminal status are excluded, or the row would name a delivered one. */
  currentVehicleId?: string;
  currentShipmentId?: string;
  /** WAS `geoTabDeviceId`. Drivers have no GeoTab device — the column is
   *  `drivers.eld_device_id`, an ELD, which is a different system. The detail panel showed
   *  a "GeoTab Device ID" row that could never populate while the id the driver DOES have
   *  was sent and never displayed. */
  eldDeviceId?: string;
  isActive: boolean;
  createdAt: string;
  updatedAt: string;
}

export interface Shipment {
  id: string;
  shipmentNumber: string;
  carrierId: string;
  carrierName: string;
  driverId?: string;
  driverName?: string;
  vehicleId?: string;
  trailerId?: string;
  status: 'planned' | 'dispatched' | 'picked_up' | 'in_transit' | 'delivered' | 'cancelled';
  origin: Location;
  destination: Location;
  scheduledPickup: string;
  actualPickup?: string;
  scheduledDelivery: string;
  /** `shipments` records `scheduled_delivery` and `actual_delivery`. There is no ETA: nothing
   *  in this product predicts a delivery time. The list coloured a row yellow when
   *  `estimatedDelivery > scheduledDelivery` — a late-running warning driven by a field no
   *  endpoint has ever sent, so it never fired, and the field is gone. Same shape as `DockDoor.estimatedReleaseAt`. */
  actualDelivery?: string;
  freightDescription?: string;
  weight?: number; // kg
  pieces?: number;
  palletCount?: number;
  hazmat: boolean;
  temperatureRequired?: number; // for reefers
  poNumber?: string;
  bolNumber?: string;
  proNumber?: string;
  freightCharge?: number;
  detentionRate?: number; // per hour
  detentionHours?: number;
  detentionTotal?: number;
  /** `shipments` carries no position. The nearest real thing is the assigned driver's
   *  vehicle's `last_location`, two hops away through `shipments.driver_id` ->
   *  `vehicles.current_driver_id` — and that silently becomes another load's position the
   *  moment a driver changes vehicle. Presenting it as the shipment's would be the
   *  `currentMileage` defect: the right number under the wrong label. The field is gone. */
  geoTabTripId?: string;
  routeId?: string;
  createdAt: string;
  updatedAt: string;
}

export interface Route {
  id: string;
  name: string;
  origin: Location;
  destination: Location;
  waypoints?: Location[];
  distance: number; // km
  estimatedDuration: number; // minutes
  averageSpeed?: number; // km/h
  fuelStops?: FuelStop[];
  restStops?: RestStop[];
  tollCosts?: number;
  fuelCosts?: number;
  createdAt: string;
  updatedAt: string;
}

export interface Vehicle {
  id: string;
  vehicleNumber: string;
  carrierId: string;
  carrierName: string;
  vin?: string;
  licensePlate: string;
  make?: string;
  model?: string;
  year?: number;
  vehicleType: 'tractor' | 'straight_truck' | 'van' | 'reefer' | 'flatbed' | 'tanker';
  fuelType: 'diesel' | 'gasoline' | 'electric' | 'hybrid' | 'lng' | 'cng';
  grossVehicleWeight?: number; // kg
  registrationExpiry?: string;
  inspectionDue?: string;
  dotNumber?: string;
  isActive: boolean;
  currentDriverId?: string;
  /** `vehicles` HAS NO SHIPMENT LINK — a shipment names its driver, and a vehicle names its
   *  driver, so a vehicle's load is really its driver's load. Removed rather than derived
   *  through two hops. */
  /** WAS `currentLocation`, which no endpoint has ever sent, so every location block on the
   *  vehicle panel was dead. The column is `vehicles.last_location` and the serializer emits
   *  it as `lastLocation` with exactly this shape. Rule 35: name the field after the wire. */
  lastLocation?: GeoLocation;
  /** `vehicles.geotab_device_id`. WAS `geoTabDeviceId` with a capital T — the casing seam
   *  produces `geotabDeviceId`, so the declared name matched nothing and the row never
   *  rendered. Rule 35: name the field after the wire. */
  geotabDeviceId?: string;
  odometer?: number;
  fuelLevel?: number;
  engineHours?: number;
  createdAt: string;
  updatedAt: string;
}

export interface FreightCharge {
  id: string;
  shipmentId: string;
  carrierId: string;
  chargeType: 'line_haul' | 'fuel_surcharge' | 'accessorial' | 'detention' | 'layover' | 'lumper' | 'redelivery' | 'tonu';
  description: string;
  quantity: number;
  rate: number;
  amount: number;
  currency: string;
  approved: boolean;
  approvedBy?: string;
  approvedAt?: string;
  invoiceNumber?: string;
  createdAt: string;
}

// GeoTab Integration Types

export interface GeoTabDevice {
  id: string;
  deviceType: string;
  serialNumber?: string;
  vehicleId?: string;
  driverId?: string;
  isActive: boolean;
  lastCommunication?: string;
  firmwareVersion?: string;
}

export interface GeoTabTrip {
  id: string;
  deviceId: string;
  driverId?: string;
  vehicleId?: string;
  startTime: string;
  endTime?: string;
  distance: number; // km
  duration: number; // minutes
  startLocation: GeoLocation;
  endLocation?: GeoLocation;
  maxSpeed?: number; // km/h
  averageSpeed?: number;
  idleTime: number; // minutes
  harshBrakingEvents: number;
  harshAccelerationEvents: number;
  speedingEvents: number;
}

export interface GeoTabDiagnostic {
  id: string;
  deviceId: string;
  diagnosticCode: string;
  name: string;
  source: string;
  value?: string;
  /** The device's `lastSeen`, which is a heartbeat's time standing in for a fault's — the
   *  closest thing the payload carries. NULL when the device has never reported; it used to
   *  fall back to `new Date()`, stamping every fault code with the current time. */
  timestamp: string | null;
  isActive: boolean;
}

export interface GeoTabException {
  id: string;
  deviceId: string;
  ruleName: string;
  ruleType: string;
  startTime: string;
  endTime?: string;
  duration: number; // minutes
  location?: GeoLocation;
  driverId?: string;
  acknowledged: boolean;
}

// Supporting Types

export interface GeoLocation {
  latitude: number;
  longitude: number;
  accuracy?: number;
  altitude?: number;
  heading?: number;
  speed?: number; // km/h
  timestamp: string;
  address?: string;
}

export interface Location {
  name: string;
  address: string;
  city: string;
  state: string;
  zipCode: string;
  country: string;
  latitude?: number;
  longitude?: number;
  contactName?: string;
  /** `Location` is a frontend-only shape (shipment origin/destination), not a table, and
   *  nothing renders these two — kept because a caller constructing a Location may set
   *  them. The CARRIER equivalents were deleted: `carriers` has no contact columns, and the
   *  card rendered a "Contact" heading above two empty lines for every row. */
  contactPhone?: string;
  contactEmail?: string;
  hours?: string;
}

export interface Address {
  street: string;
  city: string;
  state: string;
  zipCode: string;
  country: string;
}

export interface FuelStop {
  location: GeoLocation;
  address: string;
  estimatedTime: string;
  fuelPrice?: number;
}

export interface RestStop {
  location: GeoLocation;
  address: string;
  estimatedTime: string;
  duration: number;
  type: 'rest_break' | 'meal_break' | 'overnight';
}

// Dashboard Types

export interface LogisticsOverview {
  // Yard Stats
  trailersInYard: number;
  trailersDocked: number;
  dockDoorsAvailable: number;
  dockDoorsOccupied: number;
  todayAppointments: number;
  appointmentsOnTime: number;
  detentionRiskCount: number;
  detentionCostToday: number;
  
  // Fleet Stats
  vehiclesActive: number;
  vehiclesIdle: number;
  shipmentsInTransit: number;
  shipmentsDeliveredToday: number;
  onTimeDeliveryRate: number;
  averageTransitTime: number;
  
  // Compliance
  driversHosViolations: number;
  vehiclesInspectionDue: number;
  carrierComplianceIssues: number;
}

/** Live detention exposure, named after `/api/v1/yard/detention-alerts`.
 *
 *  EVERY FIELD ON THIS INTERFACE WAS WRONG, and the banner it feeds appears only when a
 *  trailer is at risk or already accruing charges — which is to say, only when it matters. It
 *  rendered the trailer id above a bare " • ", a "$" with no number, and "N/A excess".
 *
 *  The numbers were all being sent under different names (`detention_minutes`,
 *  `current_charge`, `elapsed_minutes`, `free_minutes`), so those are renames — rule 35. The
 *  identifying details genuinely were not sent, and are real columns on the row the endpoint
 *  already had in hand, so those are now served.
 *
 *  Only `excessMinutes` appeared in the wire-vocabulary sweep: `carrierName`, `location` and
 *  `estimatedCost` all exist on OTHER interfaces, so the global vocabulary credits them and the
 *  sweep sees nothing. Rule 34, and the reason this one needed reading against its own
 *  endpoint.
 *
 *  There is no `id`: the alert is computed, not stored. `trailerId` is the natural key and is
 *  what the list should be keyed on — it was keyed on `alert.id`, so every row shared
 *  `undefined`.
 */
export interface DetentionAlert {
  trailerId: string;
  /** `yard_trailers.trailer_number` — the human-readable identifier on the trailer. */
  trailerNumber: string;
  /** 'at_risk' before free time expires, 'detention' once charges are accruing. Replaces a
   *  four-value `severity` union nothing ever produced. */
  status: 'at_risk' | 'detention';
  licensePlate?: string | null;
  yardLocation?: string | null;
  carrierName?: string | null;
  checkInAt: string;
  elapsedMinutes: number;
  freeMinutes: number;
  /** Minutes past free time. Zero while 'at_risk'. */
  detentionMinutes: number;
  currentCharge: number;
  hourlyRate: number;
}

// `HOSViolationAlert` was declared here and referenced by NOTHING — one occurrence in the
// whole frontend, its own declaration. It described an alert no endpoint produces and no
// component renders: `hoursRemaining` and `currentLocation` had no source, and neither did
// `estimatedViolationTime` or the four-value `violationType` union. A type that nothing
// constructs is not a contract, it is a plan; the HOS surface that DOES exist reads
// `hosDriveHoursRemaining` off the driver, which the API derives and this file documents.

// Filter Types

export interface TrailerFilters {
  status?: YardTrailer['status'];
  carrierId?: string;
  trailerType?: YardTrailer['trailerType'];
  detentionRisk?: YardTrailer['detentionRisk'];
  yardLocation?: string;
}

export interface ShipmentFilters {
  status?: Shipment['status'];
  carrierId?: string;
  driverId?: string;
  dateFrom?: string;
  dateTo?: string;
  origin?: string;
  destination?: string;
}

export interface AppointmentFilters {
  status?: DockAppointment['status'];
  workcellId?: string;
  carrierId?: string;
  dateFrom?: string;
  dateTo?: string;
  priority?: DockAppointment['priority'];
}

// Fleet Tracker Types

export interface FleetVehiclePosition {
  deviceId: string;
  vehicleId: string;
  driverId?: string;
  driverName?: string;
  position: GeoLocation;
  status: 'moving' | 'idle' | 'stopped' | 'offline';
  speed: number;
  heading: number;
  lastUpdate: string;
}

export interface ShipmentRoute {
  shipmentId: string;
  shipmentNumber: string;
  origin: GeoLocation;
  destination: GeoLocation;
  waypoints: GeoLocation[];
  status: Shipment['status'];
  vehicleId?: string;
  driverName?: string;
  color: string;
}

export interface GeofenceZone {
  id: string;
  name: string;
  type: 'circle' | 'polygon';
  center?: GeoLocation;
  radius?: number; // in meters
  coordinates?: GeoLocation[]; // for polygon
  color: 'green' | 'yellow' | 'red';
  description?: string;
}

export interface FleetUpdate {
  type: 'vehicle_position' | 'status_change' | 'geofence_alert' | 'shipment_update';
  timestamp: string;
  data: FleetVehiclePosition | GeofenceAlert | ShipmentRoute;
}

export interface GeofenceAlert {
  id: string;
  vehicleId: string;
  /** Denormalised from the vehicle; null when the referenced vehicle is not resolvable. */
  vehicleNumber?: string | null;
  geofenceId: string;
  /** Denormalised from the zone. NULL means the server could not resolve the zone — which
   *  is not the same as a zone with no name, and the panel says so. */
  geofenceName?: string | null;
  /** `geofence_alerts.event_type`. The API used to send this as `eventType`, so it arrived
   *  undefined and the panel's ternary fell through to "Violation" for every alert. */
  alertType: 'entry' | 'exit' | 'violation';
  severity?: string;
  acknowledged?: boolean;
  location: GeoLocation;
  timestamp: string;
}

export type MapFilterType = 'all' | 'shipments' | 'fleet' | 'carriers' | 'compliance';

// ============================================
// Fleet Tracker Enhancement Types
// ============================================

// Geofencing Types
/** THE NULLABLE FIELDS ARE NULLABLE ON PURPOSE. `_alert_out` resolves the zone and vehicle
 *  names by join and sends `null` when it cannot, with a comment saying why: *"the panel must
 *  be able to tell a zone it could not resolve from one with an empty name."* `adaptAlert` then
 *  replaced that `null` with the zone ID, and failing that with `''` — and `'' ?? fallback` is
 *  `''`, so the panel's `geofenceName ?? 'Zone name unavailable'` could never fire and the row
 *  rendered a blank line. A deliberate distinction, made on the server and handled in the
 *  panel, destroyed by the layer between them. */
export interface GeofenceAlertExtended {
  id: string;
  vehicleId?: string | null;
  vehicleNumber?: string | null;
  driverName?: string;
  geofenceId?: string | null;
  geofenceName?: string | null;
  /** NOT defaulted to 'violation'. That default is the original defect wearing a fallback:
   *  every alert, including a routine authorised entry, read "Violation". The panel already
   *  refuses to guess an unrecognised value — it needs to see the absence to do so. */
  alertType?: string | null;
  location?: GeoLocation | null;
  timestamp?: string | null;
  acknowledged: boolean;
  /** An alert whose severity did not arrive is not an informational one. */
  severity?: 'info' | 'warning' | 'critical' | null;
}

export interface GeofenceZoneExtended extends GeofenceZone {
  /** OPTIONAL, and it was `string[]` defaulted to `[]`. `_zone_out` does not send it and
   *  nothing computes it, so the panel's "{n} vehicles inside" read "0 vehicles inside" for
   *  every zone — a count, not a blank. Present only when a producer supplies one. */
  vehiclesInside?: string[];
  /** Derived from `triggerOn`, which the server does send. A real derivation, not a default. */
  alertRules: {
    onEntry: boolean;
    onExit: boolean;
    notifyRoles: string[];
  };
  isActive: boolean;
  /** `_zone_out` sends neither. They were defaulted to `''`, and `new Date('')` is an
   *  Invalid Date — which renders as the literal string "Invalid Date". */
  createdAt?: string;
  updatedAt?: string;
}

// Fleet Health & Security Types
export interface DiagnosticTroubleCode {
  code: string;
  description: string;
  severity: 'low' | 'medium' | 'high' | 'critical';
  system: 'engine' | 'transmission' | 'emissions' | 'safety' | 'other';
  timestamp: string;
  cleared: boolean;
  vehicleId: string;
  vehicleNumber: string;
}

export interface VehicleHealthStatus {
  vehicleId: string;
  vehicleNumber: string;
  driverId?: string;
  driverName?: string;
  status: 'online' | 'offline' | 'maintenance' | 'warning';
  lastCommunication: string;
  dtcs: DiagnosticTroubleCode[];
  safetyScore: number;
  securityStatus: 'secure' | 'warning' | 'alert';
  engineHours: number;
  odometer: number;
  fuelLevel?: number;
}

export interface SecurityEvent {
  id: string;
  vehicleId: string;
  vehicleNumber: string;
  eventType: 'unauthorized_access' | 'unusual_route' | 'after_hours_use' | 'geofence_violation' | 'device_tampering';
  timestamp: string;
  severity: 'low' | 'medium' | 'high' | 'critical';
  location?: GeoLocation;
  description: string;
  acknowledged: boolean;
  driverName?: string;
}

export interface DriverSafetyMetrics {
  driverId: string;
  driverName: string;
  overallScore: number;
  harshBrakingEvents: number;
  harshAccelerationEvents: number;
  speedingEvents: number;
  idleTimeHours: number;
  seatbeltViolations: number;
  period: string;
  trend: 'improving' | 'stable' | 'declining';
}

// Maintenance Types
export interface MaintenanceSchedule {
  id: string;
  vehicleId: string;
  vehicleNumber: string;
  serviceType: 'oil_change' | 'tire_rotation' | 'brake_inspection' | 'engine_tuneup' | 'transmission_service' | 'annual_inspection' | 'other';
  description: string;
  scheduledDate: string;
  /** Odometer reading at which this service falls due (`due_odometer_miles`). */
  dueMileage?: number;
  status: 'scheduled' | 'overdue' | 'completed' | 'cancelled';
  priority: 'low' | 'normal' | 'high' | 'urgent';
  estimatedCost?: number;
  /** `assignedTechnician` was HERE. `maintenance_schedules` has no technician column and,
   *  unlike `repair_orders`, no vendor either — a schedule records WHAT is due and WHEN,
   *  not who will do it. The card offered a "Tech:" line that could never populate; the
   *  same field on `RepairOrder` at least had `vendor` standing beside it. */
  notes?: string;
}

/** A repair order, named after the wire.
 *
 *  THIS INTERFACE USED TO DECLARE SEVEN FIELDS `_order_out` HAS NEVER SENT — the largest
 *  cluster left in the declared-but-unsent baseline. `repair_orders` has thirteen columns and
 *  the serializer emits eleven of them; the type described a different, richer object that no
 *  endpoint produces and no migration plans:
 *
 *    * `workOrderNumber` — no such number is issued anywhere in this product. It had been
 *      synthesised from eight characters of the row's UUID and printed as the heading a
 *      technician would quote to a vendor; that was already removed, leaving a field nothing
 *      could fill.
 *    * `assignedTechnician` — no column, and the sharpest of the seven, because
 *      `repair_orders.vendor` — who actually did the work — WAS being sent and rendered
 *      nowhere. The card offered a "Tech:" line that could never populate while the name it
 *      could have shown arrived on every response. Same shape as the `geoTabDeviceId` finding.
 *    * `actualCost` — a second cost on a table with one `cost` column, which is the actual
 *      cost. Two names for one number invites someone to populate both.
 *    * `laborHours`, `partsUsed` (with its `PartUsed` shape) — no columns, no tables, and no
 *      pending work that would add them.
 *    * `issueDescription`, `reportedDate` — real data under invented names. The adapter filled
 *      them from `title` and `openedAt`, which is rule 35's case: name the field after the
 *      wire, not after the nicer word. Renamed rather than deleted.
 *
 *  What the server sends and the type now says: `title`, `description`, `vendor`, `category`,
 *  `cost`, `status`, `priority`, `openedAt`, `completedAt`. `vehicleNumber` is the one
 *  legitimately client-side value, derived by the adapter.
 */
export interface RepairOrder {
  id: string;
  vehicleId: string;
  /** Derived client-side by `adaptRepairOrder`; falls back to the id when absent. */
  vehicleNumber: string;
  /** The summary. Headed the card as of this change — previously the heading was a
   *  work-order number that no system issues. */
  title: string;
  /** The detail a technician typed. `_history_out` on the same table always read it while
   *  `_order_out` did not send it, so one repair carried its description in the
   *  completed-work view and lost it in the active list. */
  description?: string | null;
  status: 'reported' | 'diagnosing' | 'in_progress' | 'waiting_parts' | 'completed' | 'cancelled';
  /** MISMATCHED WITH THE SERVER, deliberately left as-is for now: `repair_orders.priority`
   *  is `low | medium | high | critical`, so 'medium' and 'critical' arrive here as values
   *  this union does not contain and `getPriorityColor` falls through to its default.
   *  Reconciling the two vocabularies is a product decision (which set of words does the
   *  operator use?), not a mechanical fix — recorded in defect-class-sweeps.md. */
  priority: 'low' | 'normal' | 'high' | 'urgent';
  /** The shop or supplier that did the work. Sent on every response since the endpoint was
   *  written and displayed nowhere, under a card that asked for a technician instead. */
  vendor?: string | null;
  /** `repair_orders.category` — likewise sent and never shown. */
  category?: string | null;
  /** What the repair cost. NOT an estimate — the panel labelled it "estimated" and coerced a
   *  missing value to 0, so a repair with no cost recorded displayed as a free one. */
  cost?: number;
  openedAt?: string | null;
  completedAt?: string | null;
}

export interface ServiceHistoryEntry {
  id: string;
  vehicleId: string;
  vehicleNumber: string;
  serviceType: string;
  description: string;
  serviceDate: string;
  mileageAtService: number;
  cost: number;
  technician?: string;
  notes?: string;
  partsReplaced?: string[];
}

export interface MaintenanceCosts {
  /** Undefined if the endpoint sent nothing at all. Was named `totalYTD` — real data
   *  under a name no endpoint uses, renamed to what the wire calls it. */
  ytdTotal?: number;
  /** OPTIONAL BECAUSE A DEPLOYMENT MAY BE OLDER THAN THIS CLIENT. `/maintenance/costs`
   *  used to send only `ytdTotal` and `byCategory`, and these three were manufactured
   *  client-side — two hardcoded to 0, one as `ytd / 12` regardless of the month — and
   *  rendered as figures. The server computes all three now (repair costs by month,
   *  `maintenance_schedules.estimated_cost`, and the vehicle count); they stay optional so
   *  a client talking to an older backend omits the row rather than inventing a zero.
   *
   *  `costPerVehicle` and `upcomingEstimated` are also legitimately absent against a
   *  CURRENT backend: an empty fleet has no cost per vehicle, and outstanding work that
   *  nobody has costed has no estimate. Neither is zero. */
  monthlyAverage?: number;
  costPerVehicle?: number;
  upcomingEstimated?: number;
  byCategory: Record<string, number>;
  /** `YYYY-MM` per entry, one for every elapsed month of the current year — including the
   *  months that cost nothing, which is a number and not a gap. */
  monthlyBreakdown: { month: string; cost: number }[];
}

// Performance & KPI Types
export interface KPIWidgetConfig {
  id: string;
  type: 'fuel_efficiency' | 'idle_time' | 'on_time_performance' | 'vehicle_health' | 'cost_per_mile' | 'dtc_count';
  title: string;
  position: number;
  size: 'small' | 'medium' | 'large';
  timeRange: 'today' | 'week' | 'month' | 'quarter' | 'year';
  filters?: {
    vehicleIds?: string[];
    carrierId?: string;
    driverIds?: string[];
  };
}

export interface FuelEfficiencyData {
  fleetAverage: number;
  unit: 'mpg' | 'l_per_100km';
  bestPerformers: { vehicleId: string; vehicleNumber: string; efficiency: number }[];
  worstPerformers: { vehicleId: string; vehicleNumber: string; efficiency: number }[];
  trend: { date: string; value: number }[];
  byVehicle: Record<string, number>;
  totalFuelConsumed: number;
  totalDistance: number;
}

export interface IdleTimeData {
  totalHours: number;
  percentageOfRuntime: number;
  costImpact: number;
  byVehicle: Record<string, { hours: number; percentage: number; cost: number }>;
  trend: { date: string; hours: number; cost: number }[];
}

export interface OnTimePerformanceData {
  overallPercentage: number;
  onTimeCount: number;
  lateCount: number;
  byCarrier: Record<string, number>;
  byRoute: Record<string, number>;
  trend: { date: string; percentage: number; onTime: number; total: number }[];
}

export interface VehicleHealthScoreData {
  fleetAverage: number;
  byVehicle: Record<string, number>;
  criticalCount: number;
  warningCount: number;
  healthyCount: number;
  factors: {
    dtcs: number;
    maintenance: number;
    safety: number;
    connectivity: number;
  };
}

export interface CostPerMileData {
  totalCost: number;
  totalMiles: number;
  averageCostPerMile: number;
  breakdown: {
    fuel: number;
    maintenance: number;
    insurance: number;
    other: number;
  };
  byVehicle: Record<string, number>;
  trend: { date: string; cost: number; miles: number }[];
}

export interface DTCCountData {
  totalActive: number;
  criticalCount: number;
  byVehicle: Record<string, number>;
  bySystem: Record<string, number>;
  recent: DiagnosticTroubleCode[];
  trend: { date: string; count: number; cleared: number }[];
}

export type TimeRange = 'today' | 'week' | 'month' | 'quarter' | 'year' | 'custom';

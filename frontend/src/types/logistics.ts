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
  contents?: string;
  poNumber?: string;
  sealNumber?: string;
  driverName?: string;
  driverPhone?: string;
  lastLocation?: GeoLocation;
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
  lastLocation?: GeoLocation;
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
  estimatedDelivery?: string;
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
  currentLocation?: GeoLocation;
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
  currentShipmentId?: string;
  currentLocation?: GeoLocation;
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
  timestamp: string;
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

export interface DetentionAlert {
  id: string;
  trailerId: string;
  trailerLicensePlate?: string;
  driverName?: string;
  carrierName: string;
  location: string;
  checkInTime: string;
  currentDurationMinutes: number;
  freeTimeMinutes: number;
  excessMinutes: number;
  estimatedCost: number;
  severity: 'low' | 'medium' | 'high' | 'critical';
}

export interface HOSViolationAlert {
  id: string;
  driverId: string;
  driverName: string;
  carrierName: string;
  violationType: 'driving_limit' | 'duty_limit' | 'rest_break' | 'cycle_limit';
  hoursRemaining: number;
  estimatedViolationTime?: string;
  currentLocation?: GeoLocation;
  severity: 'warning' | 'violation';
}

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
export interface GeofenceAlertExtended {
  id: string;
  vehicleId: string;
  vehicleNumber: string;
  driverName?: string;
  geofenceId: string;
  geofenceName: string;
  alertType: 'entry' | 'exit' | 'violation';
  location: GeoLocation;
  timestamp: string;
  acknowledged: boolean;
  severity: 'info' | 'warning' | 'critical';
}

export interface GeofenceZoneExtended extends GeofenceZone {
  vehiclesInside: string[];
  alertRules: {
    onEntry: boolean;
    onExit: boolean;
    notifyRoles: string[];
  };
  isActive: boolean;
  createdAt: string;
  updatedAt: string;
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
  assignedTechnician?: string;
  notes?: string;
}

export interface PartUsed {
  partNumber: string;
  description: string;
  quantity: number;
  unitCost: number;
}

export interface RepairOrder {
  id: string;
  vehicleId: string;
  vehicleNumber: string;
  /** No work-order number exists in `repair_orders`. It was synthesised from the first
   *  eight characters of the row's UUID and displayed as the heading of every row. */
  workOrderNumber?: string;
  issueDescription: string;
  /** `repair_orders.description` — the detail, as opposed to `title`, which is the summary
   *  `issueDescription` is derived from. The serializer omitted it entirely until now. */
  description?: string | null;
  reportedDate: string;
  startedDate?: string;
  completedDate?: string;
  status: 'reported' | 'diagnosing' | 'in_progress' | 'waiting_parts' | 'completed' | 'cancelled';
  /** MISMATCHED WITH THE SERVER, deliberately left as-is for now: `repair_orders.priority`
   *  is `low | medium | high | critical`, so 'medium' and 'critical' arrive here as values
   *  this union does not contain and `getPriorityColor` falls through to its default.
   *  Reconciling the two vocabularies is a product decision (which set of words does the
   *  operator use?), not a mechanical fix — recorded in defect-class-sweeps.md. */
  priority: 'low' | 'normal' | 'high' | 'urgent';
  assignedTechnician?: string;
  /** What the repair cost (`repair_orders.cost`). NOT an estimate — the panel labelled it
   *  "estimated" and coerced a missing value to 0, so a repair with no cost recorded
   *  displayed as a free one. */
  cost?: number;
  actualCost?: number;
  partsUsed: PartUsed[];
  laborHours?: number;
  relatedDTCs?: string[];
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
  /** `/maintenance/costs` sends `ytdTotal`. Undefined if it sent nothing at all. */
  totalYTD?: number;
  /** OPTIONAL BECAUSE NOTHING COMPUTES THEM. The server sends only `ytdTotal` and
   *  `byCategory`; these three were manufactured client-side (two hardcoded to 0, one as
   *  `ytd / 12` regardless of the month) and rendered as figures. */
  monthlyAverage?: number;
  costPerVehicle?: number;
  upcomingEstimated?: number;
  byCategory: Record<string, number>;
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

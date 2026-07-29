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
  workcellId: string;
  workcellName: string;
  status: 'available' | 'occupied' | 'reserved' | 'maintenance' | 'blocked';
  currentTrailerId?: string;
  trailerLicensePlate?: string;
  supportedEquipment: string[];
  hasLoadingEquipment: boolean;
  maxWeightCapacity: number; // kg
  currentAppointmentId?: string;
  estimatedReleaseAt?: string;
  createdAt: string;
  updatedAt: string;
}

export interface DockAppointment {
  id: string;
  carrierId: string;
  carrierName: string;
  trailerId?: string;
  trailerLicensePlate?: string;
  doorId?: string;
  doorNumber?: string;
  workcellId: string;
  workcellName: string;
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
  contactEmail: string;
  contactPhone: string;
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
  geoTabDeviceId?: string; // GeoTab device ID
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
  geoTabDeviceId?: string;
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
  geofenceId: string;
  geofenceName: string;
  alertType: 'entry' | 'exit' | 'violation';
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

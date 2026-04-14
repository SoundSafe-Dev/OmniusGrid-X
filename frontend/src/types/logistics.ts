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
  hosCycleHoursUsed: number;
  hosDriveHoursRemaining: number;
  hosDutyHoursRemaining: number;
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

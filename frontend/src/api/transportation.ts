import { api } from './client';
import { toListResult } from './listResult';
import { TRANSPORT_ALIASES, TRANSPORT_OUT_ALIASES } from './transform';
import { registerTransform } from './transformRegistry';
import {
  Carrier, 
  Driver, 
  Shipment, 
  Route,
  Vehicle,
  ShipmentFilters,
  PaginatedResponse,
  GeoLocation,
  GeoTabDevice,
  GeoTabTrip,
  GeoTabDiagnostic,
  GeoTabException
} from '../types';

import { USE_MOCK } from './mockMode';

// FS-61: casing handled by the axios seam — no per-call toCamel/toSnake.
// (/api/v1/logistics is deliberately NOT registered: legacy-camel backend.)
registerTransform('/api/v1/transportation', { inAliases: TRANSPORT_ALIASES, outAliases: TRANSPORT_OUT_ALIASES });
registerTransform('/api/v1/geotab');

/** `DriverHOSOut` in `app/api/transportation.py`, after the casing seam (FS-395).
 *
 *  THE THREE LISTS ARE SEPARATE ON PURPOSE and the backend says why: "`missing_data` is not
 *  `violations`. A driver with no medical certificate on file has not broken a rule; nobody
 *  knows whether they have." `isCompliant` requires BOTH lists empty; `assessable` reports
 *  the second alone, so a consumer can render "unknown" instead of "clear".
 *
 *  Every hour is nullable, and the distinction is the whole point: NULL means the driver has
 *  not reported, 0 means out of hours. Collapsing them is the defect this codebase has found
 *  on HOS three separate times. */
export interface DriverHOS {
  driverId: string;
  isCompliant: boolean;
  assessable: boolean;
  missingData: string[];
  violations: string[];
  warnings: string[];
  hoursSummary: {
    driveHoursToday: number | null;
    onDutyHoursToday: number | null;
    cycleHours: number | null;
    driveHoursRemaining: number | null;
    onDutyHoursRemaining: number | null;
    cycleHoursRemaining: number | null;
  };
}

/** `ShipmentCostsOut` in `app/api/transportation.py`, after the casing seam (FS-397).
 *
 *  The money lives on NESTED charge objects, not on scalars: `linehaul.amount` and
 *  `fuelSurcharge.amount`. The client used to declare five flat numbers, none of which the
 *  endpoint sends. */
export interface ShipmentCosts {
  shipmentId: string;
  /** `amount` is NULL when the charge could not be estimated (FS-665).
   *
   *  A shipment with no route has no distance, and the per-mile charge is `distance * rate`.
   *  The server used to substitute 500 miles and bill against it — $1,250 of linehaul for a
   *  shipment that had no route at all, reported with `distanceMiles: 500` as fact. It now
   *  answers `null` with `rateBasis: 'not_estimated'`, so the page must render the absence
   *  rather than call `.toFixed()` on it. */
  linehaul: {
    amount: number | null;
    rateBasis: string;
    mileageCharge: number | null;
    weightCharge: number | null;
  };
  /** NOT ALWAYS A MEASUREMENT — `FuelSurchargeCharge` records that without a contract
   *  surcharge table the engine falls back to a computed estimate, so `rateBasis` is
   *  carried rather than flattened away. Null on the same terms as the linehaul. */
  fuelSurcharge: {
    amount: number | null;
    rateBasis: string;
  };
  /** Null when either component could not be estimated. */
  totalCost: number | null;
  distanceMiles: number | null;
  weightLbs: number | null;
}

const MOCK_DELAY = 500;

const delay = (ms: number) => new Promise(resolve => setTimeout(resolve, ms));

// Mock Data
const mockCarriers: Carrier[] = [
  {
    id: 'carrier-1',
    name: 'Swift Transportation',
    scac: 'SWFT',
    mcNumber: 'MC-123456',
    dotNumber: 'DOT-987654',
    ctpatCertified: true,
    ctpatExpiry: new Date(Date.now() + 180 * 86400000).toISOString(),
    insuranceExpiry: new Date(Date.now() + 90 * 86400000).toISOString(),
    operatingAuthority: 'active',
    safetyRating: 'satisfactory',
    isActive: true,
    complianceScore: 98,
    onTimePerformance: 94,
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
  },
  {
    id: 'carrier-2',
    name: 'Schneider National',
    scac: 'SNDR',
    mcNumber: 'MC-234567',
    dotNumber: 'DOT-876543',
    ctpatCertified: true,
    ctpatExpiry: new Date(Date.now() + 200 * 86400000).toISOString(),
    insuranceExpiry: new Date(Date.now() + 120 * 86400000).toISOString(),
    operatingAuthority: 'active',
    safetyRating: 'satisfactory',
    isActive: true,
    complianceScore: 96,
    onTimePerformance: 92,
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
  },
  {
    id: 'carrier-3',
    name: 'JB Hunt',
    scac: 'JBHT',
    mcNumber: 'MC-345678',
    dotNumber: 'DOT-765432',
    ctpatCertified: false,
    insuranceExpiry: new Date(Date.now() + 60 * 86400000).toISOString(),
    operatingAuthority: 'active',
    safetyRating: 'conditional',
    isActive: true,
    complianceScore: 85,
    onTimePerformance: 88,
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
  },
];

const mockDrivers: Driver[] = [
  {
    id: 'driver-1',
    carrierId: 'carrier-1',
    carrierName: 'Swift Transportation',
    firstName: 'John',
    lastName: 'Smith',
    licenseNumber: 'DL123456789',
    licenseExpiry: new Date(Date.now() + 365 * 86400000).toISOString(),
    medicalCertExpiry: new Date(Date.now() + 180 * 86400000).toISOString(),
    cdlClass: 'A',
    endorsements: ['T', 'H', 'N'],
    hazmatCertified: true,
    currentHosStatus: 'on_duty',
    hosCycleHoursUsed: 45,
    hosDriveHoursRemaining: 6,
    hosDutyHoursRemaining: 9,
    currentVehicleId: 'vehicle-1',
    eldDeviceId: 'eld-device-001',
    isActive: true,
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
  },
  {
    id: 'driver-2',
    carrierId: 'carrier-2',
    carrierName: 'Schneider National',
    firstName: 'Maria',
    lastName: 'Garcia',
    licenseNumber: 'DL987654321',
    licenseExpiry: new Date(Date.now() + 200 * 86400000).toISOString(),
    medicalCertExpiry: new Date(Date.now() + 90 * 86400000).toISOString(),
    cdlClass: 'A',
    endorsements: ['T'],
    hazmatCertified: false,
    currentHosStatus: 'driving',
    hosCycleHoursUsed: 52,
    hosDriveHoursRemaining: 3,
    hosDutyHoursRemaining: 5,
    currentVehicleId: 'vehicle-2',
    eldDeviceId: 'eld-device-002',
    isActive: true,
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
  },
  {
    id: 'driver-3',
    carrierId: 'carrier-3',
    carrierName: 'JB Hunt',
    firstName: 'Robert',
    lastName: 'Johnson',
    licenseNumber: 'DL456789123',
    licenseExpiry: new Date(Date.now() + 150 * 86400000).toISOString(),
    cdlClass: 'A',
    endorsements: [],
    hazmatCertified: false,
    currentHosStatus: 'off_duty',
    hosCycleHoursUsed: 60,
    hosDriveHoursRemaining: 0,
    hosDutyHoursRemaining: 0,
    eldDeviceId: 'eld-device-003',
    isActive: true,
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
  },
];

const mockVehicles: Vehicle[] = [
  {
    id: 'vehicle-1',
    vehicleNumber: 'TRK-001',
    carrierId: 'carrier-1',
    carrierName: 'Swift Transportation',
    vin: '1HGBH41JXMN109186',
    licensePlate: 'TRK-1001',
    make: 'Freightliner',
    model: 'Cascadia',
    year: 2023,
    vehicleType: 'tractor',
    fuelType: 'diesel',
    grossVehicleWeight: 80000,
    registrationExpiry: new Date(Date.now() + 200 * 86400000).toISOString(),
    inspectionDue: new Date(Date.now() + 30 * 86400000).toISOString(),
    isActive: true,
    currentDriverId: 'driver-1',
    geotabDeviceId: 'gt-device-001',
    odometer: 125000,
    fuelLevel: 75,
    engineHours: 4500,
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
  },
  {
    id: 'vehicle-2',
    vehicleNumber: 'TRK-002',
    carrierId: 'carrier-2',
    carrierName: 'Schneider National',
    vin: '3AKJHHDR6KSJ12345',
    licensePlate: 'TRK-2002',
    make: 'Peterbilt',
    model: '579',
    year: 2022,
    vehicleType: 'tractor',
    fuelType: 'diesel',
    grossVehicleWeight: 80000,
    registrationExpiry: new Date(Date.now() + 150 * 86400000).toISOString(),
    inspectionDue: new Date(Date.now() + 15 * 86400000).toISOString(),
    isActive: true,
    currentDriverId: 'driver-2',
    geotabDeviceId: 'gt-device-002',
    lastLocation: {
      latitude: 39.7392,
      longitude: -104.9903,
      speed: 65,
      timestamp: new Date().toISOString(),
    },
    odometer: 89000,
    fuelLevel: 45,
    engineHours: 3200,
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
  },
  {
    id: 'vehicle-3',
    vehicleNumber: 'TRK-003',
    carrierId: 'carrier-3',
    carrierName: 'JB Hunt',
    vin: '4V4NC9EH7AN123456',
    licensePlate: 'TRK-3003',
    make: 'Kenworth',
    model: 'T680',
    year: 2021,
    vehicleType: 'straight_truck',
    fuelType: 'diesel',
    grossVehicleWeight: 33000,
    registrationExpiry: new Date(Date.now() + 100 * 86400000).toISOString(),
    inspectionDue: new Date(Date.now() + 5 * 86400000).toISOString(),
    isActive: true,
    geotabDeviceId: 'gt-device-003',
    odometer: 145000,
    fuelLevel: 90,
    engineHours: 5800,
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
  },
];

const mockShipments: Shipment[] = [
  {
    id: 'shipment-1',
    shipmentNumber: 'SHP-2024-0001',
    carrierId: 'carrier-1',
    carrierName: 'Swift Transportation',
    driverId: 'driver-1',
    driverName: 'John Smith',
    trailerId: 'trailer-1',
    status: 'in_transit',
    origin: {
      name: 'Main Distribution Center',
      address: '1000 Warehouse Blvd',
      city: 'Chicago',
      state: 'IL',
      zipCode: '60601',
      country: 'USA',
    },
    destination: {
      name: 'West Coast Hub',
      address: '2500 Port Terminal Dr',
      city: 'Los Angeles',
      state: 'CA',
      zipCode: '90021',
      country: 'USA',
    },
    scheduledPickup: new Date(Date.now() - 24 * 3600000).toISOString(),
    actualPickup: new Date(Date.now() - 24 * 3600000).toISOString(),
    scheduledDelivery: new Date(Date.now() + 12 * 3600000).toISOString(),
    weight: 25000,
    pieces: 500,
    palletCount: 20,
    hazmat: false,
    poNumber: 'PO-78234',
    bolNumber: 'BOL-2024-001',
    proNumber: 'PRO-987654',
    freightCharge: 2850.00,
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
  },
  {
    id: 'shipment-2',
    shipmentNumber: 'SHP-2024-0002',
    carrierId: 'carrier-2',
    carrierName: 'Schneider National',
    driverId: 'driver-2',
    driverName: 'Maria Garcia',
    trailerId: 'trailer-2',
    status: 'in_transit',
    origin: {
      name: 'Denver Fulfillment Center',
      address: '500 Logistics Way',
      city: 'Denver',
      state: 'CO',
      zipCode: '80202',
      country: 'USA',
    },
    destination: {
      name: 'Texas Distribution Hub',
      address: '3000 Commerce St',
      city: 'Dallas',
      state: 'TX',
      zipCode: '75207',
      country: 'USA',
    },
    scheduledPickup: new Date(Date.now() - 12 * 3600000).toISOString(),
    actualPickup: new Date(Date.now() - 12 * 3600000).toISOString(),
    scheduledDelivery: new Date(Date.now() + 6 * 3600000).toISOString(),
    weight: 35000,
    pieces: 800,
    palletCount: 32,
    hazmat: false,
    temperatureRequired: -18,
    poNumber: 'PO-78235',
    bolNumber: 'BOL-2024-002',
    proNumber: 'PRO-987655',
    freightCharge: 3200.00,
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
  },
  {
    id: 'shipment-3',
    shipmentNumber: 'SHP-2024-0003',
    carrierId: 'carrier-3',
    carrierName: 'JB Hunt',
    status: 'planned',
    origin: {
      name: 'Port of Houston',
      address: '111 Port Rd',
      city: 'Houston',
      state: 'TX',
      zipCode: '77012',
      country: 'USA',
    },
    destination: {
      name: 'Atlanta Distribution',
      address: '2000 Supply Chain Ave',
      city: 'Atlanta',
      state: 'GA',
      zipCode: '30336',
      country: 'USA',
    },
    scheduledPickup: new Date(Date.now() + 24 * 3600000).toISOString(),
    scheduledDelivery: new Date(Date.now() + 72 * 3600000).toISOString(),
    weight: 42000,
    pieces: 150,
    hazmat: false,
    poNumber: 'PO-78236',
    freightCharge: 4500.00,
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
  },
];

const mockRoutes: Route[] = [
  {
    id: 'route-1',
    routeName: 'Chicago to LA - I-80 West',
    origin: {
      name: 'Main Distribution Center',
      address: '1000 Warehouse Blvd',
      city: 'Chicago',
      state: 'IL',
      zipCode: '60601',
      country: 'USA',
    },
    destination: {
      name: 'West Coast Hub',
      address: '2500 Port Terminal Dr',
      city: 'Los Angeles',
      state: 'CA',
      zipCode: '90021',
      country: 'USA',
    },
    // MILES AND HOURS, matching the wire (FS-439). This read `distance: 3200` and
    // `estimatedDuration: 2160` — Chicago to LA in KILOMETRES and MINUTES, because the type
    // said km and minutes while the server sends `total_distance_miles` and
    // `estimated_duration_hours`. The mock agreed with the type and both disagreed with the
    // server, so development would have shown a plausible route and production a different
    // one by a factor of 1.6.
    totalDistanceMiles: 2015,
    estimatedDurationHours: 30,
    tollCostEstimate: 250,
    fuelCostEstimate: 800,
    optimizationCriteria: 'balanced',
    isActive: true,
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
  },
];

// TMS API
// FS-128: several transportation/geotab endpoints REQUIRE an organization_id
// query param (unlike /vehicles, which the backend derives from the JWT), and
// the frontend wasn't sending it — so drivers/carriers/shipments/fleet-summary
// 422'd in real mode (and the offline demo showed errors instead of seeded
// data). The current org is stashed in localStorage at login (authStore
// devLogin/login); read it here and pass it as a snake_case param, matching the
// existing `carrier_id` convention. Returns undefined if unknown (call behaves
// as before).

export const transportationApi = {
  // Carriers
  getCarriers: async (): Promise<PaginatedResponse<Carrier>> => {
    if (USE_MOCK) {
      await delay(MOCK_DELAY);
      return {
        items: mockCarriers,
        total: mockCarriers.length,
        skip: 0,
        limit: mockCarriers.length,
        hasMore: false,
      };
    }
    const response = await api.get<Carrier[]>('/api/v1/transportation/carriers');
    // FS-898/FS-485: `total`/`hasMore` used to be faked from `items.length`, which
    // reads as "this is everyone" even on a capped page. toListResult reads the
    // server's own X-Result-Truncated/X-Result-Limit instead.
    const { items, truncated, limit } = toListResult(response);
    return {
      items,
      total: items.length,
      skip: 0,
      limit,
      hasMore: truncated,
    };
  },

  getCarrier: async (id: string): Promise<Carrier> => {
    if (USE_MOCK) {
      await delay(MOCK_DELAY);
      const carrier = mockCarriers.find(c => c.id === id);
      if (!carrier) throw new Error('Carrier not found');
      return carrier;
    }
    const response = await api.get<Carrier>(`/api/v1/transportation/carriers/${id}`);
    return response.data;
  },

  getCarrierCompliance: async (id: string): Promise<{ score: number; issues: string[]; ctpatStatus: string }> => {
    if (USE_MOCK) {
      await delay(MOCK_DELAY);
      const carrier = mockCarriers.find(c => c.id === id);
      return {
        score: carrier?.complianceScore || 0,
        issues: carrier?.safetyRating === 'conditional' ? ['Safety rating conditional'] : [],
        ctpatStatus: carrier?.ctpatCertified ? 'certified' : 'not_certified',
      };
    }
    const response = await api.get(`/api/v1/transportation/carriers/${id}/compliance`);
    return response.data;
  },

  // Drivers
  getDrivers: async (carrierId?: string): Promise<PaginatedResponse<Driver>> => {
    if (USE_MOCK) {
      await delay(MOCK_DELAY);
      let filtered = [...mockDrivers];
      if (carrierId) filtered = filtered.filter(d => d.carrierId === carrierId);
      return {
        items: filtered,
        total: filtered.length,
        skip: 0,
        limit: filtered.length,
        hasMore: false,
      };
    }
    const response = await api.get<Driver[]>('/api/v1/transportation/drivers', { params: { carrier_id: carrierId } });
    const { items, truncated, limit } = toListResult(response);
    return {
      items,
      total: items.length,
      skip: 0,
      limit,
      hasMore: truncated,
    };
  },

  getDriver: async (id: string): Promise<Driver> => {
    if (USE_MOCK) {
      await delay(MOCK_DELAY);
      const driver = mockDrivers.find(d => d.id === id);
      if (!driver) throw new Error('Driver not found');
      return driver;
    }
    const response = await api.get<Driver>(`/api/v1/transportation/drivers/${id}`);
    return response.data;
  },

  /** `GET /api/v1/transportation/drivers/{id}/hos` — hours of service (FS-395).
   *
   *  THE DECLARED SHAPE WAS NOT THE ENDPOINT'S. It said
   *  `{driveHoursRemaining, dutyHoursRemaining, cycleHoursUsed, currentStatus, violations}`
   *  and returned `response.data` unchanged; only `violations` is a top-level field on the
   *  wire. `DriverHOSOut` sends `driver_id`, `is_compliant`, `assessable`, `missing_data`,
   *  `violations`, `warnings` and a nested `hours_summary`, so four of those five names
   *  resolved to `undefined` on the real path. Nothing consumes this method yet, which is
   *  why it never showed — it is a trap for the first caller, the FS-367 shape.
   *
   *  THE FIELDS IT OMITTED ARE THE SAFETY-CRITICAL ONES. `assessable` and `missingData`
   *  exist because "no violations" and "nobody could tell" are different facts, and the
   *  backend is explicit about it: *"A driver with no medical certificate on file has not
   *  broken a rule; nobody knows whether they have."* A type that declares only
   *  `violations` makes the second unrenderable, so the first caller would paint an
   *  unassessable driver as clear. Measured against the seeded fleet: `assessable: false`,
   *  `missing_data: ["No medical certificate on file"]`.
   *
   *  The hours are nullable by design — NULL means the driver has not reported, and 0 means
   *  out of hours. The previous mock used `|| 0`, collapsing those two into "out of hours",
   *  which is the shape `apiClientsDoNotDefaultResponses` records a warning against. */
  getDriverHOS: async (id: string): Promise<DriverHOS> => {
    if (USE_MOCK) {
      await delay(MOCK_DELAY);
      const driver = mockDrivers.find(d => d.id === id);
      const reported = driver?.hosDriveHoursRemaining ?? null;
      return {
        driverId: id,
        // Unassessable when the fixture has no driver, mirroring the server: it is not a
        // clean bill, it is an absence of one.
        assessable: driver !== undefined,
        isCompliant: driver !== undefined && reported !== 0,
        missingData: driver === undefined ? ['Driver not found'] : [],
        violations: reported === 0 ? ['Drive limit exceeded'] : [],
        warnings: [],
        hoursSummary: {
          driveHoursToday: null,
          onDutyHoursToday: null,
          cycleHours: driver?.hosCycleHoursUsed ?? null,
          driveHoursRemaining: reported,
          onDutyHoursRemaining: driver?.hosDutyHoursRemaining ?? null,
          cycleHoursRemaining: null,
        },
      };
    }
    const response = await api.get<DriverHOS>(`/api/v1/transportation/drivers/${id}/hos`);
    return response.data;
  },

  // Vehicles
  getVehicles: async (carrierId?: string): Promise<PaginatedResponse<Vehicle>> => {
    if (USE_MOCK) {
      await delay(MOCK_DELAY);
      let filtered = [...mockVehicles];
      if (carrierId) filtered = filtered.filter(v => v.carrierId === carrierId);
      return {
        items: filtered,
        total: filtered.length,
        skip: 0,
        limit: filtered.length,
        hasMore: false,
      };
    }
    // FS-99: backend returns the {items, meta} pagination envelope with a real
    // total now. Map it to the flat PaginatedResponse; tolerate either casing
    // of has_more from the transform seam.
    const response = await api.get<{
      items: Vehicle[];
      meta: { total: number; skip: number; limit: number; has_more?: boolean; hasMore?: boolean };
    }>('/api/v1/transportation/vehicles', { params: { carrier_id: carrierId } });
    const { items, meta } = response.data;
    return {
      items,
      total: meta.total,
      skip: meta.skip,
      limit: meta.limit,
      hasMore: meta.hasMore ?? meta.has_more ?? meta.skip + items.length < meta.total,
    };
  },


  // Shipments
  getShipments: async (filters?: ShipmentFilters): Promise<PaginatedResponse<Shipment>> => {
    if (USE_MOCK) {
      await delay(MOCK_DELAY);
      let filtered = [...mockShipments];
      if (filters?.status) filtered = filtered.filter(s => s.status === filters.status);
      if (filters?.carrierId) filtered = filtered.filter(s => s.carrierId === filters.carrierId);
      if (filters?.driverId) filtered = filtered.filter(s => s.driverId === filters.driverId);
      return {
        items: filtered,
        total: filtered.length,
        skip: 0,
        limit: filtered.length,
        hasMore: false,
      };
    }
    // FS-99: backend returns the {items, meta} pagination envelope with a real
    // total now. Map it to the flat PaginatedResponse; tolerate either casing
    // of has_more from the transform seam.
    const response = await api.get<{
      items: Shipment[];
      meta: { total: number; skip: number; limit: number; has_more?: boolean; hasMore?: boolean };
    }>('/api/v1/transportation/shipments', { params: { ...(filters ?? {}) } });
    const { items, meta } = response.data;
    return {
      items,
      total: meta.total,
      skip: meta.skip,
      limit: meta.limit,
      hasMore: meta.hasMore ?? meta.has_more ?? meta.skip + items.length < meta.total,
    };
  },

  getShipment: async (id: string): Promise<Shipment> => {
    if (USE_MOCK) {
      await delay(MOCK_DELAY);
      const shipment = mockShipments.find(s => s.id === id);
      if (!shipment) throw new Error('Shipment not found');
      return shipment;
    }
    const response = await api.get<Shipment>(`/api/v1/transportation/shipments/${id}`);
    return response.data;
  },

  createShipment: async (data: Partial<Shipment>): Promise<Shipment> => {
    if (USE_MOCK) {
      await delay(MOCK_DELAY);
      const newShipment: Shipment = {
        ...data as Shipment,
        id: `shipment-${Date.now()}`,
        shipmentNumber: `SHP-2024-${String(mockShipments.length + 1).padStart(4, '0')}`,
        status: 'planned',
        createdAt: new Date().toISOString(),
        updatedAt: new Date().toISOString(),
      };
      mockShipments.push(newShipment);
      return newShipment;
    }
    const response = await api.post<Shipment>('/api/v1/transportation/shipments', data);
    return response.data;
  },

  /**
   * Dispatch a shipment to a driver and a TRAILER (FS-420).
   *
   * It used to take a `vehicleId` and post `{ driver_id, vehicle_id }`. Two things were
   * wrong and each alone was fatal: the server declared its two ids as bare parameters,
   * which FastAPI reads as QUERY parameters, so every call returned 422 — the feature had
   * never worked once in real mode. And `Shipment.trailer_id` is a foreign key to
   * `yard_trailers`; there is no vehicle column on a shipment, so a vehicle id could not
   * have been stored even if the call had been well-formed.
   */
  dispatchShipment: async (id: string, driverId: string, trailerId: string): Promise<Shipment> => {
    if (USE_MOCK) {
      await delay(MOCK_DELAY);
      const shipment = mockShipments.find(s => s.id === id);
      const driver = mockDrivers.find(d => d.id === driverId);
      if (!shipment) throw new Error('Shipment not found');
      shipment.status = 'dispatched';
      shipment.driverId = driverId;
      shipment.driverName = driver ? `${driver.firstName} ${driver.lastName}` : undefined;
      // TRAILER, matching the column the real endpoint writes. This used to set
      // `shipment.vehicleId` and mutate the vehicle and driver besides — associations the
      // real dispatch does not make. That is what let a feature which returned 422 on every
      // real call look implemented: the mock was modelling a different operation.
      shipment.trailerId = trailerId;
      shipment.updatedAt = new Date().toISOString();
      if (driver) {
        driver.currentShipmentId = id;
        driver.updatedAt = new Date().toISOString();
      }
      return shipment;
    }
    const response = await api.post<Shipment>(`/api/v1/transportation/shipments/${id}/dispatch`, { driver_id: driverId, trailer_id: trailerId });
    return response.data;
  },

  /**
   * Lifecycle status transitions (delivered, exception, ...) — task D22.
   *
   * NO `note` PARAMETER (FS-658). This used to take one and post it, and there is nowhere for
   * it to go: `Shipment` has no note column and the service never read the field. A parameter
   * a caller can pass and the server cannot keep is a promise the API does not make — the
   * server now declares `extra: "forbid"` and refuses it rather than dropping it silently.
   *
   * The body itself is the other half of that fix: the route declared `status` as a bare
   * scalar, so FastAPI read it as a QUERY parameter, and every call from here answered 422.
   */
  updateShipmentStatus: async (id: string, status: Shipment['status']): Promise<Shipment> => {
    if (USE_MOCK) {
      await delay(MOCK_DELAY);
      const shipment = mockShipments.find(s => s.id === id);
      if (!shipment) throw new Error('Shipment not found');
      shipment.status = status;
      if (status === 'delivered') shipment.actualDelivery = new Date().toISOString();
      shipment.updatedAt = new Date().toISOString();
      return shipment;
    }
    const response = await api.post<Shipment>(
      `/api/v1/transportation/shipments/${id}/status`,
      { status }
    );
    return response.data;
  },

  /** `GET /api/v1/transportation/shipments/{id}/costs` (FS-397).
   *
   *  NONE OF THE FIVE DECLARED FIELDS WERE ON THE WIRE. This said
   *  `{freight, fuel, accessorials, detention, total}` and returned `response.data`
   *  unchanged; `ShipmentCostsOut` sends `shipment_id`, `linehaul`, `fuel_surcharge`,
   *  `total_cost`, `distance_miles` and `weight_lbs`. The two money figures are nested
   *  objects, not scalars — `linehaul.amount` and `fuel_surcharge.amount` — so every line of
   *  the modal's Cost Breakdown called `.toFixed(2)` on `undefined`.
   *
   *  `accessorials` and `detention` are not billed by this endpoint at all, and the mock
   *  computed both, so the breakdown looked complete in development.
   *
   *  The fuel surcharge is NOT always a measurement — `FuelSurchargeCharge` says so — which
   *  is why `rateBasis` and the two fuel prices are carried through rather than flattened to
   *  a number. */
  getShipmentCosts: async (id: string): Promise<ShipmentCosts> => {
    if (USE_MOCK) {
      await delay(MOCK_DELAY);
      const shipment = mockShipments.find(s => s.id === id);
      const freight = shipment?.freightCharge || 0;
      const fuel = freight * 0.15;
      return {
        shipmentId: id,
        linehaul: { amount: freight, rateBasis: 'per_mile', mileageCharge: freight, weightCharge: 0 },
        fuelSurcharge: { amount: fuel, rateBasis: 'per_mile' },
        totalCost: freight + fuel,
        distanceMiles: null,
        weightLbs: null,
      };
    }
    const response = await api.get<ShipmentCosts>(`/api/v1/transportation/shipments/${id}/costs`);
    return response.data;
  },

  // Routes
  getRoutes: async (): Promise<Route[]> => {
    if (USE_MOCK) {
      await delay(MOCK_DELAY);
      return mockRoutes;
    }
    const response = await api.get<Route[]>('/api/v1/transportation/routes');
    return toListResult(response).items;
  },

  // Analytics
  /** Delivery-efficiency tiles on the TMS page (FS-394).
   *
   *  THIS TYPE DESCRIBED A PAYLOAD THAT HAS NEVER EXISTED, and the backend had already
   *  written it down. `DeliveryEfficiencyOut` in `fleet_logistics.py` says:
   *
   *      `transportation.ts` types this call as `{ onTimeRate, avgTransitTime,
   *      totalDeliveries, lateDeliveries }` and three of those four names have never been
   *      on the wire … Recorded in the burn-down doc rather than silently reconciled.
   *
   *  It was right not to fix it from that side — the schema would then have agreed with the
   *  type and disagreed with the payload. This is the side that was wrong.
   *
   *  MEASURED ON THE RUNNING PAGE before the fix: "Average Transit Time" rendered as bare
   *  `h` and "Deliveries Today" was blank, because `avgTransitTime` and `totalDeliveries`
   *  are `undefined` and React renders that as nothing. `lateDeliveries` is not sent at all,
   *  so the "N late" line could never appear.
   *
   *  AND THE TILE THAT DID RENDER WAS WRONG BY 100×. `onTimeRate` is a RATIO 0..1 on the
   *  wire (`round(on_time / delivered, 4)`); the page printed `.toFixed(1)` with a `%` sign,
   *  so a genuine 33.3% on-time rate displayed as **0.3%** — and the tile's `>= 90` green
   *  threshold could never fire, because the value cannot exceed 1. The mock computed a
   *  percentage for the same field, which is why it looked right in development.
   *
   *  Returned as `onTimeRatePct` so the unit is in the name and this cannot recur silently.
   *  The mock now derives the same shape from the same arithmetic. */
  getDeliveryEfficiency: async (): Promise<{
    onTimeRatePct: number | null;
    avgTransitHours: number | null;
    deliveredToday: number | null;
    totalDelivered: number | null;
  }> => {
    if (USE_MOCK) {
      await delay(MOCK_DELAY);
      const delivered = mockShipments.filter(s => s.status === 'delivered');
      const onTime = delivered.filter(s => !s.actualDelivery || new Date(s.actualDelivery) <= new Date(s.scheduledDelivery)).length;
      const today = new Date().toDateString();
      return {
        onTimeRatePct: delivered.length > 0 ? (onTime / delivered.length) * 100 : 100,
        avgTransitHours: 36,
        deliveredToday: delivered.filter(
          s => s.actualDelivery && new Date(s.actualDelivery).toDateString() === today,
        ).length,
        totalDelivered: delivered.length,
      };
    }
    // /api/v1/logistics is legacy-camel (never-registered); data arrives camelCase.
    const response = await api.get<{
      onTimeRate: number; avgTransitHours: number; deliveredToday: number; totalDelivered: number;
    }>('/api/v1/logistics/delivery-efficiency');
    const wire = response.data;
    // NULL, NOT A DEFAULT, when a figure is absent — and `apiClientsDoNotDefaultResponses`
    // was right to reject the first version of this, which used `?? 0` and `?? 1`.
    //
    // `?? 1` on the ratio would have rendered **100% on time** whenever the payload was
    // unusable: a green all-clear generated by the absence of the data that decides it,
    // which is the class this repo has already found on HOS hours twice and on
    // `activeViolations`. The endpoint's own 1.0 means something different — it computed
    // over zero deliveries — and only it is entitled to say that.
    //
    // All four are required fields on `DeliveryEfficiencyOut`, so null here means the
    // response was malformed, and the page renders an em dash rather than a number.
    const num = (v: unknown): number | null => (typeof v === 'number' ? v : null);
    const ratio = num(wire?.onTimeRate);
    return {
      onTimeRatePct: ratio === null ? null : ratio * 100,
      avgTransitHours: num(wire?.avgTransitHours),
      deliveredToday: num(wire?.deliveredToday),
      totalDelivered: num(wire?.totalDelivered),
    };
  },

  getComplianceSummary: async (): Promise<{
    totalCarriers: number;
    ctpatCertified: number;
    activeViolations: number;
    safetyAlerts: number;
    /** How many drivers the violation count was actually computed over, and how many had not
     *  reported the hours it needs. `activeViolations: 0` means something different depending
     *  on which of those is which — the tile paints zero GREEN, and a fleet where nobody had
     *  reported used to get that green. Optional: an older backend sends neither. */
    driversAssessed?: number;
    driversUnassessable?: number;
  }> => {
    if (USE_MOCK) {
      await delay(MOCK_DELAY);
      return {
        totalCarriers: mockCarriers.length,
        ctpatCertified: mockCarriers.filter(c => c.ctpatCertified).length,
        activeViolations: 2,
        safetyAlerts: 1,
        driversAssessed: mockDrivers.length,
        driversUnassessable: 0,
      };
    }
    const response = await api.get('/api/v1/logistics/compliance/summary');
    return response.data;
  },
};

// GeoTab Integration API
/** What `/geotab/fleet/summary` actually reports. Every field optional because a
 *  deployment with no telematics configured sends none of them, and a blank tile is
 *  honest where a zero would claim a measurement. */
export interface FleetSummary {
  /** NAMED AFTER THE WIRE, not after a nicer word. The endpoint counts DEVICES, and
   *  calling them `totalVehicles` was part of what made the original mismatch invisible —
   *  the shape read plausibly while sharing no field name with any response. One name per
   *  concept means no adapter to drift, and nothing for the wire-vocabulary sweep to
   *  report as unsourced. */
  totalDevices?: number;
  activeDevices?: number;
  totalDrivers?: number;
  driversOnDuty?: number;
  driversDriving?: number;
  exceptionsToday?: number;
  totalMilesToday?: number;
  averageFuelEfficiency?: number;
  /** True when the figures come from the simulator rather than a device. */
  simulated?: boolean;
  dataSourceWarning?: string | null;
}

export const geoTabApi = {
  // Devices
  getDevices: async (): Promise<GeoTabDevice[]> => {
    if (USE_MOCK) {
      await delay(MOCK_DELAY);
      return [
        { id: 'gt-device-001', deviceType: 'GO9', serialNumber: 'GT900001', vehicleId: 'vehicle-1', driverId: 'driver-1', isActive: true, firmwareVersion: '2.3.1' },
        { id: 'gt-device-002', deviceType: 'GO9', serialNumber: 'GT900002', vehicleId: 'vehicle-2', driverId: 'driver-2', isActive: true, lastCommunication: new Date().toISOString() },
        { id: 'gt-device-003', deviceType: 'GO8', serialNumber: 'GT800003', vehicleId: 'vehicle-3', driverId: 'driver-3', isActive: true },
      ];
    }
    const response = await api.get<GeoTabDevice[]>('/api/v1/geotab/devices');
    return response.data;
  },

  getDeviceLocation: async (deviceId: string): Promise<GeoLocation> => {
    if (USE_MOCK) {
      await delay(MOCK_DELAY);
      return {
        latitude: 39.7392 + (Math.random() - 0.5) * 0.1,
        longitude: -104.9903 + (Math.random() - 0.5) * 0.1,
        speed: Math.random() * 80,
        heading: Math.random() * 360,
        timestamp: new Date().toISOString(),
        address: 'I-70 Eastbound, Mile Marker 278',
      };
    }
    const response = await api.get<GeoLocation>(`/api/v1/geotab/devices/${deviceId}/location`);
    return response.data;
  },

  // Trips
  getTrips: async (deviceId: string, from: string, to: string): Promise<GeoTabTrip[]> => {
    if (USE_MOCK) {
      await delay(MOCK_DELAY);
      return [
        {
          id: 'trip-001',
          deviceId,
          driverId: 'driver-1',
          startTime: from,
          endTime: to,
          distance: 3200,
          duration: 2160,
          startLocation: { latitude: 41.8781, longitude: -87.6298, timestamp: from },
          endLocation: { latitude: 34.0522, longitude: -118.2437, timestamp: to },
          maxSpeed: 110,
          averageSpeed: 88,
          idleTime: 45,
          harshBrakingEvents: 2,
          harshAccelerationEvents: 1,
          speedingEvents: 0,
        },
      ];
    }
    const response = await api.get<GeoTabTrip[]>(`/api/v1/geotab/devices/${deviceId}/trips`, { params: { from, to } });
    return response.data;
  },

  // Diagnostics
  getDiagnostics: async (deviceId: string): Promise<GeoTabDiagnostic[]> => {
    if (USE_MOCK) {
      await delay(MOCK_DELAY);
      return [
        { id: 'diag-1', deviceId, name: 'Mass Air Flow Sensor', source: 'OBDII', timestamp: new Date().toISOString(), isActive: false },
        { id: 'diag-2', deviceId, name: 'Seatbelt Violation', source: 'Safety', value: 'Unbuckled', timestamp: new Date().toISOString(), isActive: true },
      ];
    }
    const response = await api.get<any>(`/api/v1/geotab/devices/${deviceId}/diagnostics`);
    const d = response.data;
    // Backend returns an envelope with diagnostics.dtc_codes; the transform
    // seam camelizes it (dtcCodes/lastSeen) before we flatten to entries.
    if (Array.isArray(d)) return d as GeoTabDiagnostic[];
    const codes: string[] = d?.diagnostics?.dtcCodes ?? [];
    return codes.map((code, i) => ({
      id: `${deviceId}-dtc-${i}`,
      deviceId,
      name: code,
      source: 'OBDII',
      // NOT `?? new Date()`. A device that has never reported would have had every fault
      // code stamped with the CURRENT time — "this fault occurred just now" — which is the
      // most confident thing the row could say and the one thing nobody knows. `lastSeen` is
      // already an approximation (a heartbeat's time standing in for a fault's), and
      // approximating an approximation with `now()` is where it stops being one.
      timestamp: d?.lastSeen ?? null,
      isActive: true,
    }));
  },

  // Exceptions (Rules Violations)
  getExceptions: async (deviceId?: string): Promise<GeoTabException[]> => {
    if (USE_MOCK) {
      await delay(MOCK_DELAY);
      const exceptions: GeoTabException[] = [
        {
          id: 'exc-1',
          deviceId: 'gt-device-001',
          ruleName: 'Speeding > 10mph over',
          startTime: new Date(Date.now() - 2 * 3600000).toISOString(),
          endTime: new Date(Date.now() - 1.9 * 3600000).toISOString(),
          duration: 6,
          location: { latitude: 39.5, longitude: -105.0, timestamp: new Date().toISOString() },
          driverId: 'driver-1',
          acknowledged: false,
        },
      ];
      if (deviceId) return exceptions.filter(e => e.deviceId === deviceId);
      return exceptions;
    }
    const response = await api.get<any>('/api/v1/geotab/exceptions', { params: deviceId ? { device_id: deviceId } : undefined });
    // Backend wraps the list in an envelope ({exceptions: [...]}); unwrap either shape.
    return (response.data?.exceptions ?? response.data) as GeoTabException[];
  },

  /**
   * Fleet summary from GeoTab.
   *
   * THE DECLARED SHAPE AND THE WIRE HAD NOTHING IN COMMON. This promised
   * `totalVehicles / vehiclesMoving / vehiclesIdle / vehiclesOffline / avgSpeed /
   * totalDistanceToday / fuelConsumedToday` and returned `response.data` untouched;
   * `/geotab/fleet/summary` sends `total_devices / active_devices / total_drivers /
   * drivers_on_duty / drivers_driving / exceptions_today / hos_violations_today /
   * average_fuel_efficiency / total_miles_today`. Not one field overlapped, so every
   * figure on the "Fleet Status (GeoTab Live)" card was `undefined` — rendering blanks
   * next to bare units, " mph" and " mi".
   *
   * Mapped to the counterparts that genuinely exist. `avgSpeed` and `fuelConsumedToday`
   * have none — the server reports fuel EFFICIENCY, which is a different quantity — so
   * they are absent rather than zero, and the card omits those tiles.
   *
   * AND THE PAYLOAD SAYS IT IS SIMULATED. Every GeoTab response carries
   * `simulated: true`, `data_source: 'geotab_simulator'` and a warning that the figures
   * are "not valid for DOT/ELD compliance reporting" — added server-side precisely so a
   * consumer could tell. Nothing read it, and the card's heading said "Live". It is
   * carried through here so the UI can stop claiming that.
   */
  getFleetSummary: async (): Promise<FleetSummary> => {
    if (USE_MOCK) {
      await delay(MOCK_DELAY);
      return {
        totalDevices: 3,
        activeDevices: 2,
        totalDrivers: 4,
        driversOnDuty: 2,
        driversDriving: 1,
        exceptionsToday: 3,
        totalMilesToday: 1250,
        averageFuelEfficiency: 7.4,
        simulated: true,
      };
    }
    const response = await api.get<Record<string, any>>('/api/v1/geotab/fleet/summary');
    const d = response.data ?? {};
    // `/api/v1/geotab` is not registered on the casing seam, so these arrive snake_case.
    // The camelCase fallbacks cover a deployment that registers the prefix later.
    return {
      totalDevices: d.total_devices ?? d.totalDevices,
      activeDevices: d.active_devices ?? d.activeDevices,
      totalDrivers: d.total_drivers ?? d.totalDrivers,
      driversOnDuty: d.drivers_on_duty ?? d.driversOnDuty,
      driversDriving: d.drivers_driving ?? d.driversDriving,
      exceptionsToday: d.exceptions_today ?? d.exceptionsToday,
      totalMilesToday: d.total_miles_today ?? d.totalMilesToday,
      averageFuelEfficiency: d.average_fuel_efficiency ?? d.averageFuelEfficiency,
      simulated: Boolean(d.simulated),
      dataSourceWarning: d.warning ?? null,
    };
  },
};

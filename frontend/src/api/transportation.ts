import { api } from './client';
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
    contactEmail: 'dispatch@swifttrans.com',
    contactPhone: '+1-555-1000',
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
    contactEmail: 'ops@schneider.com',
    contactPhone: '+1-555-1001',
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
    contactEmail: 'fleet@jbhunt.com',
    contactPhone: '+1-555-1002',
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
    currentShipmentId: 'shipment-1',
    geoTabDeviceId: 'gt-device-001',
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
    currentShipmentId: 'shipment-2',
    geoTabDeviceId: 'gt-device-002',
    lastLocation: {
      latitude: 39.7392,
      longitude: -104.9903,
      speed: 65,
      timestamp: new Date().toISOString(),
    },
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
    geoTabDeviceId: 'gt-device-003',
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
    currentShipmentId: 'shipment-1',
    geoTabDeviceId: 'gt-device-001',
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
    currentShipmentId: 'shipment-2',
    geoTabDeviceId: 'gt-device-002',
    currentLocation: {
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
    geoTabDeviceId: 'gt-device-003',
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
    vehicleId: 'vehicle-1',
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
    estimatedDelivery: new Date(Date.now() + 10 * 3600000).toISOString(),
    freightDescription: 'Electronics - Consumer Goods',
    weight: 25000,
    pieces: 500,
    palletCount: 20,
    hazmat: false,
    poNumber: 'PO-78234',
    bolNumber: 'BOL-2024-001',
    proNumber: 'PRO-987654',
    freightCharge: 2850.00,
    detentionRate: 50,
    geoTabTripId: 'trip-001',
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
    vehicleId: 'vehicle-2',
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
    estimatedDelivery: new Date(Date.now() + 5 * 3600000).toISOString(),
    freightDescription: 'Frozen Foods - Reefer Required',
    weight: 35000,
    pieces: 800,
    palletCount: 32,
    hazmat: false,
    temperatureRequired: -18,
    poNumber: 'PO-78235',
    bolNumber: 'BOL-2024-002',
    proNumber: 'PRO-987655',
    freightCharge: 3200.00,
    detentionRate: 65,
    currentLocation: {
      latitude: 39.7392,
      longitude: -104.9903,
      speed: 65,
      timestamp: new Date().toISOString(),
    },
    geoTabTripId: 'trip-002',
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
    freightDescription: 'Steel Components - Flatbed',
    weight: 42000,
    pieces: 150,
    hazmat: false,
    poNumber: 'PO-78236',
    freightCharge: 4500.00,
    detentionRate: 75,
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
  },
];

const mockRoutes: Route[] = [
  {
    id: 'route-1',
    name: 'Chicago to LA - I-80 West',
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
    distance: 3200,
    estimatedDuration: 2160,
    averageSpeed: 88,
    tollCosts: 250,
    fuelCosts: 800,
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
    const items = response.data;
    return {
      items,
      total: items.length,
      skip: 0,
      limit: items.length,
      hasMore: false,
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
    const items = response.data;
    return {
      items,
      total: items.length,
      skip: 0,
      limit: items.length,
      hasMore: false,
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

  getDriverHOS: async (id: string): Promise<{ 
    driveHoursRemaining: number; 
    dutyHoursRemaining: number; 
    cycleHoursUsed: number;
    currentStatus: string;
    violations: string[];
  }> => {
    if (USE_MOCK) {
      await delay(MOCK_DELAY);
      const driver = mockDrivers.find(d => d.id === id);
      return {
        driveHoursRemaining: driver?.hosDriveHoursRemaining || 0,
        dutyHoursRemaining: driver?.hosDutyHoursRemaining || 0,
        cycleHoursUsed: driver?.hosCycleHoursUsed || 0,
        currentStatus: driver?.currentHosStatus || 'off_duty',
        violations: driver?.hosDriveHoursRemaining === 0 ? ['Drive limit exceeded'] : [],
      };
    }
    const response = await api.get(`/api/v1/transportation/drivers/${id}/hos`);
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

  dispatchShipment: async (id: string, driverId: string, vehicleId: string): Promise<Shipment> => {
    if (USE_MOCK) {
      await delay(MOCK_DELAY);
      const shipment = mockShipments.find(s => s.id === id);
      const driver = mockDrivers.find(d => d.id === driverId);
      const vehicle = mockVehicles.find(v => v.id === vehicleId);
      if (!shipment) throw new Error('Shipment not found');
      shipment.status = 'dispatched';
      shipment.driverId = driverId;
      shipment.driverName = driver ? `${driver.firstName} ${driver.lastName}` : undefined;
      shipment.vehicleId = vehicleId;
      shipment.updatedAt = new Date().toISOString();
      if (driver) {
        driver.currentShipmentId = id;
        driver.currentVehicleId = vehicleId;
        driver.updatedAt = new Date().toISOString();
      }
      if (vehicle) {
        vehicle.currentDriverId = driverId;
        vehicle.currentShipmentId = id;
        vehicle.updatedAt = new Date().toISOString();
      }
      return shipment;
    }
    const response = await api.post<Shipment>(`/api/v1/transportation/shipments/${id}/dispatch`, { driver_id: driverId, vehicle_id: vehicleId });
    return response.data;
  },

  // Lifecycle status transitions (delivered, exception, ...) — task D22.
  updateShipmentStatus: async (id: string, status: Shipment['status'], note?: string): Promise<Shipment> => {
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
      { status, note }
    );
    return response.data;
  },

  getShipmentCosts: async (id: string): Promise<{ freight: number; fuel: number; accessorials: number; detention: number; total: number }> => {
    if (USE_MOCK) {
      await delay(MOCK_DELAY);
      const shipment = mockShipments.find(s => s.id === id);
      const freight = shipment?.freightCharge || 0;
      const fuel = freight * 0.15;
      const accessorials = 0;
      const detention = (shipment?.detentionHours || 0) * (shipment?.detentionRate || 0);
      return {
        freight,
        fuel,
        accessorials,
        detention,
        total: freight + fuel + accessorials + detention,
      };
    }
    const response = await api.get(`/api/v1/transportation/shipments/${id}/costs`);
    return response.data;
  },

  // Routes
  getRoutes: async (): Promise<Route[]> => {
    if (USE_MOCK) {
      await delay(MOCK_DELAY);
      return mockRoutes;
    }
    const response = await api.get<Route[]>('/api/v1/transportation/routes');
    return response.data;
  },

  // Analytics
  getDeliveryEfficiency: async (): Promise<{ 
    onTimeRate: number; 
    avgTransitTime: number; 
    totalDeliveries: number;
    lateDeliveries: number;
  }> => {
    if (USE_MOCK) {
      await delay(MOCK_DELAY);
      const delivered = mockShipments.filter(s => s.status === 'delivered');
      const onTime = delivered.filter(s => !s.actualDelivery || new Date(s.actualDelivery) <= new Date(s.scheduledDelivery)).length;
      return {
        onTimeRate: delivered.length > 0 ? (onTime / delivered.length) * 100 : 0,
        avgTransitTime: 36,
        totalDeliveries: delivered.length,
        lateDeliveries: delivered.length - onTime,
      };
    }
    // /api/v1/logistics is legacy-camel (never-registered); data arrives camelCase.
    const response = await api.get('/api/v1/logistics/delivery-efficiency');
    return response.data;
  },

  getComplianceSummary: async (): Promise<{
    totalCarriers: number;
    ctpatCertified: number;
    activeViolations: number;
    safetyAlerts: number;
  }> => {
    if (USE_MOCK) {
      await delay(MOCK_DELAY);
      return {
        totalCarriers: mockCarriers.length,
        ctpatCertified: mockCarriers.filter(c => c.ctpatCertified).length,
        activeViolations: 2,
        safetyAlerts: 1,
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
          vehicleId: 'vehicle-1',
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
        { id: 'diag-1', deviceId, diagnosticCode: 'P0101', name: 'Mass Air Flow Sensor', source: 'OBDII', timestamp: new Date().toISOString(), isActive: false },
        { id: 'diag-2', deviceId, diagnosticCode: 'Seatbelt', name: 'Seatbelt Violation', source: 'Safety', value: 'Unbuckled', timestamp: new Date().toISOString(), isActive: true },
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
      diagnosticCode: code,
      name: code,
      source: 'OBDII',
      timestamp: d?.lastSeen ?? new Date().toISOString(),
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
          ruleType: 'Speeding',
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

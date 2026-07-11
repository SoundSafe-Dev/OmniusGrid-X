import { api } from './client';
import type { FleetVehiclePosition, ShipmentRoute, GeofenceZone, FleetUpdate } from '../types';

import { USE_MOCK } from './mockMode';
const MOCK_DELAY = 500;

const delay = (ms: number) => new Promise(resolve => setTimeout(resolve, ms));

// Mock vehicle positions (simulated GeoTab data)
const mockVehiclePositions: FleetVehiclePosition[] = [
  {
    deviceId: 'gt-device-001',
    vehicleId: 'vehicle-1',
    driverId: 'driver-1',
    driverName: 'John Smith',
    position: {
      latitude: 41.8781,
      longitude: -87.6298,
      speed: 65,
      heading: 270,
      timestamp: new Date().toISOString(),
    },
    status: 'moving',
    speed: 65,
    heading: 270,
    lastUpdate: new Date().toISOString(),
  },
  {
    deviceId: 'gt-device-002',
    vehicleId: 'vehicle-2',
    driverId: 'driver-2',
    driverName: 'Sarah Johnson',
    position: {
      latitude: 39.7392,
      longitude: -104.9903,
      speed: 3,
      heading: 180,
      timestamp: new Date().toISOString(),
    },
    status: 'idle',
    speed: 3,
    heading: 180,
    lastUpdate: new Date().toISOString(),
  },
  {
    deviceId: 'gt-device-003',
    vehicleId: 'vehicle-3',
    driverId: 'driver-3',
    driverName: 'Mike Davis',
    position: {
      latitude: 34.0522,
      longitude: -118.2437,
      speed: 0,
      heading: 0,
      timestamp: new Date(Date.now() - 10 * 60000).toISOString(),
    },
    status: 'stopped',
    speed: 0,
    heading: 0,
    lastUpdate: new Date(Date.now() - 10 * 60000).toISOString(),
  },
  {
    deviceId: 'gt-device-004',
    vehicleId: 'vehicle-4',
    driverId: 'driver-4',
    driverName: 'Emily Wilson',
    position: {
      latitude: 40.7128,
      longitude: -74.0060,
      speed: 45,
      heading: 90,
      timestamp: new Date().toISOString(),
    },
    status: 'moving',
    speed: 45,
    heading: 90,
    lastUpdate: new Date().toISOString(),
  },
];

// Mock shipment routes
const mockShipmentRoutes: ShipmentRoute[] = [
  {
    shipmentId: 'shipment-1',
    shipmentNumber: 'SHP-2024-0001',
    origin: { latitude: 41.8781, longitude: -87.6298, timestamp: new Date().toISOString() },
    destination: { latitude: 34.0522, longitude: -118.2437, timestamp: new Date().toISOString() },
    waypoints: [
      { latitude: 41.8781, longitude: -87.6298, timestamp: new Date().toISOString() },
      { latitude: 40.7128, longitude: -74.0060, timestamp: new Date().toISOString() },
      { latitude: 39.7392, longitude: -104.9903, timestamp: new Date().toISOString() },
      { latitude: 34.0522, longitude: -118.2437, timestamp: new Date().toISOString() },
    ],
    status: 'in_transit',
    vehicleId: 'vehicle-1',
    driverName: 'John Smith',
    color: '#3b82f6',
  },
  {
    shipmentId: 'shipment-2',
    shipmentNumber: 'SHP-2024-0002',
    origin: { latitude: 34.0522, longitude: -118.2437, timestamp: new Date().toISOString() },
    destination: { latitude: 41.8781, longitude: -87.6298, timestamp: new Date().toISOString() },
    waypoints: [
      { latitude: 34.0522, longitude: -118.2437, timestamp: new Date().toISOString() },
      { latitude: 39.7392, longitude: -104.9903, timestamp: new Date().toISOString() },
      { latitude: 41.8781, longitude: -87.6298, timestamp: new Date().toISOString() },
    ],
    status: 'dispatched',
    vehicleId: 'vehicle-2',
    driverName: 'Sarah Johnson',
    color: '#a855f7',
  },
];

// Mock geofence zones
const mockGeofenceZones: GeofenceZone[] = [
  {
    id: 'geofence-1',
    name: 'Chicago Hub - Safe Zone',
    type: 'circle',
    center: { latitude: 41.8781, longitude: -87.6298, timestamp: new Date().toISOString() },
    radius: 5000, // 5km
    color: 'green',
    description: 'Main distribution center safe zone',
  },
  {
    id: 'geofence-2',
    name: 'LA Port - Restricted',
    type: 'circle',
    center: { latitude: 34.0522, longitude: -118.2437, timestamp: new Date().toISOString() },
    radius: 2000, // 2km
    color: 'red',
    description: 'High security zone - authorization required',
  },
  {
    id: 'geofence-3',
    name: 'Denver Checkpoint',
    type: 'circle',
    center: { latitude: 39.7392, longitude: -104.9903, timestamp: new Date().toISOString() },
    radius: 3000, // 3km
    color: 'yellow',
    description: 'Inspection checkpoint zone',
  },
];

// Simulate vehicle movement
export const simulateVehicleMovement = (positions: FleetVehiclePosition[]): FleetVehiclePosition[] => {
  return positions.map(vehicle => {
    if (vehicle.status === 'moving') {
      const speedMps = vehicle.speed * 0.44704; // mph to m/s
      const distance = speedMps * 30; // distance in 30 seconds
      const headingRad = (vehicle.heading * Math.PI) / 180;
      
      // Approximate lat/lng change (simplified)
      const latChange = (distance * Math.cos(headingRad)) / 111320;
      const lngChange = (distance * Math.sin(headingRad)) / (111320 * Math.cos(vehicle.position.latitude * Math.PI / 180));
      
      return {
        ...vehicle,
        position: {
          ...vehicle.position,
          latitude: vehicle.position.latitude + latChange,
          longitude: vehicle.position.longitude + lngChange,
          timestamp: new Date().toISOString(),
        },
        lastUpdate: new Date().toISOString(),
      };
    }
    return vehicle;
  });
};

// Fleet Tracker API
export const fleetTrackerApi = {
  // Get all vehicle positions
  getAllVehiclePositions: async (): Promise<FleetVehiclePosition[]> => {
    if (USE_MOCK) {
      await delay(MOCK_DELAY);
      return simulateVehicleMovement(mockVehiclePositions);
    }
    const response = await api.get<FleetVehiclePosition[]>('/api/v1/fleet/vehicles/locations');
    return response.data;
  },

  // Get single vehicle position
  getVehiclePosition: async (deviceId: string): Promise<FleetVehiclePosition | null> => {
    if (USE_MOCK) {
      await delay(MOCK_DELAY);
      const vehicle = mockVehiclePositions.find(v => v.deviceId === deviceId);
      return vehicle || null;
    }
    const response = await api.get<FleetVehiclePosition>(`/api/v1/fleet/vehicles/${deviceId}/location`);
    return response.data;
  },

  // Get active shipment routes
  getActiveShipmentRoutes: async (): Promise<ShipmentRoute[]> => {
    if (USE_MOCK) {
      await delay(MOCK_DELAY);
      return mockShipmentRoutes;
    }
    const response = await api.get<ShipmentRoute[]>('/api/v1/fleet/shipments/active-routes');
    return response.data;
  },

  // Get geofence zones
  getGeofenceZones: async (): Promise<GeofenceZone[]> => {
    if (USE_MOCK) {
      await delay(MOCK_DELAY);
      return mockGeofenceZones;
    }
    const response = await api.get<GeofenceZone[]>('/api/v1/fleet/geofences');
    return response.data;
  },

  // Subscribe to WebSocket updates (returns cleanup function)
  subscribeToUpdates: (onUpdate: (update: FleetUpdate) => void): (() => void) => {
    if (USE_MOCK) {
      // Simulate WebSocket with polling
      const interval = setInterval(async () => {
        const positions = await fleetTrackerApi.getAllVehiclePositions();
        positions.forEach(position => {
          onUpdate({
            type: 'vehicle_position',
            timestamp: new Date().toISOString(),
            data: position,
          });
        });
      }, 30000); // 30 seconds polling

      return () => clearInterval(interval);
    }

    // Real WebSocket implementation
    const wsUrl = `${import.meta.env.VITE_WS_URL || 'ws://localhost:8000'}/ws/fleet-tracking`;
    const ws = new WebSocket(wsUrl);

    ws.onmessage = (event) => {
      try {
        const update: FleetUpdate = JSON.parse(event.data);
        onUpdate(update);
      } catch (error) {
        console.error('Failed to parse WebSocket message:', error);
      }
    };

    ws.onerror = (error) => {
      console.error('WebSocket error:', error);
    };

    return () => ws.close();
  },
};

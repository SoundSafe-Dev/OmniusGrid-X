import { api } from './client';
import type { 
  VehicleHealthStatus, 
  DiagnosticTroubleCode, 
  SecurityEvent,
  DriverSafetyMetrics 
} from '../types';
import {
  mockVehicleHealthStatuses,
  mockDTCs,
  mockSecurityEvents,
  mockDriverSafetyMetrics,
  getMockVehicleHealthById,
  getMockDTCsByVehicle,
  getMockSecurityEventsByVehicle,
  getMockUnacknowledgedSecurityEvents,
  getMockCriticalSecurityEvents,
  getMockDriverSafetyById,
  getHealthStatistics,
} from './mocks/fleetHealthMocks';
import { USE_MOCK } from './mockMode';

const MOCK_DELAY = 300;
const delay = (ms: number) => new Promise(resolve => setTimeout(resolve, ms));

export const fleetHealthApi = {
  getAllVehicleHealth: async (): Promise<VehicleHealthStatus[]> => {
    if (USE_MOCK) {
      await delay(MOCK_DELAY);
      return mockVehicleHealthStatuses;
    }
    const response = await api.get<VehicleHealthStatus[]>('/api/v1/fleet/health');
    return response.data;
  },

  getVehicleHealth: async (vehicleId: string): Promise<VehicleHealthStatus | null> => {
    if (USE_MOCK) {
      await delay(MOCK_DELAY);
      return getMockVehicleHealthById(vehicleId) || null;
    }
    const response = await api.get<VehicleHealthStatus>(`/api/v1/fleet/health/${vehicleId}`);
    return response.data;
  },

  getAllDTCs: async (): Promise<DiagnosticTroubleCode[]> => {
    if (USE_MOCK) {
      await delay(MOCK_DELAY);
      return mockDTCs.filter(d => !d.cleared);
    }
    const response = await api.get<DiagnosticTroubleCode[]>('/api/v1/fleet/dtcs');
    return response.data;
  },

  getDTCsByVehicle: async (vehicleId: string): Promise<DiagnosticTroubleCode[]> => {
    if (USE_MOCK) {
      await delay(MOCK_DELAY);
      return getMockDTCsByVehicle(vehicleId);
    }
    const response = await api.get<DiagnosticTroubleCode[]>(`/api/v1/fleet/vehicles/${vehicleId}/dtcs`);
    return response.data;
  },


  getSecurityEvents: async (): Promise<SecurityEvent[]> => {
    if (USE_MOCK) {
      await delay(MOCK_DELAY);
      return mockSecurityEvents;
    }
    const response = await api.get<SecurityEvent[]>('/api/v1/fleet/security/events');
    return response.data;
  },

  getSecurityEventsByVehicle: async (vehicleId: string): Promise<SecurityEvent[]> => {
    if (USE_MOCK) {
      await delay(MOCK_DELAY);
      return getMockSecurityEventsByVehicle(vehicleId);
    }
    const response = await api.get<SecurityEvent[]>(`/api/v1/fleet/vehicles/${vehicleId}/security`);
    return response.data;
  },

  getUnacknowledgedSecurityEvents: async (): Promise<SecurityEvent[]> => {
    if (USE_MOCK) {
      await delay(MOCK_DELAY);
      return getMockUnacknowledgedSecurityEvents();
    }
    const response = await api.get<SecurityEvent[]>('/api/v1/fleet/security/events?acknowledged=false');
    return response.data;
  },

  getCriticalSecurityEvents: async (): Promise<SecurityEvent[]> => {
    if (USE_MOCK) {
      await delay(MOCK_DELAY);
      return getMockCriticalSecurityEvents();
    }
    const response = await api.get<SecurityEvent[]>('/api/v1/fleet/security/events?severity=critical');
    return response.data;
  },

  acknowledgeSecurityEvent: async (eventId: string): Promise<void> => {
    if (USE_MOCK) {
      await delay(MOCK_DELAY);
      return;
    }
    await api.patch(`/api/v1/fleet/security/events/${eventId}`, { acknowledged: true });
  },

  getDriverSafetyMetrics: async (): Promise<DriverSafetyMetrics[]> => {
    if (USE_MOCK) {
      await delay(MOCK_DELAY);
      return mockDriverSafetyMetrics;
    }
    const response = await api.get<DriverSafetyMetrics[]>('/api/v1/fleet/safety/drivers');
    return response.data;
  },

  getDriverSafetyById: async (driverId: string): Promise<DriverSafetyMetrics | null> => {
    if (USE_MOCK) {
      await delay(MOCK_DELAY);
      return getMockDriverSafetyById(driverId) || null;
    }
    const response = await api.get<DriverSafetyMetrics>(`/api/v1/fleet/safety/drivers/${driverId}`);
    return response.data;
  },

  getHealthStatistics: async () => {
    if (USE_MOCK) {
      await delay(MOCK_DELAY);
      return getHealthStatistics();
    }
    const response = await api.get('/api/v1/fleet/health/statistics');
    return response.data;
  },
};

// NOTE: a `subscribeToHealthUpdates` helper used to live here. It opened a
// WebSocket to `/ws/fleet-health`, which the backend does not serve — the only
// socket route is `/ws` — so in real mode it never delivered an update; it just
// logged an onerror. It also defaulted to `ws://`, so it would have failed on any
// HTTPS deployment even if the route had existed. Nothing in the app called it.
// Removed rather than rewired: the same dead-socket pattern was already replaced
// with REST polling for geofencing and fleetTracker. If live vehicle-health
// updates are wanted, poll `getAllVehicleHealth()` (or add a real server route
// first) instead of resurrecting this.

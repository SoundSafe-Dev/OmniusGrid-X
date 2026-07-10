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

  clearDTC: async (dtcCode: string, vehicleId: string): Promise<void> => {
    if (USE_MOCK) {
      await delay(MOCK_DELAY);
      return;
    }
    await api.patch(`/api/v1/fleet/dtcs/${dtcCode}`, { vehicleId, cleared: true });
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

  subscribeToHealthUpdates: (onUpdate: (update: VehicleHealthStatus) => void): (() => void) => {
    if (USE_MOCK) {
      const interval = setInterval(async () => {
        const vehicles = await fleetHealthApi.getAllVehicleHealth();
        if (Math.random() > 0.8 && vehicles.length > 0) {
          const randomVehicle = vehicles[Math.floor(Math.random() * vehicles.length)];
          onUpdate({
            ...randomVehicle,
            lastCommunication: new Date().toISOString(),
          });
        }
      }, 20000);
      return () => clearInterval(interval);
    }
    const wsUrl = `${import.meta.env.VITE_WS_URL || 'ws://localhost:8000'}/ws/fleet-health`;
    const ws = new WebSocket(wsUrl);
    ws.onmessage = (event) => {
      try {
        const update: VehicleHealthStatus = JSON.parse(event.data);
        onUpdate(update);
      } catch (error) {
        console.error('Failed to parse WebSocket message:', error);
      }
    };
    ws.onerror = (error) => console.error('Fleet Health WebSocket error:', error);
    return () => ws.close();
  },
};

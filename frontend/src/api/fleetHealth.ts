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

/** `FleetHealthStatsResponse` in `app/api/fleet_health.py`, after the casing seam.
 *
 *  THREE FIELDS, and `totalVehicles` is deliberately absent from this type: the endpoint
 *  computes it as the size of the active-diagnostics set, so it equals `vehiclesWithIssues`
 *  by construction and a healthy fleet would report zero total vehicles. Declaring it here
 *  would make the client repeat the claim (FS-398). */
export interface FleetHealthStatistics {
  activeDtcs: number;
  criticalDtcs: number;
  vehiclesWithIssues: number;
}

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

  /** `GET /api/v1/fleet/health/statistics` — the two DTC counts, and nothing else (FS-398).
   *
   *  HAD NO RETURN TYPE AT ALL, so `response.data` was `any` and every consumer was
   *  unchecked. `HealthSecurityPanel` assigned it straight into a state object with eight
   *  differently-named keys, and TypeScript had nothing to compare. All four tiles rendered
   *  blank in real mode; the mock returned the eight-key shape, so development looked fine.
   *
   *  The mock is a different shape from the wire ON PURPOSE and that is the bug it hid: it
   *  returns per-status counts and a safety score which this endpoint does not compute and
   *  cannot — `GeoTabDiagnostic.vehicle_id` is a bare string with no foreign key to
   *  `vehicles`, so the diagnostics table cannot even tell you the fleet size. The panel
   *  derives those from the vehicle list it already fetches. */
  getHealthStatistics: async (): Promise<FleetHealthStatistics> => {
    if (USE_MOCK) {
      await delay(MOCK_DELAY);
      const m = getHealthStatistics();
      return { activeDtcs: m.totalActiveDTCs, criticalDtcs: m.criticalDTCs, vehiclesWithIssues: m.warning };
    }
    const response = await api.get<FleetHealthStatistics>('/api/v1/fleet/health/statistics');
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

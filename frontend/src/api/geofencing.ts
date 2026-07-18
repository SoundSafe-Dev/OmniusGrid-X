import { api } from './client';
import type {
  GeofenceZoneExtended,
  GeofenceAlertExtended
} from '../types';
import {
  mockGeofenceZones,
  mockGeofenceAlerts,
  getMockZoneById,
  getMockAlertsByVehicle,
  getMockUnacknowledgedAlerts,
  getMockCriticalAlerts,
} from './mocks/geofencingMocks';

import { USE_MOCK } from './mockMode';
const MOCK_DELAY = 300;
const delay = (ms: number) => new Promise(resolve => setTimeout(resolve, ms));

// Real-mode adapters: the /api/v1/geofencing router is NOT registered on the
// casing seam and returns a zone/alert shape that diverges from the component's
// GeofenceZoneExtended / GeofenceAlertExtended. Map backend keys -> the shape
// the panel reads, with safe defaults so nothing calls .length/.toFixed on
// undefined. Mock data already matches the TS types and is left untouched.
const severityToColor = (severity?: string): GeofenceZoneExtended['color'] => {
  if (severity === 'critical') return 'red';
  if (severity === 'warning') return 'yellow';
  return 'green';
};

const adaptZone = (z: any): GeofenceZoneExtended => {
  const center = z?.center
    ? {
        latitude: z.center.latitude ?? z.center.lat ?? 0,
        longitude: z.center.longitude ?? z.center.lng ?? 0,
        timestamp: z.center.timestamp ?? '',
      }
    : undefined;
  const trigger = z?.triggerOn;
  return {
    id: z?.id,
    name: z?.name,
    type: z?.type ?? z?.zoneType ?? 'circle',
    center,
    radius: z?.radius ?? z?.radiusMeters ?? 0,
    coordinates: z?.coordinates,
    color: z?.color ?? severityToColor(z?.severity),
    description: z?.description ?? '',
    vehiclesInside: z?.vehiclesInside ?? [],
    alertRules: z?.alertRules ?? {
      onEntry: trigger === 'entry' || trigger === 'both',
      onExit: trigger === 'exit' || trigger === 'both',
      notifyRoles: [],
    },
    isActive: z?.isActive ?? true,
    createdAt: z?.createdAt ?? '',
    updatedAt: z?.updatedAt ?? '',
  };
};

const adaptAlert = (a: any): GeofenceAlertExtended => ({
  id: a?.id,
  vehicleId: a?.vehicleId ?? '',
  vehicleNumber: a?.vehicleNumber ?? a?.vehicleId ?? '',
  driverName: a?.driverName,
  geofenceId: a?.geofenceId ?? a?.zoneId ?? '',
  geofenceName: a?.geofenceName ?? a?.zoneId ?? '',
  alertType: a?.alertType ?? a?.eventType ?? 'violation',
  location: a?.location,
  timestamp: a?.timestamp ?? a?.createdAt ?? '',
  acknowledged: a?.acknowledged ?? false,
  severity: a?.severity ?? 'info',
});

export const geofencingApi = {
  getZones: async (): Promise<GeofenceZoneExtended[]> => {
    if (USE_MOCK) {
      await delay(MOCK_DELAY);
      return mockGeofenceZones;
    }
    const response = await api.get<any[]>('/api/v1/geofencing/zones');
    return (response.data ?? []).map(adaptZone);
  },

  getZone: async (id: string): Promise<GeofenceZoneExtended | null> => {
    if (USE_MOCK) {
      await delay(MOCK_DELAY);
      return getMockZoneById(id) || null;
    }
    const response = await api.get<any>(`/api/v1/geofencing/zones/${id}`);
    return response.data ? adaptZone(response.data) : null;
  },

  createZone: async (zone: Partial<GeofenceZoneExtended>): Promise<GeofenceZoneExtended> => {
    if (USE_MOCK) {
      await delay(MOCK_DELAY);
      const newZone: GeofenceZoneExtended = {
        ...zone as GeofenceZoneExtended,
        id: `geofence-${Date.now()}`,
        vehiclesInside: [],
        isActive: true,
        createdAt: new Date().toISOString(),
        updatedAt: new Date().toISOString(),
      };
      return newZone;
    }
    const response = await api.post<any>('/api/v1/geofencing/zones', zone);
    return adaptZone(response.data);
  },

  updateZone: async (id: string, updates: Partial<GeofenceZoneExtended>): Promise<GeofenceZoneExtended> => {
    if (USE_MOCK) {
      await delay(MOCK_DELAY);
      const zone = getMockZoneById(id);
      if (!zone) throw new Error('Zone not found');
      return { ...zone, ...updates, updatedAt: new Date().toISOString() };
    }
    const response = await api.put<any>(`/api/v1/geofencing/zones/${id}`, updates);
    return adaptZone(response.data);
  },

  deleteZone: async (id: string): Promise<void> => {
    if (USE_MOCK) {
      await delay(MOCK_DELAY);
      return;
    }
    await api.delete(`/api/v1/geofencing/zones/${id}`);
  },

  getAlerts: async (): Promise<GeofenceAlertExtended[]> => {
    if (USE_MOCK) {
      await delay(MOCK_DELAY);
      return mockGeofenceAlerts;
    }
    const response = await api.get<any[]>('/api/v1/geofencing/alerts');
    return (response.data ?? []).map(adaptAlert);
  },

  getAlertsByVehicle: async (vehicleId: string): Promise<GeofenceAlertExtended[]> => {
    if (USE_MOCK) {
      await delay(MOCK_DELAY);
      return getMockAlertsByVehicle(vehicleId);
    }
    const response = await api.get<any[]>(`/api/v1/geofencing/alerts?vehicle_id=${vehicleId}`);
    return (response.data ?? []).map(adaptAlert);
  },

  getUnacknowledgedAlerts: async (): Promise<GeofenceAlertExtended[]> => {
    if (USE_MOCK) {
      await delay(MOCK_DELAY);
      return getMockUnacknowledgedAlerts();
    }
    const response = await api.get<any[]>('/api/v1/geofencing/alerts?acknowledged=false');
    return (response.data ?? []).map(adaptAlert);
  },

  getCriticalAlerts: async (): Promise<GeofenceAlertExtended[]> => {
    if (USE_MOCK) {
      await delay(MOCK_DELAY);
      return getMockCriticalAlerts();
    }
    const response = await api.get<any[]>('/api/v1/geofencing/alerts?severity=critical');
    return (response.data ?? []).map(adaptAlert);
  },

  acknowledgeAlert: async (alertId: string): Promise<void> => {
    if (USE_MOCK) {
      await delay(MOCK_DELAY);
      return;
    }
    await api.post(`/api/v1/geofencing/alerts/${alertId}/acknowledge`, {});
  },

  subscribeToAlerts: (onAlert: (alert: GeofenceAlertExtended) => void): (() => void) => {
    if (USE_MOCK) {
      const interval = setInterval(async () => {
        const alerts = await geofencingApi.getUnacknowledgedAlerts();
        if (Math.random() > 0.7 && alerts.length > 0) {
          const randomAlert = alerts[Math.floor(Math.random() * alerts.length)];
          onAlert({
            ...randomAlert,
            id: `${randomAlert.id}-new-${Date.now()}`,
            timestamp: new Date().toISOString(),
          });
        }
      }, 15000);
      return () => clearInterval(interval);
    }
    // Real mode: poll unacknowledged alerts. The previous code opened a raw
    // WebSocket to /ws/geofencing — a route that does not exist on the backend
    // (only /ws is registered), so the panel silently never received alerts
    // while the console error-looped. Polling delivers until geofence events
    // are published through the authenticated /ws stream.
    const seen = new Set<string>();
    let first = true;
    const interval = setInterval(async () => {
      try {
        const alerts = await geofencingApi.getUnacknowledgedAlerts();
        for (const alert of alerts) {
          if (!seen.has(alert.id)) {
            seen.add(alert.id);
            if (!first) onAlert(alert); // don't replay the backlog as "new"
          }
        }
        first = false;
      } catch (error) {
        console.error('Geofencing alert poll failed:', error);
      }
    }, 15000);
    return () => clearInterval(interval);
  },
};

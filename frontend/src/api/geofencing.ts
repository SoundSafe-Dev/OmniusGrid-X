import { api } from './client';
import type { 
  GeofenceZoneExtended, 
  GeofenceAlertExtended,
  GeoLocation 
} from '../types';
import {
  mockGeofenceZones,
  mockGeofenceAlerts,
  getMockZoneById,
  getMockAlertsByVehicle,
  getMockAlertsByZone,
  getMockUnacknowledgedAlerts,
  getMockCriticalAlerts,
} from './mocks/geofencingMocks';

import { USE_MOCK } from './mockMode';
const MOCK_DELAY = 300;
const delay = (ms: number) => new Promise(resolve => setTimeout(resolve, ms));

export const geofencingApi = {
  getZones: async (): Promise<GeofenceZoneExtended[]> => {
    if (USE_MOCK) {
      await delay(MOCK_DELAY);
      return mockGeofenceZones;
    }
    const response = await api.get<GeofenceZoneExtended[]>('/api/v1/geofencing/zones');
    return response.data;
  },

  getZone: async (id: string): Promise<GeofenceZoneExtended | null> => {
    if (USE_MOCK) {
      await delay(MOCK_DELAY);
      return getMockZoneById(id) || null;
    }
    const response = await api.get<GeofenceZoneExtended>(`/api/v1/geofencing/zones/${id}`);
    return response.data;
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
    const response = await api.post<GeofenceZoneExtended>('/api/v1/geofencing/zones', zone);
    return response.data;
  },

  updateZone: async (id: string, updates: Partial<GeofenceZoneExtended>): Promise<GeofenceZoneExtended> => {
    if (USE_MOCK) {
      await delay(MOCK_DELAY);
      const zone = getMockZoneById(id);
      if (!zone) throw new Error('Zone not found');
      return { ...zone, ...updates, updatedAt: new Date().toISOString() };
    }
    const response = await api.patch<GeofenceZoneExtended>(`/api/v1/geofencing/zones/${id}`, updates);
    return response.data;
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
    const response = await api.get<GeofenceAlertExtended[]>('/api/v1/geofencing/alerts');
    return response.data;
  },

  getAlertsByVehicle: async (vehicleId: string): Promise<GeofenceAlertExtended[]> => {
    if (USE_MOCK) {
      await delay(MOCK_DELAY);
      return getMockAlertsByVehicle(vehicleId);
    }
    const response = await api.get<GeofenceAlertExtended[]>(`/api/v1/geofencing/alerts?vehicleId=${vehicleId}`);
    return response.data;
  },

  getUnacknowledgedAlerts: async (): Promise<GeofenceAlertExtended[]> => {
    if (USE_MOCK) {
      await delay(MOCK_DELAY);
      return getMockUnacknowledgedAlerts();
    }
    const response = await api.get<GeofenceAlertExtended[]>('/api/v1/geofencing/alerts?acknowledged=false');
    return response.data;
  },

  getCriticalAlerts: async (): Promise<GeofenceAlertExtended[]> => {
    if (USE_MOCK) {
      await delay(MOCK_DELAY);
      return getMockCriticalAlerts();
    }
    const response = await api.get<GeofenceAlertExtended[]>('/api/v1/geofencing/alerts?severity=critical');
    return response.data;
  },

  acknowledgeAlert: async (alertId: string): Promise<void> => {
    if (USE_MOCK) {
      await delay(MOCK_DELAY);
      return;
    }
    await api.patch(`/api/v1/geofencing/alerts/${alertId}`, { acknowledged: true });
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
    const wsUrl = `${import.meta.env.VITE_WS_URL || 'ws://localhost:8000'}/ws/geofencing`;
    const ws = new WebSocket(wsUrl);
    ws.onmessage = (event) => {
      try {
        const alert: GeofenceAlertExtended = JSON.parse(event.data);
        onAlert(alert);
      } catch (error) {
        console.error('Failed to parse WebSocket message:', error);
      }
    };
    ws.onerror = (error) => console.error('Geofencing WebSocket error:', error);
    return () => ws.close();
  },
};

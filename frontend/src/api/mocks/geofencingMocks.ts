import type {
  GeofenceZoneExtended,
  GeofenceAlertExtended
} from '../../types';

// Mock geofence zones
export const mockGeofenceZones: GeofenceZoneExtended[] = [
  {
    id: 'geofence-001',
    name: 'Chicago Distribution Hub',
    type: 'circle',
    center: { 
      latitude: 41.8781, 
      longitude: -87.6298, 
      timestamp: new Date().toISOString() 
    },
    radius: 5000,
    color: 'green',
    description: 'Main distribution center - Safe zone',
    vehiclesInside: ['vehicle-1'],
    alertRules: { onEntry: true, onExit: true, notifyRoles: ['dispatcher', 'manager'] },
    isActive: true,
    createdAt: new Date(Date.now() - 30 * 24 * 60 * 60 * 1000).toISOString(),
    updatedAt: new Date().toISOString(),
  },
  {
    id: 'geofence-002',
    name: 'LA Port - Restricted Area',
    type: 'circle',
    center: { 
      latitude: 34.0522, 
      longitude: -118.2437, 
      timestamp: new Date().toISOString() 
    },
    radius: 2000,
    color: 'red',
    description: 'High security zone - Authorization required',
    vehiclesInside: [],
    alertRules: { onEntry: true, onExit: false, notifyRoles: ['security', 'manager'] },
    isActive: true,
    createdAt: new Date(Date.now() - 60 * 24 * 60 * 60 * 1000).toISOString(),
    updatedAt: new Date().toISOString(),
  },
  {
    id: 'geofence-003',
    name: 'Denver Inspection Checkpoint',
    type: 'circle',
    center: { 
      latitude: 39.7392, 
      longitude: -104.9903, 
      timestamp: new Date().toISOString() 
    },
    radius: 3000,
    color: 'yellow',
    description: 'Mandatory inspection checkpoint',
    vehiclesInside: ['vehicle-2'],
    alertRules: { onEntry: true, onExit: true, notifyRoles: ['compliance'] },
    isActive: true,
    createdAt: new Date(Date.now() - 45 * 24 * 60 * 60 * 1000).toISOString(),
    updatedAt: new Date().toISOString(),
  },
  {
    id: 'geofence-004',
    name: 'Dallas Fuel Station Network',
    type: 'circle',
    center: { 
      latitude: 32.7767, 
      longitude: -96.7970, 
      timestamp: new Date().toISOString() 
    },
    radius: 8000,
    color: 'green',
    description: 'Preferred fuel station network',
    vehiclesInside: ['vehicle-3'],
    alertRules: { onEntry: false, onExit: false, notifyRoles: [] },
    isActive: true,
    createdAt: new Date(Date.now() - 20 * 24 * 60 * 60 * 1000).toISOString(),
    updatedAt: new Date().toISOString(),
  },
  {
    id: 'geofence-005',
    name: 'Phoenix Customer Site - Beta',
    type: 'circle',
    center: { 
      latitude: 33.4484, 
      longitude: -112.0740, 
      timestamp: new Date().toISOString() 
    },
    radius: 1500,
    color: 'yellow',
    description: 'VIP customer delivery zone',
    vehiclesInside: [],
    alertRules: { onEntry: true, onExit: true, notifyRoles: ['customer_service', 'manager'] },
    isActive: false,
    createdAt: new Date(Date.now() - 15 * 24 * 60 * 60 * 1000).toISOString(),
    updatedAt: new Date(Date.now() - 2 * 24 * 60 * 60 * 1000).toISOString(),
  },
];

// Mock geofence alerts
export const mockGeofenceAlerts: GeofenceAlertExtended[] = [
  {
    id: 'alert-001',
    vehicleId: 'vehicle-1',
    vehicleNumber: 'TRK-001',
    driverName: 'John Smith',
    geofenceId: 'geofence-001',
    geofenceName: 'Chicago Distribution Hub',
    alertType: 'entry',
    location: { 
      latitude: 41.8785, 
      longitude: -87.6300, 
      timestamp: new Date(Date.now() - 30 * 60000).toISOString() 
    },
    timestamp: new Date(Date.now() - 30 * 60000).toISOString(),
    acknowledged: true,
    severity: 'info',
  },
  {
    id: 'alert-002',
    vehicleId: 'vehicle-2',
    vehicleNumber: 'TRK-002',
    driverName: 'Sarah Johnson',
    geofenceId: 'geofence-003',
    geofenceName: 'Denver Inspection Checkpoint',
    alertType: 'entry',
    location: { 
      latitude: 39.7390, 
      longitude: -104.9900, 
      timestamp: new Date(Date.now() - 5 * 60000).toISOString() 
    },
    timestamp: new Date(Date.now() - 5 * 60000).toISOString(),
    acknowledged: false,
    severity: 'warning',
  },
  {
    id: 'alert-003',
    vehicleId: 'vehicle-3',
    vehicleNumber: 'TRK-003',
    driverName: 'Mike Davis',
    geofenceId: 'geofence-004',
    geofenceName: 'Dallas Fuel Station Network',
    alertType: 'exit',
    location: { 
      latitude: 32.7800, 
      longitude: -96.8000, 
      timestamp: new Date(Date.now() - 15 * 60000).toISOString() 
    },
    timestamp: new Date(Date.now() - 15 * 60000).toISOString(),
    acknowledged: false,
    severity: 'info',
  },
  {
    id: 'alert-004',
    vehicleId: 'vehicle-5',
    vehicleNumber: 'TRK-005',
    driverName: 'Robert Chen',
    geofenceId: 'geofence-002',
    geofenceName: 'LA Port - Restricted Area',
    alertType: 'violation',
    location: { 
      latitude: 34.0525, 
      longitude: -118.2440, 
      timestamp: new Date(Date.now() - 2 * 60000).toISOString() 
    },
    timestamp: new Date(Date.now() - 2 * 60000).toISOString(),
    acknowledged: false,
    severity: 'critical',
  },
  {
    id: 'alert-005',
    vehicleId: 'vehicle-4',
    vehicleNumber: 'TRK-004',
    driverName: 'Emily Wilson',
    geofenceId: 'geofence-001',
    geofenceName: 'Chicago Distribution Hub',
    alertType: 'exit',
    location: { 
      latitude: 41.8770, 
      longitude: -87.6280, 
      timestamp: new Date(Date.now() - 60 * 60000).toISOString() 
    },
    timestamp: new Date(Date.now() - 60 * 60000).toISOString(),
    acknowledged: true,
    severity: 'info',
  },
  {
    id: 'alert-006',
    vehicleId: 'vehicle-6',
    vehicleNumber: 'TRK-006',
    driverName: 'James Miller',
    geofenceId: 'geofence-003',
    geofenceName: 'Denver Inspection Checkpoint',
    alertType: 'violation',
    location: { 
      latitude: 39.7500, 
      longitude: -104.9850, 
      timestamp: new Date(Date.now() - 45 * 60000).toISOString() 
    },
    timestamp: new Date(Date.now() - 45 * 60000).toISOString(),
    acknowledged: false,
    severity: 'warning',
  },
  {
    id: 'alert-007',
    vehicleId: 'vehicle-2',
    vehicleNumber: 'TRK-002',
    driverName: 'Sarah Johnson',
    geofenceId: 'geofence-002',
    geofenceName: 'LA Port - Restricted Area',
    alertType: 'entry',
    location: { 
      latitude: 34.0518, 
      longitude: -118.2435, 
      timestamp: new Date(Date.now() - 3 * 60 * 60000).toISOString() 
    },
    timestamp: new Date(Date.now() - 3 * 60 * 60000).toISOString(),
    acknowledged: true,
    severity: 'warning',
  },
];

// Helper functions for geofencing
export const getMockZoneById = (id: string): GeofenceZoneExtended | undefined => {
  return mockGeofenceZones.find(z => z.id === id);
};

export const getMockAlertsByVehicle = (vehicleId: string): GeofenceAlertExtended[] => {
  return mockGeofenceAlerts.filter(a => a.vehicleId === vehicleId);
};

export const getMockAlertsByZone = (zoneId: string): GeofenceAlertExtended[] => {
  return mockGeofenceAlerts.filter(a => a.geofenceId === zoneId);
};

export const getMockUnacknowledgedAlerts = (): GeofenceAlertExtended[] => {
  return mockGeofenceAlerts.filter(a => !a.acknowledged);
};

export const getMockCriticalAlerts = (): GeofenceAlertExtended[] => {
  return mockGeofenceAlerts.filter(a => a.severity === 'critical' && !a.acknowledged);
};

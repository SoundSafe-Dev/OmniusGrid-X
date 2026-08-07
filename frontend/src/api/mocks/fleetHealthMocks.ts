import type { 
  VehicleHealthStatus, 
  DiagnosticTroubleCode, 
  SecurityEvent,
  DriverSafetyMetrics 
} from '../../types';

// Mock Diagnostic Trouble Codes
export const mockDTCs: DiagnosticTroubleCode[] = [
  {
    code: 'P0101',
    description: 'Mass Air Flow Sensor Circuit Range/Performance',
    severity: 'medium',
    system: 'engine',
    timestamp: new Date(Date.now() - 2 * 24 * 60 * 60 * 1000).toISOString(),
    cleared: false,
    vehicleId: 'vehicle-1',
    vehicleNumber: 'TRK-001',
  },
  {
    code: 'P0300',
    description: 'Random/Multiple Cylinder Misfire Detected',
    severity: 'high',
    system: 'engine',
    timestamp: new Date(Date.now() - 5 * 24 * 60 * 60 * 1000).toISOString(),
    cleared: false,
    vehicleId: 'vehicle-2',
    vehicleNumber: 'TRK-002',
  },
  {
    code: 'P0420',
    description: 'Catalyst System Efficiency Below Threshold',
    severity: 'medium',
    system: 'emissions',
    timestamp: new Date(Date.now() - 1 * 24 * 60 * 60 * 1000).toISOString(),
    cleared: false,
    vehicleId: 'vehicle-2',
    vehicleNumber: 'TRK-002',
  },
  {
    code: 'P0500',
    description: 'Vehicle Speed Sensor Malfunction',
    severity: 'low',
    system: 'safety',
    timestamp: new Date(Date.now() - 3 * 24 * 60 * 60 * 1000).toISOString(),
    cleared: true,
    vehicleId: 'vehicle-3',
    vehicleNumber: 'TRK-003',
  },
  {
    code: 'P0705',
    description: 'Transmission Range Sensor Circuit Malfunction',
    severity: 'critical',
    system: 'transmission',
    timestamp: new Date(Date.now() - 12 * 60 * 60 * 1000).toISOString(),
    cleared: false,
    vehicleId: 'vehicle-4',
    vehicleNumber: 'TRK-004',
  },
  {
    code: 'B1000',
    description: 'Airbag System Fault',
    severity: 'critical',
    system: 'safety',
    timestamp: new Date(Date.now() - 1 * 60 * 60 * 1000).toISOString(),
    cleared: false,
    vehicleId: 'vehicle-6',
    vehicleNumber: 'TRK-006',
  },
];

// Mock Vehicle Health Status
export const mockVehicleHealthStatuses: VehicleHealthStatus[] = [
  {
    vehicleId: 'vehicle-1',
    vehicleNumber: 'TRK-001',
    driverId: 'driver-1',
    driverName: 'John Smith',
    status: 'online',
    lastCommunication: new Date(Date.now() - 2 * 60 * 1000).toISOString(),
    dtcs: mockDTCs.filter(d => d.vehicleId === 'vehicle-1' && !d.cleared),
    safetyScore: 92,
    securityStatus: 'secure',
    engineHours: 3425,
    odometer: 128500,
    fuelLevel: 78,
  },
  {
    vehicleId: 'vehicle-2',
    vehicleNumber: 'TRK-002',
    driverId: 'driver-2',
    driverName: 'Sarah Johnson',
    status: 'warning',
    lastCommunication: new Date(Date.now() - 1 * 60 * 1000).toISOString(),
    dtcs: mockDTCs.filter(d => d.vehicleId === 'vehicle-2' && !d.cleared),
    safetyScore: 78,
    securityStatus: 'warning',
    engineHours: 5120,
    odometer: 185300,
    fuelLevel: 45,
  },
  {
    vehicleId: 'vehicle-3',
    vehicleNumber: 'TRK-003',
    driverId: 'driver-3',
    driverName: 'Mike Davis',
    status: 'online',
    lastCommunication: new Date(Date.now() - 5 * 60 * 1000).toISOString(),
    dtcs: mockDTCs.filter(d => d.vehicleId === 'vehicle-3' && !d.cleared),
    safetyScore: 88,
    securityStatus: 'secure',
    engineHours: 2890,
    odometer: 98700,
    fuelLevel: 92,
  },
  {
    vehicleId: 'vehicle-4',
    vehicleNumber: 'TRK-004',
    driverId: 'driver-4',
    driverName: 'Emily Wilson',
    status: 'maintenance',
    lastCommunication: new Date(Date.now() - 3 * 60 * 60 * 1000).toISOString(),
    dtcs: mockDTCs.filter(d => d.vehicleId === 'vehicle-4' && !d.cleared),
    safetyScore: 85,
    securityStatus: 'secure',
    engineHours: 4280,
    odometer: 156400,
    fuelLevel: 23,
  },
  {
    vehicleId: 'vehicle-5',
    vehicleNumber: 'TRK-005',
    driverId: 'driver-5',
    driverName: 'Robert Chen',
    status: 'online',
    lastCommunication: new Date(Date.now() - 30 * 1000).toISOString(),
    dtcs: [],
    safetyScore: 95,
    securityStatus: 'secure',
    engineHours: 2150,
    odometer: 76200,
    fuelLevel: 67,
  },
  {
    vehicleId: 'vehicle-6',
    vehicleNumber: 'TRK-006',
    driverId: 'driver-6',
    driverName: 'James Miller',
    status: 'offline',
    lastCommunication: new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString(),
    dtcs: mockDTCs.filter(d => d.vehicleId === 'vehicle-6' && !d.cleared),
    safetyScore: 65,
    securityStatus: 'alert',
    engineHours: 6250,
    odometer: 212800,
    fuelLevel: 12,
  },
];

// Mock Security Events
export const mockSecurityEvents: SecurityEvent[] = [
  {
    id: 'sec-001',
    vehicleId: 'vehicle-6',
    vehicleNumber: 'TRK-006',
    eventType: 'unauthorized_access',
    timestamp: new Date(Date.now() - 6 * 60 * 60 * 1000).toISOString(),
    severity: 'high',
    location: { 
      latitude: 34.0522, 
      longitude: -118.2437, 
      timestamp: new Date().toISOString() 
    },
    description: 'Unauthorized access attempt detected - Vehicle door opened without valid key fob',
    acknowledged: false,
    driverName: 'James Miller',
  },
  {
    id: 'sec-002',
    vehicleId: 'vehicle-6',
    vehicleNumber: 'TRK-006',
    eventType: 'device_tampering',
    timestamp: new Date(Date.now() - 22 * 60 * 60 * 1000).toISOString(),
    severity: 'critical',
    description: 'GeoTab device connectivity lost unexpectedly - Possible tampering detected',
    acknowledged: false,
    driverName: 'James Miller',
  },
  {
    id: 'sec-003',
    vehicleId: 'vehicle-2',
    vehicleNumber: 'TRK-002',
    eventType: 'after_hours_use',
    timestamp: new Date(Date.now() - 1 * 24 * 60 * 60 * 1000).toISOString(),
    severity: 'medium',
    location: { 
      latitude: 39.7392, 
      longitude: -104.9903, 
      timestamp: new Date().toISOString() 
    },
    description: 'Vehicle operated outside authorized hours (11:45 PM - 2:30 AM)',
    acknowledged: true,
    driverName: 'Sarah Johnson',
  },
  {
    id: 'sec-004',
    vehicleId: 'vehicle-5',
    vehicleNumber: 'TRK-005',
    eventType: 'unusual_route',
    timestamp: new Date(Date.now() - 3 * 24 * 60 * 60 * 1000).toISOString(),
    severity: 'low',
    description: 'Vehicle deviated 45 miles from planned route without authorization',
    acknowledged: true,
    driverName: 'Robert Chen',
  },
  {
    id: 'sec-005',
    vehicleId: 'vehicle-6',
    vehicleNumber: 'TRK-006',
    eventType: 'geofence_violation',
    timestamp: new Date(Date.now() - 2 * 60 * 60 * 1000).toISOString(),
    severity: 'high',
    location: { 
      latitude: 34.0525, 
      longitude: -118.2440, 
      timestamp: new Date().toISOString() 
    },
    description: 'Vehicle entered restricted zone without proper clearance',
    acknowledged: false,
    driverName: 'James Miller',
  },
];

// Mock Driver Safety Metrics
export const mockDriverSafetyMetrics: DriverSafetyMetrics[] = [
  {
    driverId: 'driver-1',
    driverName: 'John Smith',
    overallScore: 92,
    harshBrakingEvents: 2,
    harshAccelerationEvents: 1,
    speedingEvents: 0,
    idleTimeHours: 12.5,
    seatbeltViolations: 0,
    period: '30d',
    trend: 'improving',
  },
  {
    driverId: 'driver-2',
    driverName: 'Sarah Johnson',
    overallScore: 78,
    harshBrakingEvents: 8,
    harshAccelerationEvents: 5,
    speedingEvents: 3,
    idleTimeHours: 24.2,
    seatbeltViolations: 1,
    period: '30d',
    trend: 'worsening',
  },
  {
    driverId: 'driver-3',
    driverName: 'Mike Davis',
    overallScore: 88,
    harshBrakingEvents: 4,
    harshAccelerationEvents: 2,
    speedingEvents: 1,
    idleTimeHours: 18.3,
    seatbeltViolations: 0,
    period: '30d',
    trend: 'stable',
  },
  {
    driverId: 'driver-4',
    driverName: 'Emily Wilson',
    overallScore: 85,
    harshBrakingEvents: 5,
    harshAccelerationEvents: 3,
    speedingEvents: 2,
    idleTimeHours: 15.7,
    seatbeltViolations: 0,
    period: '30d',
    trend: 'stable',
  },
  {
    driverId: 'driver-5',
    driverName: 'Robert Chen',
    overallScore: 95,
    harshBrakingEvents: 1,
    harshAccelerationEvents: 0,
    speedingEvents: 0,
    idleTimeHours: 8.9,
    seatbeltViolations: 0,
    period: '30d',
    trend: 'improving',
  },
  {
    driverId: 'driver-6',
    driverName: 'James Miller',
    overallScore: 65,
    harshBrakingEvents: 15,
    harshAccelerationEvents: 12,
    speedingEvents: 8,
    idleTimeHours: 32.4,
    seatbeltViolations: 2,
    period: '30d',
    trend: 'worsening',
  },
];

// Helper functions
export const getMockVehicleHealthById = (id: string): VehicleHealthStatus | undefined => {
  return mockVehicleHealthStatuses.find(v => v.vehicleId === id);
};

export const getMockDTCsByVehicle = (vehicleId: string): DiagnosticTroubleCode[] => {
  return mockDTCs.filter(d => d.vehicleId === vehicleId && !d.cleared);
};

export const getMockSecurityEventsByVehicle = (vehicleId: string): SecurityEvent[] => {
  return mockSecurityEvents.filter(e => e.vehicleId === vehicleId);
};

export const getMockUnacknowledgedSecurityEvents = (): SecurityEvent[] => {
  return mockSecurityEvents.filter(e => !e.acknowledged);
};

export const getMockCriticalSecurityEvents = (): SecurityEvent[] => {
  return mockSecurityEvents.filter(e => e.severity === 'critical' && !e.acknowledged);
};

export const getMockDriverSafetyById = (id: string): DriverSafetyMetrics | undefined => {
  return mockDriverSafetyMetrics.find(d => d.driverId === id);
};

// Statistics helpers
export const getHealthStatistics = () => {
  const total = mockVehicleHealthStatuses.length;
  const online = mockVehicleHealthStatuses.filter(v => v.status === 'online').length;
  const offline = mockVehicleHealthStatuses.filter(v => v.status === 'offline').length;
  const maintenance = mockVehicleHealthStatuses.filter(v => v.status === 'maintenance').length;
  const warning = mockVehicleHealthStatuses.filter(v => v.status === 'warning').length;
  const avgSafetyScore = Math.round(
    mockVehicleHealthStatuses.reduce((sum, v) => sum + v.safetyScore, 0) / total
  );
  const totalActiveDTCs = mockDTCs.filter(d => !d.cleared).length;
  const criticalDTCs = mockDTCs.filter(d => !d.cleared && d.severity === 'critical').length;
  
  return {
    total,
    online,
    offline,
    maintenance,
    warning,
    avgSafetyScore,
    totalActiveDTCs,
    criticalDTCs,
  };
};

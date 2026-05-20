import { api } from './client';
import { 
  YardTrailer, 
  DockDoor, 
  DockAppointment, 
  YardMove, 
  DriverWaitTime,
  TrailerFilters,
  AppointmentFilters,
  LogisticsOverview,
  DetentionAlert,
  PaginatedResponse,
  GeoLocation
} from '../types';
import { USE_MOCK } from './mockMode';

const MOCK_DELAY = 500;

const delay = (ms: number) => new Promise(resolve => setTimeout(resolve, ms));

// Mock Data
const mockTrailers: YardTrailer[] = [
  {
    id: 'trailer-1',
    trailerId: 'TR-2024-001',
    licensePlate: 'ABC-1234',
    carrierId: 'carrier-1',
    carrierName: 'Swift Transportation',
    trailerType: 'dry_van',
    status: 'docked',
    yardLocation: 'DOCK-A1',
    assignedDoorId: 'door-1',
    checkedInAt: new Date(Date.now() - 2 * 3600000).toISOString(),
    detentionRisk: 'low',
    detentionCost: 0,
    contents: 'Electronics - Batch #4521',
    poNumber: 'PO-78234',
    sealNumber: 'SL-998877',
    driverName: 'John Smith',
    driverPhone: '+1-555-0101',
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
  },
  {
    id: 'trailer-2',
    trailerId: 'TR-2024-002',
    licensePlate: 'XYZ-5678',
    carrierId: 'carrier-2',
    carrierName: 'Schneider National',
    trailerType: 'reefer',
    status: 'yard',
    yardLocation: 'ZONE-B-12',
    checkedInAt: new Date(Date.now() - 4 * 3600000).toISOString(),
    expectedDuration: 180,
    detentionRisk: 'medium',
    detentionCost: 75,
    contents: 'Frozen Foods - Temperature Sensitive',
    poNumber: 'PO-78235',
    sealNumber: 'SL-998878',
    driverName: 'Maria Garcia',
    driverPhone: '+1-555-0102',
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
  },
  {
    id: 'trailer-3',
    trailerId: 'TR-2024-003',
    licensePlate: 'DEF-9012',
    carrierId: 'carrier-3',
    carrierName: 'JB Hunt',
    trailerType: 'flatbed',
    status: 'in_transit',
    checkedInAt: new Date(Date.now() - 1 * 3600000).toISOString(),
    detentionRisk: 'low',
    detentionCost: 0,
    contents: 'Steel Components',
    poNumber: 'PO-78236',
    lastLocation: {
      latitude: 40.7128,
      longitude: -74.0060,
      speed: 55,
      timestamp: new Date().toISOString(),
    },
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
  },
  {
    id: 'trailer-4',
    trailerId: 'TR-2024-004',
    licensePlate: 'GHI-3456',
    carrierId: 'carrier-1',
    carrierName: 'Swift Transportation',
    trailerType: 'dry_van',
    status: 'yard',
    yardLocation: 'ZONE-A-05',
    checkedInAt: new Date(Date.now() - 6 * 3600000).toISOString(),
    expectedDuration: 240,
    detentionRisk: 'high',
    detentionCost: 450,
    contents: 'Automotive Parts',
    poNumber: 'PO-78237',
    sealNumber: 'SL-998879',
    driverName: 'Robert Johnson',
    driverPhone: '+1-555-0103',
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
  },
];

const mockDockDoors: DockDoor[] = [
  {
    id: 'door-1',
    doorNumber: 'DOCK-A1',
    workcellId: 'workcell-1',
    workcellName: 'Assembly Line A',
    status: 'occupied',
    currentTrailerId: 'trailer-1',
    trailerLicensePlate: 'ABC-1234',
    supportedEquipment: ['forklift', 'pallet_jack', 'conveyor'],
    hasLoadingEquipment: true,
    maxWeightCapacity: 45000,
    currentAppointmentId: 'appt-1',
    estimatedReleaseAt: new Date(Date.now() + 1 * 3600000).toISOString(),
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
  },
  {
    id: 'door-2',
    doorNumber: 'DOCK-A2',
    workcellId: 'workcell-1',
    workcellName: 'Assembly Line A',
    status: 'available',
    supportedEquipment: ['forklift', 'pallet_jack'],
    hasLoadingEquipment: true,
    maxWeightCapacity: 45000,
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
  },
  {
    id: 'door-3',
    doorNumber: 'DOCK-B1',
    workcellId: 'workcell-2',
    workcellName: 'Assembly Line B',
    status: 'reserved',
    supportedEquipment: ['forklift', 'crane'],
    hasLoadingEquipment: true,
    maxWeightCapacity: 60000,
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
  },
  {
    id: 'door-4',
    doorNumber: 'DOCK-B2',
    workcellId: 'workcell-2',
    workcellName: 'Assembly Line B',
    status: 'maintenance',
    supportedEquipment: ['forklift'],
    hasLoadingEquipment: false,
    maxWeightCapacity: 45000,
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
  },
];

const mockAppointments: DockAppointment[] = [
  {
    id: 'appt-1',
    carrierId: 'carrier-1',
    carrierName: 'Swift Transportation',
    trailerId: 'trailer-1',
    trailerLicensePlate: 'ABC-1234',
    doorId: 'door-1',
    doorNumber: 'DOCK-A1',
    workcellId: 'workcell-1',
    workcellName: 'Assembly Line A',
    appointmentType: 'delivery',
    scheduledArrival: new Date(Date.now() - 2 * 3600000).toISOString(),
    actualArrival: new Date(Date.now() - 2 * 3600000).toISOString(),
    scheduledDeparture: new Date(Date.now() + 2 * 3600000).toISOString(),
    status: 'docked',
    poNumber: 'PO-78234',
    loadDescription: 'Electronics - Batch #4521',
    priority: 'normal',
    driverName: 'John Smith',
    driverPhone: '+1-555-0101',
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
  },
  {
    id: 'appt-2',
    carrierId: 'carrier-2',
    carrierName: 'Schneider National',
    trailerId: 'trailer-2',
    trailerLicensePlate: 'XYZ-5678',
    workcellId: 'workcell-2',
    workcellName: 'Assembly Line B',
    appointmentType: 'pickup',
    scheduledArrival: new Date(Date.now() + 1 * 3600000).toISOString(),
    scheduledDeparture: new Date(Date.now() + 3 * 3600000).toISOString(),
    status: 'scheduled',
    poNumber: 'PO-78235',
    loadDescription: 'Frozen Foods - Temperature Sensitive',
    priority: 'high',
    driverName: 'Maria Garcia',
    driverPhone: '+1-555-0102',
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
  },
];

const mockYardMoves: YardMove[] = [
  {
    id: 'move-1',
    trailerId: 'trailer-1',
    trailerLicensePlate: 'ABC-1234',
    fromLocation: 'GATE-IN',
    toLocation: 'DOCK-A1',
    moveType: 'dock',
    performedBy: 'Yard Jockey - Mike Wilson',
    equipmentUsed: 'Yard Truck #3',
    startTime: new Date(Date.now() - 2 * 3600000).toISOString(),
    endTime: new Date(Date.now() - 1.9 * 3600000).toISOString(),
    status: 'completed',
    createdAt: new Date().toISOString(),
  },
  {
    id: 'move-2',
    trailerId: 'trailer-2',
    trailerLicensePlate: 'XYZ-5678',
    fromLocation: 'GATE-IN',
    toLocation: 'ZONE-B-12',
    moveType: 'check_in',
    performedBy: 'Yard Jockey - Sarah Lee',
    equipmentUsed: 'Yard Truck #2',
    startTime: new Date(Date.now() - 4 * 3600000).toISOString(),
    endTime: new Date(Date.now() - 3.9 * 3600000).toISOString(),
    status: 'completed',
    createdAt: new Date().toISOString(),
  },
];

const mockDriverWaitTimes: DriverWaitTime[] = [
  {
    id: 'wait-1',
    driverId: 'driver-1',
    driverName: 'John Smith',
    carrierId: 'carrier-1',
    carrierName: 'Swift Transportation',
    trailerId: 'trailer-1',
    appointmentId: 'appt-1',
    checkInTime: new Date(Date.now() - 2 * 3600000).toISOString(),
    dockTime: new Date(Date.now() - 1.8 * 3600000).toISOString(),
    waitDurationMinutes: 12,
    dockDurationMinutes: 60,
    totalDurationMinutes: 72,
    isDetention: false,
    createdAt: new Date().toISOString(),
  },
  {
    id: 'wait-2',
    driverId: 'driver-2',
    driverName: 'Maria Garcia',
    carrierId: 'carrier-2',
    carrierName: 'Schneider National',
    trailerId: 'trailer-2',
    checkInTime: new Date(Date.now() - 4 * 3600000).toISOString(),
    waitDurationMinutes: 240,
    isDetention: true,
    detentionCost: 75,
    reason: 'No dock available - waiting for slot',
    createdAt: new Date().toISOString(),
  },
];

// YMS API
export const yardApi = {
  // Trailers
  getTrailers: async (filters?: TrailerFilters): Promise<PaginatedResponse<YardTrailer>> => {
    if (USE_MOCK) {
      await delay(MOCK_DELAY);
      let filtered = [...mockTrailers];
      if (filters?.status) filtered = filtered.filter(t => t.status === filters.status);
      if (filters?.carrierId) filtered = filtered.filter(t => t.carrierId === filters.carrierId);
      if (filters?.trailerType) filtered = filtered.filter(t => t.trailerType === filters.trailerType);
      if (filters?.detentionRisk) filtered = filtered.filter(t => t.detentionRisk === filters.detentionRisk);
      return {
        items: filtered,
        total: filtered.length,
        skip: 0,
        limit: filtered.length,
        hasMore: false,
      };
    }
    const response = await api.get<YardTrailer[]>('/api/v1/yard/trailers', { params: filters });
    return {
      items: response.data,
      total: response.data.length,
      skip: 0,
      limit: response.data.length,
      hasMore: false,
    };
  },

  getTrailer: async (id: string): Promise<YardTrailer> => {
    if (USE_MOCK) {
      await delay(MOCK_DELAY);
      const trailer = mockTrailers.find(t => t.id === id);
      if (!trailer) throw new Error('Trailer not found');
      return trailer;
    }
    const response = await api.get<YardTrailer>(`/api/v1/yard/trailers/${id}`);
    return response.data;
  },

  checkInTrailer: async (data: Partial<YardTrailer>): Promise<YardTrailer> => {
    if (USE_MOCK) {
      await delay(MOCK_DELAY);
      const newTrailer: YardTrailer = {
        ...data as YardTrailer,
        id: `trailer-${Date.now()}`,
        status: 'yard',
        checkedInAt: new Date().toISOString(),
        detentionRisk: 'low',
        detentionCost: 0,
        createdAt: new Date().toISOString(),
        updatedAt: new Date().toISOString(),
      };
      mockTrailers.push(newTrailer);
      return newTrailer;
    }
    const response = await api.post<YardTrailer>('/api/v1/yard/trailers/checkin', data);
    return response.data;
  },

  checkOutTrailer: async (id: string): Promise<YardTrailer> => {
    if (USE_MOCK) {
      await delay(MOCK_DELAY);
      const trailer = mockTrailers.find(t => t.id === id);
      if (!trailer) throw new Error('Trailer not found');
      trailer.status = 'outbound';
      trailer.checkedOutAt = new Date().toISOString();
      trailer.updatedAt = new Date().toISOString();
      return trailer;
    }
    const response = await api.post<YardTrailer>(`/api/v1/yard/trailers/${id}/checkout`);
    return response.data;
  },

  assignToDoor: async (trailerId: string, doorId: string): Promise<YardTrailer> => {
    if (USE_MOCK) {
      await delay(MOCK_DELAY);
      const trailer = mockTrailers.find(t => t.id === trailerId);
      const door = mockDockDoors.find(d => d.id === doorId);
      if (!trailer) throw new Error('Trailer not found');
      if (!door) throw new Error('Door not found');
      trailer.assignedDoorId = doorId;
      trailer.yardLocation = door.doorNumber;
      trailer.status = 'docked';
      trailer.updatedAt = new Date().toISOString();
      door.status = 'occupied';
      door.currentTrailerId = trailerId;
      door.trailerLicensePlate = trailer.licensePlate;
      door.updatedAt = new Date().toISOString();
      return trailer;
    }
    const response = await api.post<YardTrailer>(`/api/v1/yard/dock/doors/${doorId}/assign/${trailerId}`);
    return response.data;
  },

  // Dock Doors
  getDockDoors: async (workcellId?: string): Promise<DockDoor[]> => {
    if (USE_MOCK) {
      await delay(MOCK_DELAY);
      if (workcellId) {
        return mockDockDoors.filter(d => d.workcellId === workcellId);
      }
      return mockDockDoors;
    }
    const response = await api.get<DockDoor[]>('/api/v1/yard/dock/doors', { params: { workcell_id: workcellId } });
    return response.data;
  },

  // Appointments
  getAppointments: async (filters?: AppointmentFilters): Promise<PaginatedResponse<DockAppointment>> => {
    if (USE_MOCK) {
      await delay(MOCK_DELAY);
      let filtered = [...mockAppointments];
      if (filters?.status) filtered = filtered.filter(a => a.status === filters.status);
      if (filters?.workcellId) filtered = filtered.filter(a => a.workcellId === filters.workcellId);
      if (filters?.carrierId) filtered = filtered.filter(a => a.carrierId === filters.carrierId);
      if (filters?.priority) filtered = filtered.filter(a => a.priority === filters.priority);
      return {
        items: filtered,
        total: filtered.length,
        skip: 0,
        limit: filtered.length,
        hasMore: false,
      };
    }
    const response = await api.get<DockAppointment[]>('/api/v1/yard/dock/appointments', { params: filters });
    return {
      items: response.data,
      total: response.data.length,
      skip: 0,
      limit: response.data.length,
      hasMore: false,
    };
  },

  createAppointment: async (data: Partial<DockAppointment>): Promise<DockAppointment> => {
    if (USE_MOCK) {
      await delay(MOCK_DELAY);
      const newAppt: DockAppointment = {
        ...data as DockAppointment,
        id: `appt-${Date.now()}`,
        status: 'scheduled',
        createdAt: new Date().toISOString(),
        updatedAt: new Date().toISOString(),
      };
      mockAppointments.push(newAppt);
      return newAppt;
    }
    const response = await api.post<DockAppointment>('/api/v1/yard/dock/appointments', data);
    return response.data;
  },

  // Yard Moves
  getYardMoves: async (trailerId?: string): Promise<YardMove[]> => {
    if (USE_MOCK) {
      await delay(MOCK_DELAY);
      if (trailerId) {
        return mockYardMoves.filter(m => m.trailerId === trailerId);
      }
      return mockYardMoves;
    }
    const response = await api.get<YardMove[]>('/api/v1/yard/moves', { params: { trailer_id: trailerId } });
    return response.data;
  },

  recordMove: async (data: Partial<YardMove>): Promise<YardMove> => {
    if (USE_MOCK) {
      await delay(MOCK_DELAY);
      const newMove: YardMove = {
        ...data as YardMove,
        id: `move-${Date.now()}`,
        startTime: new Date().toISOString(),
        status: 'in_progress',
        createdAt: new Date().toISOString(),
      };
      mockYardMoves.push(newMove);
      return newMove;
    }
    const response = await api.post<YardMove>('/api/v1/yard/moves', data);
    return response.data;
  },

  // Analytics
  getDwellTimes: async (): Promise<{ avgDwellTime: number; maxDwellTime: number; trailersExceedingTarget: number }> => {
    if (USE_MOCK) {
      await delay(MOCK_DELAY);
      return {
        avgDwellTime: 180,
        maxDwellTime: 420,
        trailersExceedingTarget: 2,
      };
    }
    const response = await api.get('/api/v1/yard/dwell-times');
    return response.data;
  },

  getDetentionAlerts: async (): Promise<DetentionAlert[]> => {
    if (USE_MOCK) {
      await delay(MOCK_DELAY);
      return [
        {
          id: 'alert-1',
          trailerId: 'trailer-4',
          trailerLicensePlate: 'GHI-3456',
          driverName: 'Robert Johnson',
          carrierName: 'Swift Transportation',
          location: 'ZONE-A-05',
          checkInTime: new Date(Date.now() - 6 * 3600000).toISOString(),
          currentDurationMinutes: 360,
          freeTimeMinutes: 120,
          excessMinutes: 240,
          estimatedCost: 450,
          severity: 'high',
        },
      ];
    }
    const response = await api.get<DetentionAlert[]>('/api/v1/yard/detention-alerts');
    return response.data;
  },
};

// GeoTab Integration for Yard
export const geoTabYardApi = {
  // Get real-time trailer location from GeoTab device
  getTrailerLocation: async (deviceId: string): Promise<GeoLocation> => {
    if (USE_MOCK) {
      await delay(MOCK_DELAY);
      return {
        latitude: 40.7128 + (Math.random() - 0.5) * 0.01,
        longitude: -74.0060 + (Math.random() - 0.5) * 0.01,
        speed: Math.random() * 60,
        timestamp: new Date().toISOString(),
      };
    }
    const response = await api.get<GeoLocation>(`/api/v1/geotab/devices/${deviceId}/location`);
    return response.data;
  },

  // Get trailer trip history
  getTrailerTrips: async (deviceId: string, from: string, to: string): Promise<any[]> => {
    if (USE_MOCK) {
      await delay(MOCK_DELAY);
      return [];
    }
    const response = await api.get(`/api/v1/geotab/devices/${deviceId}/trips`, { params: { from, to } });
    return response.data;
  },
};

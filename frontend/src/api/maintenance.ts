import { api } from './client';
import type { 
  MaintenanceSchedule, 
  RepairOrder, 
  ServiceHistoryEntry,
  MaintenanceCosts 
} from '../types';
import {
  mockMaintenanceSchedules,
  mockRepairOrders,
  mockServiceHistory,
  mockMaintenanceCosts,
  getMockScheduleById,
  getMockScheduleByVehicle,
  getMockOverdueMaintenance,
  getMockUpcomingMaintenance,
  getMockRepairOrderById,
  getMockRepairOrdersByVehicle,
  getMockActiveRepairOrders,
  getMockServiceHistoryByVehicle,
  getMaintenanceStatistics,
} from './mocks/maintenanceMocks';

import { USE_MOCK } from './mockMode';
const MOCK_DELAY = 300;
const delay = (ms: number) => new Promise(resolve => setTimeout(resolve, ms));

export const maintenanceApi = {
  getSchedules: async (): Promise<MaintenanceSchedule[]> => {
    if (USE_MOCK) {
      await delay(MOCK_DELAY);
      return mockMaintenanceSchedules;
    }
    const response = await api.get<MaintenanceSchedule[]>('/api/v1/maintenance/schedules');
    return response.data;
  },

  getScheduleById: async (id: string): Promise<MaintenanceSchedule | null> => {
    if (USE_MOCK) {
      await delay(MOCK_DELAY);
      return getMockScheduleById(id) || null;
    }
    const response = await api.get<MaintenanceSchedule>(`/api/v1/maintenance/schedules/${id}`);
    return response.data;
  },

  getSchedulesByVehicle: async (vehicleId: string): Promise<MaintenanceSchedule[]> => {
    if (USE_MOCK) {
      await delay(MOCK_DELAY);
      return getMockScheduleByVehicle(vehicleId);
    }
    const response = await api.get<MaintenanceSchedule[]>(`/api/v1/maintenance/vehicles/${vehicleId}/schedules`);
    return response.data;
  },

  createSchedule: async (schedule: Partial<MaintenanceSchedule>): Promise<MaintenanceSchedule> => {
    if (USE_MOCK) {
      await delay(MOCK_DELAY);
      const newSchedule: MaintenanceSchedule = {
        ...schedule as MaintenanceSchedule,
        id: `maint-${Date.now()}`,
        status: 'scheduled',
      };
      return newSchedule;
    }
    const response = await api.post<MaintenanceSchedule>('/api/v1/maintenance/schedules', schedule);
    return response.data;
  },

  updateSchedule: async (id: string, updates: Partial<MaintenanceSchedule>): Promise<MaintenanceSchedule> => {
    if (USE_MOCK) {
      await delay(MOCK_DELAY);
      const schedule = getMockScheduleById(id);
      if (!schedule) throw new Error('Schedule not found');
      return { ...schedule, ...updates };
    }
    const response = await api.patch<MaintenanceSchedule>(`/api/v1/maintenance/schedules/${id}`, updates);
    return response.data;
  },

  getOverdueMaintenance: async (): Promise<MaintenanceSchedule[]> => {
    if (USE_MOCK) {
      await delay(MOCK_DELAY);
      return getMockOverdueMaintenance();
    }
    const response = await api.get<MaintenanceSchedule[]>('/api/v1/maintenance/schedules?status=overdue');
    return response.data;
  },

  getUpcomingMaintenance: async (days: number = 30): Promise<MaintenanceSchedule[]> => {
    if (USE_MOCK) {
      await delay(MOCK_DELAY);
      return getMockUpcomingMaintenance(days);
    }
    const response = await api.get<MaintenanceSchedule[]>(`/api/v1/maintenance/schedules?upcoming=${days}`);
    return response.data;
  },

  getRepairOrders: async (): Promise<RepairOrder[]> => {
    if (USE_MOCK) {
      await delay(MOCK_DELAY);
      return mockRepairOrders;
    }
    const response = await api.get<RepairOrder[]>('/api/v1/maintenance/repair-orders');
    return response.data;
  },

  getRepairOrderById: async (id: string): Promise<RepairOrder | null> => {
    if (USE_MOCK) {
      await delay(MOCK_DELAY);
      return getMockRepairOrderById(id) || null;
    }
    const response = await api.get<RepairOrder>(`/api/v1/maintenance/repair-orders/${id}`);
    return response.data;
  },

  getRepairOrdersByVehicle: async (vehicleId: string): Promise<RepairOrder[]> => {
    if (USE_MOCK) {
      await delay(MOCK_DELAY);
      return getMockRepairOrdersByVehicle(vehicleId);
    }
    const response = await api.get<RepairOrder[]>(`/api/v1/maintenance/vehicles/${vehicleId}/repair-orders`);
    return response.data;
  },

  getActiveRepairOrders: async (): Promise<RepairOrder[]> => {
    if (USE_MOCK) {
      await delay(MOCK_DELAY);
      return getMockActiveRepairOrders();
    }
    const response = await api.get<RepairOrder[]>('/api/v1/maintenance/repair-orders?status=active');
    return response.data;
  },

  createRepairOrder: async (order: Partial<RepairOrder>): Promise<RepairOrder> => {
    if (USE_MOCK) {
      await delay(MOCK_DELAY);
      const newOrder: RepairOrder = {
        ...order as RepairOrder,
        id: `ro-${Date.now()}`,
        workOrderNumber: `WO-${new Date().getFullYear()}-${Math.floor(Math.random() * 9000 + 1000)}`,
        status: 'reported',
        partsUsed: [],
        reportedDate: new Date().toISOString(),
      };
      return newOrder;
    }
    const response = await api.post<RepairOrder>('/api/v1/maintenance/repair-orders', order);
    return response.data;
  },

  updateRepairOrder: async (id: string, updates: Partial<RepairOrder>): Promise<RepairOrder> => {
    if (USE_MOCK) {
      await delay(MOCK_DELAY);
      const order = getMockRepairOrderById(id);
      if (!order) throw new Error('Repair order not found');
      return { ...order, ...updates };
    }
    const response = await api.patch<RepairOrder>(`/api/v1/maintenance/repair-orders/${id}`, updates);
    return response.data;
  },

  getServiceHistory: async (vehicleId: string): Promise<ServiceHistoryEntry[]> => {
    if (USE_MOCK) {
      await delay(MOCK_DELAY);
      return getMockServiceHistoryByVehicle(vehicleId);
    }
    const response = await api.get<ServiceHistoryEntry[]>(`/api/v1/maintenance/vehicles/${vehicleId}/history`);
    return response.data;
  },

  addServiceHistoryEntry: async (entry: Partial<ServiceHistoryEntry>): Promise<ServiceHistoryEntry> => {
    if (USE_MOCK) {
      await delay(MOCK_DELAY);
      const newEntry: ServiceHistoryEntry = {
        ...entry as ServiceHistoryEntry,
        id: `sh-${Date.now()}`,
      };
      return newEntry;
    }
    const response = await api.post<ServiceHistoryEntry>('/api/v1/maintenance/history', entry);
    return response.data;
  },

  getMaintenanceCosts: async (): Promise<MaintenanceCosts> => {
    if (USE_MOCK) {
      await delay(MOCK_DELAY);
      return mockMaintenanceCosts;
    }
    const response = await api.get<MaintenanceCosts>('/api/v1/maintenance/costs');
    return response.data;
  },

  getMaintenanceStatistics: async () => {
    if (USE_MOCK) {
      await delay(MOCK_DELAY);
      return getMaintenanceStatistics();
    }
    const response = await api.get('/api/v1/maintenance/statistics');
    return response.data;
  },
};

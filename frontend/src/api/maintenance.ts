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

// Real-mode adapters: the /api/v1/maintenance router is NOT registered on the
// casing seam and returns schedule/repair-order/cost shapes that diverge from
// what MaintenancePanel reads. Map backend keys -> the component shape with safe
// defaults so nothing calls .toLocaleString()/.length on undefined. Mock data
// already matches the TS types and is left untouched.
const adaptSchedule = (s: any): MaintenanceSchedule => ({
  ...s,
  // component reads currentMileage.toLocaleString(); backend only has dueMileage
  currentMileage: s?.currentMileage ?? s?.dueMileage ?? 0,
  priority: (s?.priority ?? 'medium') as MaintenanceSchedule['priority'],
});

const adaptRepairOrder = (o: any): RepairOrder => ({
  ...o,
  estimatedCost: o?.estimatedCost ?? o?.cost ?? 0,
  issueDescription: o?.issueDescription ?? o?.title ?? '',
  reportedDate: o?.reportedDate ?? o?.openedAt ?? '',
  partsUsed: o?.partsUsed ?? [],
  workOrderNumber:
    o?.workOrderNumber ?? (typeof o?.id === 'string' ? o.id.slice(0, 8) : ''),
  vehicleNumber: o?.vehicleNumber ?? o?.vehicleId ?? '',
  priority: (o?.priority ?? 'medium') as RepairOrder['priority'],
});

export const maintenanceApi = {
  getSchedules: async (): Promise<MaintenanceSchedule[]> => {
    if (USE_MOCK) {
      await delay(MOCK_DELAY);
      return mockMaintenanceSchedules;
    }
    const response = await api.get<any[]>('/api/v1/maintenance/schedules');
    return (response.data ?? []).map(adaptSchedule);
  },

  getScheduleById: async (id: string): Promise<MaintenanceSchedule | null> => {
    if (USE_MOCK) {
      await delay(MOCK_DELAY);
      return getMockScheduleById(id) || null;
    }
    const response = await api.get<any>(`/api/v1/maintenance/schedules/${id}`);
    return response.data ? adaptSchedule(response.data) : null;
  },

  getSchedulesByVehicle: async (vehicleId: string): Promise<MaintenanceSchedule[]> => {
    if (USE_MOCK) {
      await delay(MOCK_DELAY);
      return getMockScheduleByVehicle(vehicleId);
    }
    const response = await api.get<any[]>(`/api/v1/maintenance/vehicles/${vehicleId}/schedules`);
    return (response.data ?? []).map(adaptSchedule);
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
    const response = await api.post<any>('/api/v1/maintenance/schedules', schedule);
    return adaptSchedule(response.data);
  },

  updateSchedule: async (id: string, updates: Partial<MaintenanceSchedule>): Promise<MaintenanceSchedule> => {
    if (USE_MOCK) {
      await delay(MOCK_DELAY);
      const schedule = getMockScheduleById(id);
      if (!schedule) throw new Error('Schedule not found');
      return { ...schedule, ...updates };
    }
    const response = await api.patch<any>(`/api/v1/maintenance/schedules/${id}`, updates);
    return adaptSchedule(response.data);
  },

  getOverdueMaintenance: async (): Promise<MaintenanceSchedule[]> => {
    if (USE_MOCK) {
      await delay(MOCK_DELAY);
      return getMockOverdueMaintenance();
    }
    const response = await api.get<any[]>('/api/v1/maintenance/schedules?status=overdue');
    return (response.data ?? []).map(adaptSchedule);
  },

  getUpcomingMaintenance: async (days: number = 30): Promise<MaintenanceSchedule[]> => {
    if (USE_MOCK) {
      await delay(MOCK_DELAY);
      return getMockUpcomingMaintenance(days);
    }
    const response = await api.get<any[]>(`/api/v1/maintenance/schedules?upcoming=${days}`);
    return (response.data ?? []).map(adaptSchedule);
  },

  getRepairOrders: async (): Promise<RepairOrder[]> => {
    if (USE_MOCK) {
      await delay(MOCK_DELAY);
      return mockRepairOrders;
    }
    const response = await api.get<any[]>('/api/v1/maintenance/repair-orders');
    return (response.data ?? []).map(adaptRepairOrder);
  },

  getRepairOrderById: async (id: string): Promise<RepairOrder | null> => {
    if (USE_MOCK) {
      await delay(MOCK_DELAY);
      return getMockRepairOrderById(id) || null;
    }
    const response = await api.get<any>(`/api/v1/maintenance/repair-orders/${id}`);
    return response.data ? adaptRepairOrder(response.data) : null;
  },

  getRepairOrdersByVehicle: async (vehicleId: string): Promise<RepairOrder[]> => {
    if (USE_MOCK) {
      await delay(MOCK_DELAY);
      return getMockRepairOrdersByVehicle(vehicleId);
    }
    const response = await api.get<any[]>(`/api/v1/maintenance/vehicles/${vehicleId}/repair-orders`);
    return (response.data ?? []).map(adaptRepairOrder);
  },

  getActiveRepairOrders: async (): Promise<RepairOrder[]> => {
    if (USE_MOCK) {
      await delay(MOCK_DELAY);
      return getMockActiveRepairOrders();
    }
    const response = await api.get<any[]>('/api/v1/maintenance/repair-orders?status=active');
    return (response.data ?? []).map(adaptRepairOrder);
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
    const response = await api.post<any>('/api/v1/maintenance/repair-orders', order);
    return adaptRepairOrder(response.data);
  },

  updateRepairOrder: async (id: string, updates: Partial<RepairOrder>): Promise<RepairOrder> => {
    if (USE_MOCK) {
      await delay(MOCK_DELAY);
      const order = getMockRepairOrderById(id);
      if (!order) throw new Error('Repair order not found');
      return { ...order, ...updates };
    }
    const response = await api.patch<any>(`/api/v1/maintenance/repair-orders/${id}`, updates);
    return adaptRepairOrder(response.data);
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
    // Backend /costs returns { ytdTotal, byCategory }; the Costs tab reads
    // totalYTD/monthlyAverage/costPerVehicle/upcomingEstimated/monthlyBreakdown.
    const response = await api.get<any>('/api/v1/maintenance/costs');
    const d = response.data ?? {};
    const ytd = d.ytdTotal ?? d.totalYTD ?? 0;
    return {
      totalYTD: ytd,
      monthlyAverage: ytd / 12,
      costPerVehicle: 0,
      upcomingEstimated: 0,
      byCategory: d.byCategory ?? {},
      monthlyBreakdown: d.monthlyBreakdown ?? [],
    };
  },

  getMaintenanceStatistics: async () => {
    if (USE_MOCK) {
      await delay(MOCK_DELAY);
      return getMaintenanceStatistics();
    }
    // Backend returns { scheduledCount, overdueCount, activeRepairs, ... };
    // the panel reads totalSchedules/overdue/activeROs/urgentROs.
    const response = await api.get<any>('/api/v1/maintenance/statistics');
    const d = response.data ?? {};
    return {
      totalSchedules: d.scheduledCount ?? 0,
      overdue: d.overdueCount ?? 0,
      activeROs: d.activeRepairs ?? 0,
      urgentROs: 0,
    };
  },
};

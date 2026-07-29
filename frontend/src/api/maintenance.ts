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
/**
 * NOTHING IS INVENTED HERE ANY MORE. This adapter used to fill two fields the wire did
 * not carry:
 *
 *   `currentMileage: s?.currentMileage ?? s?.dueMileage ?? 0` — the backend has no such
 *   column. It stores `due_odometer_miles`, the odometer reading at which the service
 *   falls due. The panel printed it as "Mileage: 128,500", which a technician reads as
 *   where the vehicle IS, not where it has to be serviced — and with neither value
 *   present it printed "Mileage: 0", a vehicle with no miles on it.
 *
 *   `priority: s?.priority ?? 'medium'` — the column did not exist until migration 054,
 *   so EVERY schedule rendered as 'medium', which is not even a member of the declared
 *   union ('low' | 'normal' | 'high' | 'urgent'). Whatever the operator selected on the
 *   form was discarded by the handler and overwritten by this default on the way back.
 *
 * The wire now carries `priority`, and `currentMileage` has been removed from the type
 * rather than manufactured — a schedule knows when service is DUE; it does not know the
 * vehicle's present odometer.
 */
const adaptSchedule = (s: any): MaintenanceSchedule => ({ ...s });

/**
 * Renaming is fine here; inventing is not. `repair_orders` really does store title,
 * opened_at, cost, priority and vehicle_id, so mapping those onto the names the panel
 * reads is honest. Two entries were not renames:
 *
 *   `workOrderNumber: o.id.slice(0, 8)` — the first eight characters of a UUID, rendered
 *   as the heading of every row. A technician reads that as a work-order number and
 *   quotes it to a vendor. No system ever issued it. There is no work-order number in
 *   this schema, so the row is keyed on the identifier that does exist.
 *
 *   `estimatedCost: … ?? 0` — the column is `cost`, what the repair COST, and a null one
 *   became "$0" under a label reading "estimated". A repair with no cost recorded is not
 *   a free repair. It stays undefined and the panel omits the line.
 *
 * `partsUsed`, `laborHours`, `assignedTechnician` and `actualCost` have no columns at
 * all; each is rendered conditionally, so they are simply never shown. Recorded rather
 * than faked — see the note in defect-class-sweeps.md.
 */
const adaptRepairOrder = (o: any): RepairOrder => ({
  ...o,
  cost: o?.cost,
  issueDescription: o?.issueDescription ?? o?.title ?? '',
  reportedDate: o?.reportedDate ?? o?.openedAt ?? '',
  partsUsed: o?.partsUsed ?? [],
  vehicleNumber: o?.vehicleNumber ?? o?.vehicleId ?? '',
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

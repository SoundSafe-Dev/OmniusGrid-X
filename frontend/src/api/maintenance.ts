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

// Down to the one field that is genuinely client-side. `issueDescription` and `reportedDate`
// were renames performed here — real data (`title`, `openedAt`) under names no endpoint sends —
// and `partsUsed: [] ` defaulted an array for a table that has no parts. Renaming the type to
// match the wire removed the need for all of it; what is left derives `vehicleNumber`, which
// the serializer really does not send.
const adaptRepairOrder = (o: any): RepairOrder => ({
  ...o,
  cost: o?.cost,
  description: o?.description ?? null,
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
      // The mock used to mint a `WO-YYYY-NNNN` work-order number here. Nothing on the server
      // issues one, so the mock path produced an identifier the real path never could — which
      // is how a synthesised number ended up looking like a product feature.
      const newOrder: RepairOrder = {
        ...order as RepairOrder,
        id: `ro-${Date.now()}`,
        status: 'reported',
        openedAt: new Date().toISOString(),
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
    // THE SERVER NOW COMPUTES ALL SIX. It used to return { ytdTotal, byCategory } and
    // nothing else, while the Costs tab read five figures, so three were manufactured here:
    //
    //   `costPerVehicle: 0`     — a hardcoded zero, rendered as "Per Vehicle $0".
    //   `upcomingEstimated: 0`  — a hardcoded zero, rendered in a highlighted box as
    //                             "Upcoming (Est.) $0", which reads as "nothing is coming
    //                             up" rather than "nobody calculated this".
    //   `monthlyAverage: ytd/12` — YTD divided by twelve regardless of how many months
    //                             have actually elapsed. In February that understates the
    //                             true monthly average roughly sixfold, and it is wrong in
    //                             every month except December.
    //
    // Removing them was right and left four blank rows; `/maintenance/costs` computes each
    // from real columns now (repair costs by month, schedules' estimated_cost, the vehicle
    // count). The conditional spreads stay: a deployment running an older backend still
    // sends nothing for them, and an absent row prompts a question where "$0" answers one.
    const response = await api.get<any>('/api/v1/maintenance/costs');
    const d = response.data ?? {};
    return {
      ytdTotal: d.ytdTotal,
      byCategory: d.byCategory ?? {},
      monthlyBreakdown: d.monthlyBreakdown ?? [],
      ...(d.monthlyAverage != null ? { monthlyAverage: d.monthlyAverage } : {}),
      ...(d.costPerVehicle != null ? { costPerVehicle: d.costPerVehicle } : {}),
      ...(d.upcomingEstimated != null ? { upcomingEstimated: d.upcomingEstimated } : {}),
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

import { api } from './client';
import type { 
  FuelEfficiencyData,
  IdleTimeData,
  OnTimePerformanceData,
  VehicleHealthScoreData,
  CostPerMileData,
  DTCCountData,
  TimeRange
} from '../types';
import {
  mockFuelEfficiencyData,
  mockIdleTimeData,
  mockOnTimePerformanceData,
  mockVehicleHealthScoreData,
  mockCostPerMileData,
  mockDTCCountData,
  getMockKPIDataByRange,
} from './mocks/kpiMocks';

import { USE_MOCK } from './mockMode';
import { toCamel } from './transform';
const MOCK_DELAY = 300;
const delay = (ms: number) => new Promise(resolve => setTimeout(resolve, ms));

export const kpiApi = {
  getFuelEfficiency: async (timeRange: TimeRange = 'month'): Promise<FuelEfficiencyData> => {
    if (USE_MOCK) {
      await delay(MOCK_DELAY);
      return mockFuelEfficiencyData;
    }
    const response = await api.get<any>(`/api/v1/kpi/fuel-efficiency?range=${timeRange}`);
    return toCamel<FuelEfficiencyData>(response.data);
  },

  getIdleTime: async (timeRange: TimeRange = 'month'): Promise<IdleTimeData> => {
    if (USE_MOCK) {
      await delay(MOCK_DELAY);
      return mockIdleTimeData;
    }
    const response = await api.get<any>(`/api/v1/kpi/idle-time?range=${timeRange}`);
    return toCamel<IdleTimeData>(response.data);
  },

  getOnTimePerformance: async (timeRange: TimeRange = 'month'): Promise<OnTimePerformanceData> => {
    if (USE_MOCK) {
      await delay(MOCK_DELAY);
      return mockOnTimePerformanceData;
    }
    const response = await api.get<any>(`/api/v1/kpi/on-time-performance?range=${timeRange}`);
    return toCamel<OnTimePerformanceData>(response.data);
  },

  getVehicleHealthScore: async (): Promise<VehicleHealthScoreData> => {
    if (USE_MOCK) {
      await delay(MOCK_DELAY);
      return mockVehicleHealthScoreData;
    }
    const response = await api.get<any>('/api/v1/kpi/vehicle-health');
    return toCamel<VehicleHealthScoreData>(response.data);
  },

  getCostPerMile: async (timeRange: TimeRange = 'month'): Promise<CostPerMileData> => {
    if (USE_MOCK) {
      await delay(MOCK_DELAY);
      return mockCostPerMileData;
    }
    const response = await api.get<any>(`/api/v1/kpi/cost-per-mile?range=${timeRange}`);
    return toCamel<CostPerMileData>(response.data);
  },

  getDTCCount: async (): Promise<DTCCountData> => {
    if (USE_MOCK) {
      await delay(MOCK_DELAY);
      return mockDTCCountData;
    }
    const response = await api.get<any>('/api/v1/kpi/dtc-count');
    return toCamel<DTCCountData>(response.data);
  },

  getAllKPIs: async (timeRange: TimeRange = 'month') => {
    if (USE_MOCK) {
      await delay(MOCK_DELAY);
      return getMockKPIDataByRange(timeRange);
    }
    const response = await api.get<any>(`/api/v1/kpi/dashboard?range=${timeRange}`);
    return toCamel(response.data);
  },
};

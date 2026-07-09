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

// Env toggle: mock by default so demos work offline, real when VITE_USE_MOCK=false.
const USE_MOCK = import.meta.env.VITE_USE_MOCK !== 'false';
const MOCK_DELAY = 300;
const delay = (ms: number) => new Promise(resolve => setTimeout(resolve, ms));

export const kpiApi = {
  getFuelEfficiency: async (timeRange: TimeRange = 'month'): Promise<FuelEfficiencyData> => {
    if (USE_MOCK) {
      await delay(MOCK_DELAY);
      return mockFuelEfficiencyData;
    }
    const response = await api.get<FuelEfficiencyData>(`/api/v1/kpi/fuel-efficiency?range=${timeRange}`);
    return response.data;
  },

  getIdleTime: async (timeRange: TimeRange = 'month'): Promise<IdleTimeData> => {
    if (USE_MOCK) {
      await delay(MOCK_DELAY);
      return mockIdleTimeData;
    }
    const response = await api.get<IdleTimeData>(`/api/v1/kpi/idle-time?range=${timeRange}`);
    return response.data;
  },

  getOnTimePerformance: async (timeRange: TimeRange = 'month'): Promise<OnTimePerformanceData> => {
    if (USE_MOCK) {
      await delay(MOCK_DELAY);
      return mockOnTimePerformanceData;
    }
    const response = await api.get<OnTimePerformanceData>(`/api/v1/kpi/on-time-performance?range=${timeRange}`);
    return response.data;
  },

  getVehicleHealthScore: async (): Promise<VehicleHealthScoreData> => {
    if (USE_MOCK) {
      await delay(MOCK_DELAY);
      return mockVehicleHealthScoreData;
    }
    const response = await api.get<VehicleHealthScoreData>('/api/v1/kpi/vehicle-health');
    return response.data;
  },

  getCostPerMile: async (timeRange: TimeRange = 'month'): Promise<CostPerMileData> => {
    if (USE_MOCK) {
      await delay(MOCK_DELAY);
      return mockCostPerMileData;
    }
    const response = await api.get<CostPerMileData>(`/api/v1/kpi/cost-per-mile?range=${timeRange}`);
    return response.data;
  },

  getDTCCount: async (): Promise<DTCCountData> => {
    if (USE_MOCK) {
      await delay(MOCK_DELAY);
      return mockDTCCountData;
    }
    const response = await api.get<DTCCountData>('/api/v1/kpi/dtc-count');
    return response.data;
  },

  getAllKPIs: async (timeRange: TimeRange = 'month') => {
    if (USE_MOCK) {
      await delay(MOCK_DELAY);
      return getMockKPIDataByRange(timeRange);
    }
    const response = await api.get(`/api/v1/kpi/dashboard?range=${timeRange}`);
    return response.data;
  },
};

import type { 
  FuelEfficiencyData,
  IdleTimeData,
  OnTimePerformanceData,
  VehicleHealthScoreData,
  CostPerMileData,
  DTCCountData,
  TimeRange
} from '../../types';

// Mock Fuel Efficiency Data
export const mockFuelEfficiencyData: FuelEfficiencyData = {
  fleetAverage: 7.8,
  unit: 'mpg',
  bestPerformers: [
    { vehicleId: 'vehicle-5', vehicleNumber: 'TRK-005', efficiency: 8.6 },
    { vehicleId: 'vehicle-3', vehicleNumber: 'TRK-003', efficiency: 8.2 },
    { vehicleId: 'vehicle-1', vehicleNumber: 'TRK-001', efficiency: 7.9 },
  ],
  worstPerformers: [
    { vehicleId: 'vehicle-6', vehicleNumber: 'TRK-006', efficiency: 6.5 },
    { vehicleId: 'vehicle-2', vehicleNumber: 'TRK-002', efficiency: 6.8 },
    { vehicleId: 'vehicle-4', vehicleNumber: 'TRK-004', efficiency: 7.1 },
  ],
  trend: [
    { date: '2024-07-01', value: 7.5 },
    { date: '2024-08-01', value: 7.6 },
    { date: '2024-09-01', value: 7.7 },
    { date: '2024-10-01', value: 7.6 },
    { date: '2024-11-01', value: 7.8 },
    { date: '2024-12-01', value: 7.8 },
  ],
  byVehicle: {
    'vehicle-1': 7.9,
    'vehicle-2': 6.8,
    'vehicle-3': 8.2,
    'vehicle-4': 7.1,
    'vehicle-5': 8.6,
    'vehicle-6': 6.5,
  },
  totalFuelConsumed: 24580,
  totalDistance: 191780,
};

// Mock Idle Time Data
export const mockIdleTimeData: IdleTimeData = {
  totalHours: 312.5,
  percentageOfRuntime: 18.2,
  costImpact: 4687.50,
  byVehicle: {
    'vehicle-1': { hours: 45.2, percentage: 15.8, cost: 678.00 },
    'vehicle-2': { hours: 78.5, percentage: 28.5, cost: 1177.50 },
    'vehicle-3': { hours: 38.2, percentage: 12.3, cost: 573.00 },
    'vehicle-4': { hours: 52.0, percentage: 19.2, cost: 780.00 },
    'vehicle-5': { hours: 28.5, percentage: 10.5, cost: 427.50 },
    'vehicle-6': { hours: 70.1, percentage: 31.8, cost: 1051.50 },
  },
  trend: [
    { date: '2024-07-01', hours: 58.2, cost: 873.00 },
    { date: '2024-08-01', hours: 54.5, cost: 817.50 },
    { date: '2024-09-01', hours: 49.8, cost: 747.00 },
    { date: '2024-10-01', hours: 52.1, cost: 781.50 },
    { date: '2024-11-01', hours: 48.5, cost: 727.50 },
    { date: '2024-12-01', hours: 49.4, cost: 741.00 },
  ],
};

// Mock On-Time Performance Data
export const mockOnTimePerformanceData: OnTimePerformanceData = {
  overallPercentage: 91.5,
  onTimeCount: 183,
  lateCount: 17,
  byCarrier: {
    'Swift Transportation': 94.2,
    'Schneider National': 89.8,
    'JB Hunt': 92.5,
    'FedEx Freight': 90.1,
  },
  byRoute: {
    'I-80 Corridor': 95.5,
    'I-40 Corridor': 88.3,
    'I-70 Corridor': 91.2,
    'I-95 Corridor': 89.7,
    'I-10 Corridor': 93.1,
  },
  trend: [
    { date: '2024-07-01', percentage: 89.2, onTime: 33, total: 37 },
    { date: '2024-08-01', percentage: 90.5, onTime: 38, total: 42 },
    { date: '2024-09-01', percentage: 92.1, onTime: 35, total: 38 },
    { date: '2024-10-01', percentage: 88.9, onTime: 32, total: 36 },
    { date: '2024-11-01', percentage: 93.5, onTime: 29, total: 31 },
    { date: '2024-12-01', percentage: 95.0, onTime: 16, total: 16 },
  ],
};

// Mock Vehicle Health Score Data
export const mockVehicleHealthScoreData: VehicleHealthScoreData = {
  fleetAverage: 83.8,
  byVehicle: {
    'vehicle-1': 92,
    'vehicle-2': 78,
    'vehicle-3': 88,
    'vehicle-4': 85,
    'vehicle-5': 95,
    'vehicle-6': 65,
  },
  criticalCount: 2,
  warningCount: 2,
  healthyCount: 2,
  factors: {
    dtcs: 25,
    maintenance: 20,
    safety: 30,
  },
};

// Mock Cost Per Mile Data
export const mockCostPerMileData: CostPerMileData = {
  totalCost: 89250,
  totalMiles: 191780,
  averageCostPerMile: 0.465,
  breakdown: {
    fuel: 45875,
    maintenance: 28500,
    insurance: 9875,
    other: 5000,
  },
  byVehicle: {
    'vehicle-1': 0.42,
    'vehicle-2': 0.52,
    'vehicle-3': 0.38,
    'vehicle-4': 0.48,
    'vehicle-5': 0.35,
    'vehicle-6': 0.55,
  },
  trend: [
    { date: '2024-07-01', cost: 12500, miles: 28500 },
    { date: '2024-08-01', cost: 13200, miles: 29800 },
    { date: '2024-09-01', cost: 11800, miles: 27600 },
    { date: '2024-10-01', cost: 14500, miles: 31200 },
    { date: '2024-11-01', cost: 12800, miles: 29100 },
    { date: '2024-12-01', cost: 4450, miles: 14580 },
  ],
};

// Mock DTC Count Data
export const mockDTCCountData: DTCCountData = {
  totalActive: 6,
  criticalCount: 2,
  byVehicle: {
    'vehicle-1': 1,
    'vehicle-2': 2,
    'vehicle-3': 0,
    'vehicle-4': 1,
    'vehicle-5': 0,
    'vehicle-6': 2,
  },
  bySystem: {
    'engine': 3,
    'transmission': 1,
    'emissions': 1,
    'safety': 1,
    'other': 0,
  },
  recent: [
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
      code: 'P0101',
      description: 'Mass Air Flow Sensor Circuit Range/Performance',
      severity: 'medium',
      system: 'engine',
      timestamp: new Date(Date.now() - 2 * 24 * 60 * 60 * 1000).toISOString(),
      cleared: false,
      vehicleId: 'vehicle-1',
      vehicleNumber: 'TRK-001',
    },
  ],
  trend: [
    { date: '2024-07-01', count: 4, cleared: 2 },
    { date: '2024-08-01', count: 5, cleared: 3 },
    { date: '2024-09-01', count: 3, cleared: 4 },
    { date: '2024-10-01', count: 6, cleared: 2 },
    { date: '2024-11-01', count: 4, cleared: 3 },
    { date: '2024-12-01', count: 6, cleared: 1 },
  ],
};

// Helper function to get all KPI data
export const getAllMockKPIData = () => ({
  fuelEfficiency: mockFuelEfficiencyData,
  idleTime: mockIdleTimeData,
  onTimePerformance: mockOnTimePerformanceData,
  vehicleHealth: mockVehicleHealthScoreData,
  costPerMile: mockCostPerMileData,
  dtcCount: mockDTCCountData,
});

// Helper to get KPI data by time range (simulates filtering)
export const getMockKPIDataByRange = (_range: TimeRange) => {
  // In real implementation, this would filter based on the time range
  return getAllMockKPIData();
};

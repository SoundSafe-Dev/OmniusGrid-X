// NOTE: `currentMileage` was removed from every fixture here along with the field
// itself. The API has never sent it — `maintenance_schedules` stores only
// `due_odometer_miles` — and the mock supplying it is why every test was green
// while the real path rendered the DUE mileage (or 0) under a "Mileage:" label.
// A mock that is more generous than the wire hides exactly the defects mock-mode
// testing is supposed to surface.
import type { 
  MaintenanceSchedule, 
  RepairOrder, 
  ServiceHistoryEntry,
  MaintenanceCosts 
} from '../../types';

// Mock Maintenance Schedules
export const mockMaintenanceSchedules: MaintenanceSchedule[] = [
  {
    id: 'maint-001',
    vehicleId: 'vehicle-1',
    vehicleNumber: 'TRK-001',
    serviceType: 'oil_change',
    description: 'Regular 15,000 mile oil change service',
    scheduledDate: new Date(Date.now() + 5 * 24 * 60 * 60 * 1000).toISOString(),
    dueMileage: 145000,
    status: 'scheduled',
    priority: 'normal',
    estimatedCost: 125,
    notes: 'Use synthetic oil as per manufacturer recommendation',
  },
  {
    id: 'maint-002',
    vehicleId: 'vehicle-2',
    vehicleNumber: 'TRK-002',
    serviceType: 'brake_inspection',
    description: 'Brake pad replacement and rotor inspection',
    scheduledDate: new Date(Date.now() - 2 * 24 * 60 * 60 * 1000).toISOString(),
    dueMileage: 195000,
    status: 'overdue',
    priority: 'high',
    estimatedCost: 450,
    notes: 'Driver reported squealing brakes',
  },
  {
    id: 'maint-003',
    vehicleId: 'vehicle-3',
    vehicleNumber: 'TRK-003',
    serviceType: 'tire_rotation',
    description: 'Regular tire rotation and pressure check',
    scheduledDate: new Date(Date.now() + 10 * 24 * 60 * 60 * 1000).toISOString(),
    dueMileage: 105000,
    status: 'scheduled',
    priority: 'low',
    estimatedCost: 45,
    notes: 'Check for uneven wear patterns',
  },
  {
    id: 'maint-004',
    vehicleId: 'vehicle-4',
    vehicleNumber: 'TRK-004',
    serviceType: 'transmission_service',
    description: 'Transmission fluid flush and filter replacement',
    scheduledDate: new Date(Date.now() + 3 * 24 * 60 * 60 * 1000).toISOString(),
    dueMileage: 160000,
    status: 'scheduled',
    priority: 'high',
    estimatedCost: 350,
    notes: 'Critical service - P0705 code active',
  },
  {
    id: 'maint-005',
    vehicleId: 'vehicle-5',
    vehicleNumber: 'TRK-005',
    serviceType: 'engine_tuneup',
    description: 'Full engine tune-up: spark plugs, filters, belts',
    scheduledDate: new Date(Date.now() + 15 * 24 * 60 * 60 * 1000).toISOString(),
    dueMileage: 85000,
    status: 'scheduled',
    priority: 'normal',
    estimatedCost: 275,
    notes: 'Preventive maintenance at 80k miles',
  },
  {
    id: 'maint-006',
    vehicleId: 'vehicle-6',
    vehicleNumber: 'TRK-006',
    serviceType: 'annual_inspection',
    description: 'Annual DOT safety inspection',
    scheduledDate: new Date(Date.now() - 5 * 24 * 60 * 60 * 1000).toISOString(),
    dueMileage: undefined,
    status: 'overdue',
    priority: 'urgent',
    estimatedCost: 150,
    notes: 'Vehicle cannot operate commercially until inspection completed',
  },
  {
    id: 'maint-007',
    vehicleId: 'vehicle-1',
    vehicleNumber: 'TRK-001',
    serviceType: 'other',
    description: 'Air conditioning system check',
    scheduledDate: new Date(Date.now() + 20 * 24 * 60 * 60 * 1000).toISOString(),
    dueMileage: undefined,
    status: 'scheduled',
    priority: 'low',
    estimatedCost: 85,
    notes: 'Driver reported weak cooling performance',
  },
];

// Mock Repair Orders
export const mockRepairOrders: RepairOrder[] = [
  {
    id: 'ro-001',
    vehicleId: 'vehicle-4',
    vehicleNumber: 'TRK-004',
    title: 'Transmission slipping during gear changes, check engine light on',
    openedAt: new Date(Date.now() - 7 * 24 * 60 * 60 * 1000).toISOString(),
    status: 'in_progress',
    priority: 'high',
    vendor: 'Riverside Diesel Service',
    category: 'transmission',
    cost: 2500,
  },
  {
    id: 'ro-002',
    vehicleId: 'vehicle-2',
    vehicleNumber: 'TRK-002',
    title: 'Engine misfiring under load, rough idle',
    openedAt: new Date(Date.now() - 5 * 24 * 60 * 60 * 1000).toISOString(),
    completedAt: new Date(Date.now() - 1 * 24 * 60 * 60 * 1000).toISOString(),
    status: 'completed',
    priority: 'high',
    vendor: 'Rodriguez Fleet Repair',
    category: 'engine',
    cost: 800,
  },
  {
    id: 'ro-003',
    vehicleId: 'vehicle-6',
    vehicleNumber: 'TRK-006',
    title: 'Airbag warning light illuminated, potential system fault',
    openedAt: new Date(Date.now() - 2 * 24 * 60 * 60 * 1000).toISOString(),
    status: 'waiting_parts',
    priority: 'urgent',
    vendor: 'Northgate Commercial Vehicles',
    category: 'brakes',
    cost: 1200,
  },
  {
    id: 'ro-004',
    vehicleId: 'vehicle-1',
    vehicleNumber: 'TRK-001',
    title: 'Check engine light - MAF sensor performance issue',
    openedAt: new Date(Date.now() - 10 * 24 * 60 * 60 * 1000).toISOString(),
    completedAt: new Date(Date.now() - 8 * 24 * 60 * 60 * 1000).toISOString(),
    status: 'completed',
    priority: 'normal',
    vendor: 'Anderson Truck Center',
    category: 'electrical',
    cost: 200,
  },
  {
    id: 'ro-005',
    vehicleId: 'vehicle-3',
    vehicleNumber: 'TRK-003',
    title: 'Vehicle speed sensor intermittent failure',
    openedAt: new Date(Date.now() - 12 * 24 * 60 * 60 * 1000).toISOString(),
    completedAt: new Date(Date.now() - 10 * 24 * 60 * 60 * 1000).toISOString(),
    status: 'completed',
    priority: 'low',
    vendor: 'Rodriguez Fleet Repair',
    category: 'sensors',
    cost: 150,
  },
  {
    id: 'ro-006',
    vehicleId: 'vehicle-2',
    vehicleNumber: 'TRK-002',
    title: 'Brake system warning - squealing noise during braking',
    openedAt: new Date(Date.now() - 1 * 24 * 60 * 60 * 1000).toISOString(),
    status: 'reported',
    priority: 'high',
    vendor: undefined,
    category: 'brakes',
    cost: 450,
  },
];
// Mock Service History
export const mockServiceHistory: ServiceHistoryEntry[] = [
  {
    id: 'sh-001',
    vehicleId: 'vehicle-1',
    vehicleNumber: 'TRK-001',
    serviceType: 'Oil Change',
    description: '15,000 mile synthetic oil change service',
    serviceDate: new Date(Date.now() - 90 * 24 * 60 * 60 * 1000).toISOString(),
    mileageAtService: 115000,
    cost: 125,
    technician: 'Tom Anderson',
    notes: 'Filter replaced, full synthetic 5W-30 used',
    partsReplaced: ['Oil Filter', 'Engine Oil (10qt)'],
  },
  {
    id: 'sh-002',
    vehicleId: 'vehicle-1',
    vehicleNumber: 'TRK-001',
    serviceType: 'Tire Rotation',
    description: 'Regular tire rotation and balance',
    serviceDate: new Date(Date.now() - 85 * 24 * 60 * 60 * 1000).toISOString(),
    mileageAtService: 115500,
    cost: 65,
    technician: 'Mike Rodriguez',
    partsReplaced: [],
  },
  {
    id: 'sh-003',
    vehicleId: 'vehicle-2',
    vehicleNumber: 'TRK-002',
    serviceType: 'Transmission Service',
    description: '30,000 mile transmission fluid change',
    serviceDate: new Date(Date.now() - 180 * 24 * 60 * 60 * 1000).toISOString(),
    mileageAtService: 165000,
    cost: 325,
    technician: 'Steve Williams',
    notes: 'Filter and fluid replaced, no issues found',
    partsReplaced: ['Transmission Filter', 'ATF Fluid (10qt)'],
  },
  {
    id: 'sh-004',
    vehicleId: 'vehicle-3',
    vehicleNumber: 'TRK-003',
    serviceType: 'Annual DOT Inspection',
    description: 'Annual commercial vehicle safety inspection',
    serviceDate: new Date(Date.now() - 200 * 24 * 60 * 60 * 1000).toISOString(),
    mileageAtService: 85000,
    cost: 150,
    technician: 'Lisa Thompson',
    notes: 'Passed inspection, brake pads at 60%',
    partsReplaced: [],
  },
  {
    id: 'sh-005',
    vehicleId: 'vehicle-4',
    vehicleNumber: 'TRK-004',
    serviceType: 'Brake Service',
    description: 'Brake pad and rotor replacement - front axle',
    serviceDate: new Date(Date.now() - 120 * 24 * 60 * 60 * 1000).toISOString(),
    mileageAtService: 140000,
    cost: 580,
    technician: 'Mike Rodriguez',
    notes: 'Rotors resurfaced, ceramic pads installed',
    partsReplaced: ['Brake Pads - Front', 'Brake Rotors - Front'],
  },
  {
    id: 'sh-006',
    vehicleId: 'vehicle-5',
    vehicleNumber: 'TRK-005',
    serviceType: 'Wheel Alignment',
    description: 'Four-wheel alignment and camber adjustment',
    serviceDate: new Date(Date.now() - 60 * 24 * 60 * 60 * 1000).toISOString(),
    mileageAtService: 65000,
    cost: 95,
    technician: 'Tom Anderson',
    partsReplaced: [],
  },
  {
    id: 'sh-007',
    vehicleId: 'vehicle-6',
    vehicleNumber: 'TRK-006',
    serviceType: 'Engine Tune-up',
    description: 'Complete engine tune-up at 200k miles',
    serviceDate: new Date(Date.now() - 120 * 24 * 60 * 60 * 1000).toISOString(),
    mileageAtService: 200000,
    cost: 450,
    technician: 'Steve Williams',
    notes: 'Spark plugs, filters, belts replaced',
    partsReplaced: ['Spark Plugs (8)', 'Air Filter', 'Fuel Filter', 'Serpentine Belt'],
  },
  {
    id: 'sh-008',
    vehicleId: 'vehicle-2',
    vehicleNumber: 'TRK-002',
    serviceType: 'Tire Replacement',
    description: 'Steer axle tire replacement - uneven wear',
    serviceDate: new Date(Date.now() - 45 * 24 * 60 * 60 * 1000).toISOString(),
    mileageAtService: 175000,
    cost: 720,
    technician: 'Mike Rodriguez',
    notes: 'Two steer tires replaced, alignment performed',
    partsReplaced: ['Steer Tires (2)', 'Wheel Alignment'],
  },
];

// Mock Maintenance Costs
export const mockMaintenanceCosts: MaintenanceCosts = {
  ytdTotal: 48750,
  monthlyAverage: 4062,
  costPerVehicle: 8125,
  upcomingEstimated: 8500,
  byCategory: {
    'Preventive Maintenance': 15200,
    'Repairs': 28500,
    'Inspections': 1800,
    'Tires': 2850,
    'Other': 400,
  },
  // `YYYY-MM`, matching what `/maintenance/costs` sends. It was "Jan 2024", and the panel's
  // label read `month.split(' ')[0]` — which suited this fixture and rendered the real value
  // as the literal "2026-01". A mock in a shape no endpoint produces tests the mock.
  monthlyBreakdown: [
    { month: '2024-01', cost: 4200 },
    { month: '2024-02', cost: 3800 },
    { month: '2024-03', cost: 5100 },
    { month: '2024-04', cost: 3900 },
    { month: '2024-05', cost: 4250 },
    { month: '2024-06', cost: 4600 },
    { month: '2024-07', cost: 3800 },
    { month: '2024-08', cost: 4100 },
    { month: '2024-09', cost: 5200 },
    { month: '2024-10', cost: 3900 },
    { month: '2024-11', cost: 3500 },
    { month: '2024-12', cost: 2400 },
  ],
};

// Helper functions
export const getMockScheduleById = (id: string): MaintenanceSchedule | undefined => {
  return mockMaintenanceSchedules.find(s => s.id === id);
};

export const getMockScheduleByVehicle = (vehicleId: string): MaintenanceSchedule[] => {
  return mockMaintenanceSchedules.filter(s => s.vehicleId === vehicleId);
};

export const getMockOverdueMaintenance = (): MaintenanceSchedule[] => {
  return mockMaintenanceSchedules.filter(s => s.status === 'overdue');
};

export const getMockUpcomingMaintenance = (days: number = 30): MaintenanceSchedule[] => {
  const cutoff = new Date(Date.now() + days * 24 * 60 * 60 * 1000);
  return mockMaintenanceSchedules.filter(
    s => s.status === 'scheduled' && new Date(s.scheduledDate) <= cutoff
  );
};

export const getMockRepairOrderById = (id: string): RepairOrder | undefined => {
  return mockRepairOrders.find(r => r.id === id);
};

export const getMockRepairOrdersByVehicle = (vehicleId: string): RepairOrder[] => {
  return mockRepairOrders.filter(r => r.vehicleId === vehicleId);
};

export const getMockActiveRepairOrders = (): RepairOrder[] => {
  return mockRepairOrders.filter(
    r => r.status !== 'completed' && r.status !== 'cancelled'
  );
};

export const getMockServiceHistoryByVehicle = (vehicleId: string): ServiceHistoryEntry[] => {
  return mockServiceHistory.filter(h => h.vehicleId === vehicleId);
};

// Statistics helpers
export const getMaintenanceStatistics = () => {
  const totalSchedules = mockMaintenanceSchedules.length;
  const overdue = mockMaintenanceSchedules.filter(s => s.status === 'overdue').length;
  const scheduled = mockMaintenanceSchedules.filter(s => s.status === 'scheduled').length;
  const urgent = mockMaintenanceSchedules.filter(s => s.priority === 'urgent').length;
  
  const totalROs = mockRepairOrders.length;
  const activeROs = mockRepairOrders.filter(r => 
    r.status !== 'completed' && r.status !== 'cancelled'
  ).length;
  const completedROs = mockRepairOrders.filter(r => r.status === 'completed').length;
  const urgentROs = mockRepairOrders.filter(r => r.priority === 'urgent').length;
  
  return {
    totalSchedules,
    overdue,
    scheduled,
    urgent,
    totalROs,
    activeROs,
    completedROs,
    urgentROs,
  };
};

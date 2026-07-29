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
    assignedTechnician: 'Tom Anderson',
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
    assignedTechnician: 'Mike Rodriguez',
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
    assignedTechnician: 'Steve Williams',
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
    assignedTechnician: 'Lisa Thompson',
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
    workOrderNumber: 'WO-2024-0847',
    issueDescription: 'Transmission slipping during gear changes, check engine light on',
    reportedDate: new Date(Date.now() - 7 * 24 * 60 * 60 * 1000).toISOString(),
    startedDate: new Date(Date.now() - 5 * 24 * 60 * 60 * 1000).toISOString(),
    status: 'in_progress',
    priority: 'high',
    assignedTechnician: 'Steve Williams',
    cost: 2500,
    actualCost: 1850,
    partsUsed: [
      { partNumber: 'TRN-4521', description: 'Transmission Filter Kit', quantity: 1, unitCost: 85 },
      { partNumber: 'ATF-5QT', description: 'Automatic Transmission Fluid (5qt)', quantity: 2, unitCost: 45 },
      { partNumber: 'TRN-SOL-89', description: 'Shift Solenoid', quantity: 2, unitCost: 120 },
    ],
    laborHours: 8,
    relatedDTCs: ['P0705'],
  },
  {
    id: 'ro-002',
    vehicleId: 'vehicle-2',
    vehicleNumber: 'TRK-002',
    workOrderNumber: 'WO-2024-0852',
    issueDescription: 'Engine misfiring under load, rough idle',
    reportedDate: new Date(Date.now() - 5 * 24 * 60 * 60 * 1000).toISOString(),
    startedDate: new Date(Date.now() - 4 * 24 * 60 * 60 * 1000).toISOString(),
    completedDate: new Date(Date.now() - 1 * 24 * 60 * 60 * 1000).toISOString(),
    status: 'completed',
    priority: 'high',
    assignedTechnician: 'Mike Rodriguez',
    cost: 800,
    actualCost: 675,
    partsUsed: [
      { partNumber: 'SPK-SET-6', description: 'Spark Plug Set (6)', quantity: 1, unitCost: 85 },
      { partNumber: 'IGN-COIL-2', description: 'Ignition Coil', quantity: 2, unitCost: 65 },
      { partNumber: 'AIR-FLT-45', description: 'Air Filter', quantity: 1, unitCost: 28 },
    ],
    laborHours: 4,
    relatedDTCs: ['P0300', 'P0420'],
  },
  {
    id: 'ro-003',
    vehicleId: 'vehicle-6',
    vehicleNumber: 'TRK-006',
    workOrderNumber: 'WO-2024-0861',
    issueDescription: 'Airbag warning light illuminated, potential system fault',
    reportedDate: new Date(Date.now() - 2 * 24 * 60 * 60 * 1000).toISOString(),
    status: 'waiting_parts',
    priority: 'urgent',
    assignedTechnician: 'Lisa Thompson',
    cost: 1200,
    actualCost: undefined,
    partsUsed: [],
    laborHours: undefined,
    relatedDTCs: ['B1000'],
  },
  {
    id: 'ro-004',
    vehicleId: 'vehicle-1',
    vehicleNumber: 'TRK-001',
    workOrderNumber: 'WO-2024-0821',
    issueDescription: 'Check engine light - MAF sensor performance issue',
    reportedDate: new Date(Date.now() - 10 * 24 * 60 * 60 * 1000).toISOString(),
    startedDate: new Date(Date.now() - 9 * 24 * 60 * 60 * 1000).toISOString(),
    completedDate: new Date(Date.now() - 8 * 24 * 60 * 60 * 1000).toISOString(),
    status: 'completed',
    priority: 'normal',
    assignedTechnician: 'Tom Anderson',
    cost: 200,
    actualCost: 175,
    partsUsed: [
      { partNumber: 'MAF-SNS-42', description: 'Mass Air Flow Sensor', quantity: 1, unitCost: 125 },
    ],
    laborHours: 1,
    relatedDTCs: ['P0101'],
  },
  {
    id: 'ro-005',
    vehicleId: 'vehicle-3',
    vehicleNumber: 'TRK-003',
    workOrderNumber: 'WO-2024-0839',
    issueDescription: 'Vehicle speed sensor intermittent failure',
    reportedDate: new Date(Date.now() - 12 * 24 * 60 * 60 * 1000).toISOString(),
    startedDate: new Date(Date.now() - 11 * 24 * 60 * 60 * 1000).toISOString(),
    completedDate: new Date(Date.now() - 10 * 24 * 60 * 60 * 1000).toISOString(),
    status: 'completed',
    priority: 'low',
    assignedTechnician: 'Mike Rodriguez',
    cost: 150,
    actualCost: 140,
    partsUsed: [
      { partNumber: 'VSS-78', description: 'Vehicle Speed Sensor', quantity: 1, unitCost: 85 },
    ],
    laborHours: 1,
    relatedDTCs: ['P0500'],
  },
  {
    id: 'ro-006',
    vehicleId: 'vehicle-2',
    vehicleNumber: 'TRK-002',
    workOrderNumber: 'WO-2024-0875',
    issueDescription: 'Brake system warning - squealing noise during braking',
    reportedDate: new Date(Date.now() - 1 * 24 * 60 * 60 * 1000).toISOString(),
    status: 'reported',
    priority: 'high',
    assignedTechnician: undefined,
    cost: 450,
    actualCost: undefined,
    partsUsed: [],
    laborHours: undefined,
    relatedDTCs: [],
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
  totalYTD: 48750,
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
  monthlyBreakdown: [
    { month: 'Jan 2024', cost: 4200 },
    { month: 'Feb 2024', cost: 3800 },
    { month: 'Mar 2024', cost: 5100 },
    { month: 'Apr 2024', cost: 3900 },
    { month: 'May 2024', cost: 4250 },
    { month: 'Jun 2024', cost: 4600 },
    { month: 'Jul 2024', cost: 3800 },
    { month: 'Aug 2024', cost: 4100 },
    { month: 'Sep 2024', cost: 5200 },
    { month: 'Oct 2024', cost: 3900 },
    { month: 'Nov 2024', cost: 3500 },
    { month: 'Dec 2024', cost: 2400 },
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

// Mock API data for demo mode when backend is unavailable
import { 
  Asset, Alarm, TelemetryPoint, DashboardOverview, 
  ActiveAlarmsResponse, OEEMetrics, FleetOEE, User,
  Workcell, Organization, PackMLState, AssetType
} from '../types';

const MOCK_DELAY = 500; // Simulate network delay

const mockAssets: Asset[] = [
  {
    id: 'asset-1',
    name: 'Printer #1 (Bambu Labs X1)',
    assetTypeId: 'printer',
    organizationId: 'org-1',
    workcellId: 'workcell-1',
    vendor: 'Bambu Labs',
    model: 'X1 Carbon',
    serialNumber: 'BLX1001',
    currentPackmlState: 'Execute',
    connectionConfig: { protocol: 'MQTT', endpoint: '192.168.1.100' },
    isInMaintenance: false,
    isActive: true,
    lastSeen: new Date().toISOString(),
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
  },
  {
    id: 'asset-2',
    name: 'Printer #2 (Bambu Labs X1)',
    assetTypeId: 'printer',
    organizationId: 'org-1',
    workcellId: 'workcell-1',
    vendor: 'Bambu Labs',
    model: 'X1 Carbon',
    serialNumber: 'BLX1002',
    currentPackmlState: 'Idle',
    connectionConfig: { protocol: 'MQTT', endpoint: '192.168.1.101' },
    isInMaintenance: false,
    isActive: true,
    lastSeen: new Date().toISOString(),
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
  },
  {
    id: 'asset-3',
    name: 'Printer #3 (QIDI X-Max 3)',
    assetTypeId: 'printer',
    organizationId: 'org-1',
    workcellId: 'workcell-1',
    vendor: 'QIDI',
    model: 'X-Max 3',
    serialNumber: 'QX3001',
    currentPackmlState: 'Held',
    connectionConfig: { protocol: 'ScreenScrape', endpoint: '192.168.1.102' },
    isInMaintenance: false,
    isActive: true,
    lastSeen: new Date().toISOString(),
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
  },
  {
    id: 'asset-4',
    name: 'Conveyor Belt A',
    assetTypeId: 'conveyor',
    organizationId: 'org-1',
    workcellId: 'workcell-2',
    vendor: 'Siemens',
    model: 'SIMATIC CF-100',
    serialNumber: 'SCF2001',
    currentPackmlState: 'Execute',
    connectionConfig: { protocol: 'OPC-UA', endpoint: 'opc.tcp://192.168.1.200' },
    isInMaintenance: false,
    isActive: true,
    lastSeen: new Date().toISOString(),
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
  },
  {
    id: 'asset-5',
    name: 'CNC Mill #1',
    assetTypeId: 'cnc',
    organizationId: 'org-1',
    workcellId: 'workcell-3',
    vendor: 'Haas',
    model: 'VF-2',
    serialNumber: 'HAAS001',
    currentPackmlState: 'Idle',
    connectionConfig: { protocol: 'MTConnect', endpoint: '192.168.1.150' },
    isInMaintenance: false,
    isActive: true,
    lastSeen: new Date().toISOString(),
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
  },
];

const mockAlarms: Alarm[] = [
  {
    id: 'alarm-1',
    assetId: 'asset-3',
    assetName: 'Printer #3 (QIDI X-Max 3)',
    alarmCode: 'TEMP_HIGH',
    severity: 'high',
    message: 'Nozzle temperature exceeds safe threshold',
    description: 'The nozzle temperature has exceeded 280°C, which is above the safe operating limit.',
    isActive: true,
    isAcknowledged: false,
    occurredAt: new Date(Date.now() - 3600000).toISOString(),
  },
  {
    id: 'alarm-2',
    assetId: 'asset-1',
    assetName: 'Printer #1 (Bambu Labs X1)',
    alarmCode: 'FILAMENT_RUNOUT',
    severity: 'medium',
    message: 'Filament runout detected',
    description: 'The AMS has detected that filament has run out on spool 1.',
    isActive: true,
    isAcknowledged: true,
    acknowledgedBy: 'user-1',
    acknowledgedAt: new Date(Date.now() - 1800000).toISOString(),
    acknowledgedComment: 'Replenished filament',
    occurredAt: new Date(Date.now() - 7200000).toISOString(),
  },
  {
    id: 'alarm-3',
    assetId: 'asset-5',
    assetName: 'CNC Mill #1',
    alarmCode: 'SPINDLE_WARN',
    severity: 'low',
    message: 'Spindle bearing temperature elevated',
    description: 'Spindle bearing temperature is at 65°C, approaching warning threshold.',
    isActive: true,
    isAcknowledged: false,
    occurredAt: new Date(Date.now() - 10800000).toISOString(),
  },
  {
    id: 'alarm-4',
    assetId: 'asset-2',
    assetName: 'Printer #2 (Bambu Labs X1)',
    alarmCode: 'BED_LEVEL_FAIL',
    severity: 'critical',
    message: 'Bed leveling failed after 3 attempts',
    description: 'Automatic bed leveling procedure failed. Manual calibration required.',
    isActive: false,
    isAcknowledged: true,
    acknowledgedBy: 'user-1',
    acknowledgedAt: new Date(Date.now() - 86400000).toISOString(),
    acknowledgedComment: 'Recalibrated bed manually',
    occurredAt: new Date(Date.now() - 90000000).toISOString(),
    clearedAt: new Date(Date.now() - 85000000).toISOString(),
  },
];

const mockUsers: User[] = [
  {
    id: 'user-1',
    email: 'admin@omniusgrid.com',
    name: 'System Administrator',
    role: 'admin',
    organizationId: 'org-1',
    isActive: true,
    lastLoginAt: new Date().toISOString(),
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
  },
  {
    id: 'user-2',
    email: 'operator@omniusgrid.com',
    name: 'Line Operator',
    role: 'operator',
    organizationId: 'org-1',
    isActive: true,
    lastLoginAt: new Date(Date.now() - 86400000).toISOString(),
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
  },
];

const mockWorkcells: Workcell[] = [
  {
    id: 'workcell-1',
    organizationId: 'org-1',
    name: '3D Printing Line A',
    description: 'Bambu Labs and QIDI 3D printers',
    location: 'Building A, Floor 1',
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
  },
  {
    id: 'workcell-2',
    organizationId: 'org-1',
    name: 'Assembly Line B',
    description: 'Conveyor and packaging systems',
    location: 'Building A, Floor 2',
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
  },
  {
    id: 'workcell-3',
    organizationId: 'org-1',
    name: 'Machining Center',
    description: 'CNC mills and lathes',
    location: 'Building B, Floor 1',
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
  },
];

const mockOrganizations: Organization[] = [
  {
    id: 'org-1',
    name: 'Main Factory',
    slug: 'main-factory',
    settings: { timezone: 'America/Chicago', language: 'en' },
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
  },
];

const mockAssetTypes: AssetType[] = [
  {
    id: 'printer',
    name: '3D Printer',
    category: 'additive_manufacturing',
    packmlConfig: { states: ['Idle', 'Execute', 'Held', 'Stopped'] },
    telemetrySchema: { temperature: 'number', progress: 'number' },
    actionSpace: ['start', 'stop', 'pause', 'resume'],
    createdAt: new Date().toISOString(),
  },
  {
    id: 'conveyor',
    name: 'Conveyor Belt',
    category: 'material_handling',
    packmlConfig: { states: ['Idle', 'Execute', 'Stopped'] },
    telemetrySchema: { speed: 'number', load: 'number' },
    actionSpace: ['start', 'stop', 'set_speed'],
    createdAt: new Date().toISOString(),
  },
  {
    id: 'cnc',
    name: 'CNC Machine',
    category: 'subtractive_manufacturing',
    packmlConfig: { states: ['Idle', 'Execute', 'Held', 'Stopped'] },
    telemetrySchema: { spindle_rpm: 'number', feed_rate: 'number' },
    actionSpace: ['start', 'stop', 'pause', 'home'],
    createdAt: new Date().toISOString(),
  },
];

const mockDashboardOverview: DashboardOverview = {
  totalAssets: 24,
  onlineAssets: 18,
  offlineAssets: 3,
  maintenanceAssets: 3,
  activeAlarms: 3,
  criticalAlarms: 1,
  oee: 0.78,
  utilization: 0.82,
  availability: 0.91,
  performance: 0.85,
  quality: 0.99,
};

const mockActiveAlarms: ActiveAlarmsResponse = {
  count: 3,
  critical: 1,
  high: 1,
  medium: 1,
  low: 0,
  alarms: mockAlarms.filter(a => a.isActive),
};

const mockFleetOEE: FleetOEE = {
  current: 0.78,
  target: 0.85,
  trend: 'up',
  change: 0.03,
  history: Array.from({ length: 24 }, (_, i) => ({
    timestamp: new Date(Date.now() - (23 - i) * 3600000).toISOString(),
    oee: 0.75 + Math.random() * 0.1,
    availability: 0.88 + Math.random() * 0.08,
    performance: 0.82 + Math.random() * 0.06,
    quality: 0.98 + Math.random() * 0.02,
  })),
  byWorkcell: [
    { workcellId: 'workcell-1', workcellName: '3D Printing Line A', oee: 0.82 },
    { workcellId: 'workcell-2', workcellName: 'Assembly Line B', oee: 0.75 },
    { workcellId: 'workcell-3', workcellName: 'Machining Center', oee: 0.77 },
  ],
};

const mockOEEMetrics: OEEMetrics = {
  oee: 0.78,
  availability: 0.91,
  performance: 0.85,
  quality: 0.99,
  runTimeMinutes: 480,
  plannedProductionTimeMinutes: 525,
  idealCycleTimeSeconds: 120,
  totalCount: 2400,
  goodCount: 2376,
  rejectedCount: 24,
};

// Helper to simulate async delay
const delay = (ms: number) => new Promise(resolve => setTimeout(resolve, ms));

// Mock API implementation
export const mockApi = {
  // Assets
  getAssets: async (): Promise<{ items: Asset[]; total: number; skip: number; limit: number; hasMore: boolean }> => {
    await delay(MOCK_DELAY);
    return { 
      items: mockAssets, 
      total: mockAssets.length,
      skip: 0,
      limit: 100,
      hasMore: false,
    };
  },
  
  getAsset: async (id: string): Promise<Asset | undefined> => {
    await delay(MOCK_DELAY);
    return mockAssets.find(a => a.id === id);
  },
  
  // Alarms
  getAlarms: async (): Promise<{ items: Alarm[]; total: number }> => {
    await delay(MOCK_DELAY);
    return { items: mockAlarms, total: mockAlarms.length };
  },
  
  getActiveAlarms: async (): Promise<ActiveAlarmsResponse> => {
    await delay(MOCK_DELAY);
    return mockActiveAlarms;
  },
  
  acknowledgeAlarm: async (id: string): Promise<void> => {
    await delay(MOCK_DELAY);
    const alarm = mockAlarms.find(a => a.id === id);
    if (alarm) {
      alarm.isAcknowledged = true;
      alarm.acknowledgedAt = new Date().toISOString();
    }
  },
  
  // Dashboard
  getDashboardOverview: async (): Promise<DashboardOverview> => {
    await delay(MOCK_DELAY);
    return mockDashboardOverview;
  },
  
  getFleetOEE: async (): Promise<FleetOEE> => {
    await delay(MOCK_DELAY);
    return mockFleetOEE;
  },
  
  getAssetOEE: async (_assetId: string): Promise<OEEMetrics> => {
    await delay(MOCK_DELAY);
    return mockOEEMetrics;
  },
  
  // Telemetry
  getLatestTelemetry: async (assetId: string): Promise<Record<string, TelemetryPoint>> => {
    await delay(MOCK_DELAY);
    
    const asset = mockAssets.find(a => a.id === assetId);
    const timestamp = new Date().toISOString();
    
    // Machine-specific telemetry based on asset type
    switch (asset?.assetTypeId) {
      case 'printer':
        return {
          'nozzle_temp': { metricName: 'nozzle_temp', value: 245.5 + Math.random() * 10, unit: '°C', timestamp },
          'bed_temp': { metricName: 'bed_temp', value: 65.0 + Math.random() * 5, unit: '°C', timestamp },
          'progress': { metricName: 'progress', value: 67.3 + Math.random() * 10, unit: '%', timestamp },
          'print_speed': { metricName: 'print_speed', value: 150.0 + Math.random() * 20, unit: 'mm/s', timestamp },
          'layer_height': { metricName: 'layer_height', value: 0.2, unit: 'mm', timestamp },
          'filament_used': { metricName: 'filament_used', value: 1234.5, unit: 'g', timestamp },
        };
      
      case 'conveyor':
        return {
          'speed': { metricName: 'speed', value: 2.5 + Math.random() * 0.5, unit: 'm/s', timestamp },
          'load': { metricName: 'load', value: 85.2 + Math.random() * 10, unit: '%', timestamp },
          'temperature': { metricName: 'temperature', value: 45.3 + Math.random() * 5, unit: '°C', timestamp },
          'vibration': { metricName: 'vibration', value: 0.8 + Math.random() * 0.2, unit: 'g', timestamp },
          'power_consumption': { metricName: 'power_consumption', value: 3.2 + Math.random() * 0.5, unit: 'kW', timestamp },
        };
      
      case 'cnc':
        return {
          'spindle_rpm': { metricName: 'spindle_rpm', value: 12000 + Math.random() * 1000, unit: 'RPM', timestamp },
          'feed_rate': { metricName: 'feed_rate', value: 500.0 + Math.random() * 50, unit: 'mm/min', timestamp },
          'spindle_load': { metricName: 'spindle_load', value: 75.3 + Math.random() * 10, unit: '%', timestamp },
          'tool_temperature': { metricName: 'tool_temperature', value: 35.2 + Math.random() * 3, unit: '°C', timestamp },
          'cutting_force': { metricName: 'cutting_force', value: 1250.5 + Math.random() * 100, unit: 'N', timestamp },
          'position_x': { metricName: 'position_x', value: 150.5, unit: 'mm', timestamp },
          'position_y': { metricName: 'position_y', value: 75.3, unit: 'mm', timestamp },
          'position_z': { metricName: 'position_z', value: -25.8, unit: 'mm', timestamp },
        };
      
      default:
        return {
          'status': { metricName: 'status', value: 1, unit: '', timestamp },
          'temperature': { metricName: 'temperature', value: 25.0 + Math.random() * 5, unit: '°C', timestamp },
        };
    }
  },
  
  getTelemetryHistory: async (assetId: string, metricName: string): Promise<TelemetryPoint[]> => {
    await delay(MOCK_DELAY);
    
    const asset = mockAssets.find(a => a.id === assetId);
    
    // Generate machine-specific historical data
    const generateHistory = (baseValue: number, variance: number, unit: string) => {
      return Array.from({ length: 50 }, (_, i) => ({
        metricName,
        value: baseValue + (Math.random() - 0.5) * variance,
        unit,
        timestamp: new Date(Date.now() - (49 - i) * 60000).toISOString(),
      }));
    };
    
    switch (asset?.assetTypeId) {
      case 'printer':
        switch (metricName) {
          case 'nozzle_temp':
            return generateHistory(245, 20, '°C');
          case 'bed_temp':
            return generateHistory(65, 10, '°C');
          case 'progress':
            return generateHistory(50, 30, '%');
          case 'print_speed':
            return generateHistory(150, 50, 'mm/s');
          default:
            return generateHistory(100, 20, '');
        }
      
      case 'conveyor':
        switch (metricName) {
          case 'speed':
            return generateHistory(2.5, 1, 'm/s');
          case 'load':
            return generateHistory(80, 20, '%');
          case 'temperature':
            return generateHistory(45, 10, '°C');
          case 'vibration':
            return generateHistory(0.8, 0.4, 'g');
          case 'power_consumption':
            return generateHistory(3.2, 1, 'kW');
          default:
            return generateHistory(50, 20, '');
        }
      
      case 'cnc':
        switch (metricName) {
          case 'spindle_rpm':
            return generateHistory(12000, 2000, 'RPM');
          case 'feed_rate':
            return generateHistory(500, 200, 'mm/min');
          case 'spindle_load':
            return generateHistory(75, 25, '%');
          case 'tool_temperature':
            return generateHistory(35, 10, '°C');
          case 'cutting_force':
            return generateHistory(1250, 300, 'N');
          default:
            return generateHistory(100, 50, '');
        }
      
      default:
        return generateHistory(25, 10, '°C');
    }
  },
  
  // Workcells & Organizations
  getWorkcells: async (): Promise<Workcell[]> => {
    await delay(MOCK_DELAY);
    return mockWorkcells;
  },
  
  getOrganizations: async (): Promise<Organization[]> => {
    await delay(MOCK_DELAY);
    return mockOrganizations;
  },
  
  // Asset Types
  getAssetTypes: async (): Promise<AssetType[]> => {
    await delay(MOCK_DELAY);
    return mockAssetTypes;
  },
  
  // Users
  getUsers: async (): Promise<{ items: User[]; total: number }> => {
    await delay(MOCK_DELAY);
    return { items: mockUsers, total: mockUsers.length };
  },
  
  // AI Engines - Tactical
  getTacticalStatus: async () => {
    await delay(MOCK_DELAY);
    return {
      modelLoaded: true,
      modelVersion: 'v2.1.0',
      averageLatencyMs: 45.2,
      totalInferences: 154320,
      inferencesPerMinute: 120,
    };
  },
  
  // AI Engines - Strategic
  getStrategicRecommendations: async () => {
    await delay(MOCK_DELAY);
    return [
      {
        recommendationId: 'rec-1',
        assetId: 'asset-1',
        assetName: 'Printer #1',
        description: 'Increase print speed by 10% during off-peak hours',
        priority: 8,
        confidence: 0.92,
        expectedImpact: { oeeImprovement: 0.05, costSavings: 1200 },
        status: 'pending',
        validUntil: new Date(Date.now() + 86400000 * 7).toISOString(),
        createdAt: new Date().toISOString(),
      },
      {
        recommendationId: 'rec-2',
        assetId: 'asset-3',
        assetName: 'Printer #3',
        description: 'Schedule preventive maintenance for next weekend',
        priority: 9,
        confidence: 0.88,
        expectedImpact: { oeeImprovement: 0.03, timeSavings: 4 },
        status: 'pending',
        validUntil: new Date(Date.now() + 86400000 * 3).toISOString(),
        createdAt: new Date().toISOString(),
      },
    ];
  },
  
  // AI Engines - MLOps
  getMLOpsStatus: async () => {
    await delay(MOCK_DELAY);
    return {
      currentModel: 'manufacturing-optimizer-v2.1.0.pt',
      lastDeploymentAt: new Date(Date.now() - 86400000 * 2).toISOString(),
      cachedModels: [
        'manufacturing-optimizer-v2.1.0.pt',
        'manufacturing-optimizer-v2.0.5.pt',
        'manufacturing-optimizer-v1.9.0.pt',
      ],
      deploymentHistory: [
        { version: 'manufacturing-optimizer-v2.1.0.pt', deployedAt: new Date(Date.now() - 86400000 * 2).toISOString() },
        { version: 'manufacturing-optimizer-v2.0.5.pt', deployedAt: new Date(Date.now() - 86400000 * 30).toISOString(), rolledBackAt: new Date(Date.now() - 86400000 * 2).toISOString() },
      ],
      pollIntervalSeconds: 300,
      lastPollAt: new Date().toISOString(),
    };
  },
  
  // AI Engines - Cloud Gateway
  getCloudGatewayStatus: async () => {
    await delay(MOCK_DELAY);
    return {
      connected: true,
      lastSyncAt: new Date().toISOString(),
      connectionUptimeSeconds: 86400 * 5,
      mTlsCertificateExpiry: new Date(Date.now() + 86400000 * 90).toISOString(),
      egressStats: {
        totalBytesSent: 157286400,
        compressionRatio: 0.85,
        averageBandwidthKbps: 256,
        queueDepth: 12,
      },
    };
  },
};
